"""automation/object_detector.py

目标检测接口与线程安全缓存模块。

提供：
- DetectionCache：线程安全的检测结果缓存（threading.Lock 保护读写）
- detect_objects_for_display：对截图执行目标检测，返回 BoundingBoxDict 列表
- VisionOverlayController：管理后台检测线程的生命周期与缓存

置信度计算说明：
  轮廓检测不像深度学习模型那样输出概率分数，因此使用以下启发式规则估算：
  - 面积得分（0.4 权重）：轮廓面积越接近理想范围中心，得分越高
  - 矩形度得分（0.4 权重）：轮廓面积 / 外接矩形面积，越接近 1.0 说明越像矩形 UI 元素
  - 长宽比得分（0.2 权重）：宽高比越接近常见 UI 元素比例（0.5~4.0），得分越高
  最终置信度 = 三项加权和，上限 0.75（绿色留给任务匹配目标）。

GUI 窗口排除说明：
  VisionOverlayController 截图时会尝试获取 GUI 主窗口的屏幕区域，
  并将该区域从截图中涂黑（用黑色矩形覆盖），使检测器看不到 GUI 界面，
  避免 GUI 元素被误识别为目标。
"""
from __future__ import annotations

import logging
import math
import threading

import cv2
import numpy as np

from automation.vision_box_drawer import BoundingBoxDict

logger = logging.getLogger(__name__)

# 轮廓面积过滤范围
_MIN_CONTOUR_AREA: int = 400
_MAX_CONTOUR_AREA: int = 50000

# 面积得分：以对数中点为最优面积
_AREA_LOG_MIN: float = math.log(_MIN_CONTOUR_AREA)
_AREA_LOG_MAX: float = math.log(_MAX_CONTOUR_AREA)
_AREA_LOG_MID: float = (_AREA_LOG_MIN + _AREA_LOG_MAX) / 2.0

# 检测到的目标标签
_DEFAULT_LABEL: str = "detected_object"


def _compute_contour_confidence(cnt: np.ndarray) -> float:
    """根据轮廓的几何特征估算置信度。

    使用三项启发式指标加权：
    - 面积得分（权重 0.4）：面积在对数空间中越接近范围中点，得分越高
    - 矩形度得分（权重 0.4）：轮廓面积 / 外接矩形面积，越接近 1.0 越像矩形 UI 元素
    - 长宽比得分（权重 0.2）：宽高比在 [0.5, 4.0] 范围内得满分，超出则线性衰减

    Args:
        cnt: cv2.findContours 返回的单个轮廓数组。

    Returns:
        置信度浮点数，范围 [0.0, 0.75]，保留两位小数。
        上限 0.75 确保绿色（≥0.8）只出现在任务匹配目标上。
    """
    area = cv2.contourArea(cnt)
    x, y, w, h = cv2.boundingRect(cnt)

    # --- 面积得分：对数空间中距中点越近越好 ---
    log_area = math.log(max(area, 1.0))
    area_score = 1.0 - abs(log_area - _AREA_LOG_MID) / ((_AREA_LOG_MAX - _AREA_LOG_MIN) / 2.0)
    area_score = max(0.0, min(1.0, area_score))

    # --- 矩形度得分：轮廓面积 / 外接矩形面积 ---
    rect_area = float(w * h)
    rect_score = area / rect_area if rect_area > 0 else 0.0
    rect_score = max(0.0, min(1.0, rect_score))

    # --- 长宽比得分：宽高比在 [0.5, 4.0] 内满分，超出线性衰减 ---
    aspect = w / h if h > 0 else 1.0
    if 0.5 <= aspect <= 4.0:
        aspect_score = 1.0
    elif aspect < 0.5:
        aspect_score = max(0.0, aspect / 0.5)
    else:
        aspect_score = max(0.0, 1.0 - (aspect - 4.0) / 4.0)

    confidence = 0.4 * area_score + 0.4 * rect_score + 0.2 * aspect_score
    # 上限 0.75：绿色（≥0.8）只留给任务上下文匹配的目标
    return round(max(0.0, min(0.75, confidence)), 2)


def _get_gui_window_rect() -> tuple[int, int, int, int] | None:
    """尝试获取 GUI 主窗口（PyWebView）的屏幕矩形区域。

    Returns:
        (left, top, right, bottom) 屏幕坐标，获取失败时返回 None。
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

        hwnd = user32.FindWindowW(None, "AutoAgent Desktop")
        if not hwnd:
            return None

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    return None


def _mask_gui_window(frame: np.ndarray) -> np.ndarray:
    """将 GUI 窗口区域涂黑，使检测器看不到 GUI 界面。

    Args:
        frame: BGR uint8 numpy 数组（全屏截图）。

    Returns:
        涂黑 GUI 区域后的图像副本；获取窗口位置失败时原样返回。
    """
    rect = _get_gui_window_rect()
    if rect is None:
        return frame

    left, top, right, bottom = rect
    h, w = frame.shape[:2]

    x1 = max(0, left)
    y1 = max(0, top)
    x2 = min(w, right)
    y2 = min(h, bottom)

    if x2 > x1 and y2 > y1:
        masked = frame.copy()
        masked[y1:y2, x1:x2] = 0
        logger.debug("_mask_gui_window: 已涂黑 GUI 区域 [%d,%d,%d,%d]", x1, y1, x2, y2)
        return masked

    return frame


# ---------------------------------------------------------------------------
# DetectionCache
# ---------------------------------------------------------------------------


class DetectionCache:
    """线程安全的检测结果缓存。"""

    def __init__(self) -> None:
        self._boxes: list[BoundingBoxDict] = []
        self._lock: threading.Lock = threading.Lock()

    def update(self, boxes: list[BoundingBoxDict]) -> None:
        """线程安全地更新缓存内容。"""
        with self._lock:
            self._boxes = list(boxes)

    def get(self) -> list[BoundingBoxDict]:
        """线程安全地读取缓存，返回副本。"""
        with self._lock:
            return list(self._boxes)

    def clear(self) -> None:
        """线程安全地清空缓存。"""
        with self._lock:
            self._boxes = []


# ---------------------------------------------------------------------------
# _run_detection
# ---------------------------------------------------------------------------


def _run_detection(screenshot: np.ndarray) -> list[BoundingBoxDict]:
    """对截图执行轮廓检测，返回检测到的区域列表。"""
    gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, threshold1=50, threshold2=150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    results: list[BoundingBoxDict] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if _MIN_CONTOUR_AREA <= area <= _MAX_CONTOUR_AREA:
            x, y, w, h = cv2.boundingRect(cnt)
            confidence = _compute_contour_confidence(cnt)
            results.append(
                BoundingBoxDict(
                    bbox=[int(x), int(y), int(x + w), int(y + h)],
                    label=_DEFAULT_LABEL,
                    confidence=confidence,
                )
            )
            logger.debug(
                "_run_detection: 轮廓 bbox=[%d,%d,%d,%d] area=%.0f confidence=%.2f",
                x, y, x + w, y + h, area, confidence,
            )

    logger.debug("_run_detection: found %d contour(s)", len(results))
    return results


def detect_objects_for_display(screenshot: np.ndarray) -> list[BoundingBoxDict]:
    """对截图执行目标检测，返回结构化结果列表。

    无目标时返回 []；内部异常时捕获、记录 ERROR，返回 []，不向调用方抛出。
    """
    try:
        return _run_detection(screenshot)
    except Exception as exc:  # noqa: BLE001
        logger.error("detect_objects_for_display 检测异常: %s", exc)
        return []


# ---------------------------------------------------------------------------
# VisionOverlayController
# ---------------------------------------------------------------------------


class VisionOverlayController:
    """管理后台检测线程的生命周期与缓存。

    截图时自动排除 GUI 主窗口区域（涂黑），避免 GUI 元素被误识别。
    检测结果经 apply_task_boost 处理后写入缓存，任务匹配目标显示绿色。
    """

    def __init__(
        self,
        cache: DetectionCache,
        detect_interval_sec: float = 0.5,
    ) -> None:
        self._cache = cache
        self._detect_interval_sec = detect_interval_sec
        self._stop_event: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None

        from perception.screen_capturer import ScreenCapturer
        self._capturer = ScreenCapturer()

    def start(self) -> None:
        """启动后台检测 daemon 线程。若已在运行则跳过。"""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("VisionOverlayController: 后台线程已在运行，跳过重复启动")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._detection_loop, daemon=True, name="vision-overlay-detector"
        )
        self._thread.start()
        logger.info(
            "VisionOverlayController: 后台检测线程已启动，间隔=%.2fs",
            self._detect_interval_sec,
        )

    def stop(self) -> None:
        """停止后台检测线程并清空缓存。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._detect_interval_sec * 3)
            self._thread = None
        self._cache.clear()
        logger.info("VisionOverlayController: 后台检测线程已停止，缓存已清空")

    def _detection_loop(self) -> None:
        """后台检测循环：截图 → 排除GUI区域 → 检测 → 任务置信度提升 → 更新缓存。

        GUI 区域用纯黑填充（检测器不需要视觉效果，只需排除干扰）。
        """
        from automation.task_context import apply_task_boost  # 延迟导入避免循环依赖

        while not self._stop_event.is_set():
            try:
                screenshot = self._capturer.capture_full()
                # 检测时将 GUI 区域涂黑，排除 GUI 元素干扰（检测器不需要视觉效果）
                screenshot = _mask_gui_window(screenshot)
                boxes = detect_objects_for_display(screenshot)
                # 对匹配当前任务目标的框提升置信度（无活动任务时原样返回）
                boxes = apply_task_boost(boxes)
                self._cache.update(boxes)
                logger.debug("_detection_loop: 检测到 %d 个目标", len(boxes))
            except Exception as exc:  # noqa: BLE001
                logger.error("_detection_loop 异常（继续运行）: %s", exc)

            self._stop_event.wait(timeout=self._detect_interval_sec)
