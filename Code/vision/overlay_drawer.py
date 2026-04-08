"""
vision/overlay_drawer.py — 后台截图线程，负责 mss 截图 → OpenCV 检测框绘制
→ JPEG 压缩 → base64 编码，供 PyWebView 前端实时预览。

检测框数据来源：
- 旧接口：set_boxes(list[DetectionBox])，直接传入框列表（向后兼容）
- 新接口：set_detection_cache(DetectionCache, show)，从线程安全缓存读取
  BoundingBoxDict 格式的框，由 VisionOverlayController 后台写入。
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import cv2
import mss
import numpy as np

if TYPE_CHECKING:
    from automation.object_detector import DetectionCache

logger = logging.getLogger(__name__)


@dataclass
class DetectionBox:
    """描述检测框位置与样式的数据类（旧接口，向后兼容）。"""

    x: int
    y: int
    w: int
    h: int
    label: str = ""
    color_bgr: tuple[int, int, int] = field(default_factory=lambda: (0, 255, 128))


def _is_valid_box(box: DetectionBox) -> bool:
    """Return True if the box has positive dimensions and valid BGR color components."""
    if box.w <= 0 or box.h <= 0:
        return False
    if not (len(box.color_bgr) == 3 and all(0 <= c <= 255 for c in box.color_bgr)):
        return False
    return True


# 检测框绘制颜色（BGR）— 与 vision_box_drawer.py 保持一致的三档方案
_COLOR_HIGH: tuple[int, int, int] = (0, 255, 0)      # 绿色：confidence >= 0.8
_COLOR_MID: tuple[int, int, int] = (0, 255, 255)     # 黄色：0.6 <= confidence < 0.8
_COLOR_LOW: tuple[int, int, int] = (0, 0, 255)       # 红色：confidence < 0.6
_THRESHOLD_HIGH: float = 0.8
_THRESHOLD_MID: float = 0.6
_BOX_THICKNESS: int = 2
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE: float = 0.5
_FONT_THICKNESS: int = 1
_LABEL_PADDING: int = 4


def _confidence_color(confidence: float) -> tuple[int, int, int]:
    """根据置信度返回三档颜色（与 vision_box_drawer._confidence_color 保持一致）。"""
    if confidence >= _THRESHOLD_HIGH:
        return _COLOR_HIGH
    if confidence >= _THRESHOLD_MID:
        return _COLOR_MID
    return _COLOR_LOW


def _draw_cache_boxes(frame: np.ndarray, boxes: list) -> np.ndarray:
    """将 BoundingBoxDict 格式的检测框绘制到帧上，返回副本。

    坐标格式：bbox = [x1, y1, x2, y2]（图像绝对坐标）。
    颜色按置信度三档区分：绿色（≥0.8）/ 黄色（0.6~0.8）/ 红色（<0.6）。

    Args:
        frame: BGR uint8 numpy 数组。
        boxes: list[BoundingBoxDict]，来自 DetectionCache.get()。

    Returns:
        绘制了检测框的图像副本。
    """
    if not boxes:
        return frame

    output = frame.copy()
    img_h, img_w = output.shape[:2]

    for box in boxes:
        try:
            x1, y1, x2, y2 = (int(v) for v in box["bbox"])
            label: str = str(box.get("label", ""))
            confidence: float = float(box.get("confidence", 1.0))

            # 裁剪越界坐标，防止 cv2 崩溃
            x1 = max(0, min(x1, img_w - 1))
            y1 = max(0, min(y1, img_h - 1))
            x2 = max(0, min(x2, img_w - 1))
            y2 = max(0, min(y2, img_h - 1))

            if x2 <= x1 or y2 <= y1:
                logger.debug("_draw_cache_boxes: 跳过无效框 [%d,%d,%d,%d]", x1, y1, x2, y2)
                continue

            color = _confidence_color(confidence)

            # 绘制矩形框
            cv2.rectangle(output, (x1, y1), (x2, y2), color, _BOX_THICKNESS)

            # 构建标签文字
            text = f"{label} {confidence:.2f}" if label else f"{confidence:.2f}"
            (text_w, text_h), baseline = cv2.getTextSize(
                text, _FONT, _FONT_SCALE, _FONT_THICKNESS
            )

            # 标签背景：框上方，空间不足时放框内顶部
            lx1 = x1
            ly2 = y1
            ly1 = ly2 - text_h - baseline - _LABEL_PADDING * 2
            if ly1 < 0:
                ly1 = y1
                ly2 = y1 + text_h + baseline + _LABEL_PADDING * 2
            lx2 = lx1 + text_w + _LABEL_PADDING * 2

            # 半透明背景
            overlay = output.copy()
            cv2.rectangle(overlay, (lx1, ly1), (lx2, ly2), color, cv2.FILLED)
            cv2.addWeighted(overlay, 0.6, output, 0.4, 0, output)

            # 白色文字
            cv2.putText(
                output, text,
                (lx1 + _LABEL_PADDING, ly2 - baseline - _LABEL_PADDING),
                _FONT, _FONT_SCALE, (255, 255, 255), _FONT_THICKNESS, cv2.LINE_AA,
            )

        except Exception as exc:  # noqa: BLE001
            logger.debug("_draw_cache_boxes: 绘制单个框失败: %s", exc)

    return output


class OverlayDrawer:
    """在后台 daemon 线程中持续截图，绘制检测框，编码为 base64 JPEG 供前端显示。

    支持两种检测框数据来源：
    1. set_boxes()：直接传入 DetectionBox 列表（旧接口，向后兼容）
    2. set_detection_cache()：绑定 DetectionCache，每帧从缓存读取最新框数据
       （新接口，由 VisionOverlayController 后台线程异步写入）
    """

    def __init__(self, fps: int = 8) -> None:
        self._fps: int = fps
        # 旧接口：直接传入的框列表
        self._boxes: list[DetectionBox] = []
        self._boxes_lock: threading.Lock = threading.Lock()
        # 新接口：DetectionCache 引用 + 是否启用
        self._detection_cache: DetectionCache | None = None
        self._cache_lock: threading.Lock = threading.Lock()
        self._show_boxes: bool = False

        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._frame_callback: Callable[[str], None] | None = None

        # 缓存上一帧 GUI 区域的内容，用于填充当前帧的 GUI 位置（避免黑块）
        self._gui_region_cache: np.ndarray | None = None

    def start(self, frame_callback: Callable[[str], None]) -> None:
        """Launch the capture loop in a daemon thread."""
        self._frame_callback = frame_callback
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("OverlayDrawer started at %d fps", self._fps)

    def stop(self) -> None:
        """Signal the capture loop to stop."""
        self._running = False
        logger.info("OverlayDrawer stop requested")

    def set_boxes(self, boxes: list[DetectionBox]) -> None:
        """Thread-safely update the detection box list (旧接口，向后兼容)."""
        valid = [b for b in boxes if _is_valid_box(b)]
        with self._boxes_lock:
            self._boxes = valid

    def set_detection_cache(
        self, cache: DetectionCache | None, show: bool
    ) -> None:
        """绑定 DetectionCache 并控制是否在帧上绘制检测框（新接口）。

        Args:
            cache: DetectionCache 实例，None 表示解绑。
            show: True 表示在每帧上绘制缓存中的框，False 表示不绘制。
        """
        with self._cache_lock:
            self._detection_cache = cache
            self._show_boxes = show
        logger.info(
            "OverlayDrawer.set_detection_cache: cache=%s show=%s",
            "bound" if cache is not None else "None",
            show,
        )

    def _fill_gui_region(self, frame: np.ndarray) -> np.ndarray:
        """用缓存的桌面内容填充 GUI 窗口区域，避免预览中出现黑块。

        原理：
        - 每帧截图后，先把 GUI 区域的像素保存到 _gui_region_cache
        - 下一帧截图时，用上一帧保存的该区域内容覆盖当前帧的 GUI 区域
        - 效果：预览中 GUI 位置显示的是 GUI 后面的桌面内容（上一帧），
          视觉上就像 GUI 窗口不存在，而不是黑块

        Args:
            frame: 当前帧 BGR numpy 数组（全屏截图）。

        Returns:
            填充后的帧副本；获取窗口位置失败时原样返回。
        """
        from automation.object_detector import _get_gui_window_rect  # noqa: PLC0415

        rect = _get_gui_window_rect()
        if rect is None:
            # 无法获取 GUI 位置，清空缓存并原样返回
            self._gui_region_cache = None
            return frame

        left, top, right, bottom = rect
        h, w = frame.shape[:2]

        x1 = max(0, left)
        y1 = max(0, top)
        x2 = min(w, right)
        y2 = min(h, bottom)

        if x2 <= x1 or y2 <= y1:
            return frame

        result = frame.copy()

        if self._gui_region_cache is not None:
            # 用上一帧的 GUI 区域内容填充当前帧，消除黑块
            cached_h, cached_w = self._gui_region_cache.shape[:2]
            region_h = y2 - y1
            region_w = x2 - x1
            if cached_h == region_h and cached_w == region_w:
                result[y1:y2, x1:x2] = self._gui_region_cache
            else:
                # 尺寸变化（窗口被拖动/缩放），缓存失效，本帧先涂黑
                result[y1:y2, x1:x2] = 0
        else:
            # 第一帧还没有缓存，先涂黑（只有第一帧会出现黑块）
            result[y1:y2, x1:x2] = 0

        # 保存当前帧原始 GUI 区域（未被覆盖前的内容）供下一帧使用
        # 注意：要从原始 frame 取，不是从 result 取
        self._gui_region_cache = frame[y1:y2, x1:x2].copy()

        return result

    def _capture_loop(self) -> None:
        """Main capture loop: grab screen → fill GUI region → draw boxes → encode → callback."""
        with mss.mss() as sct:
            while self._running:
                t_start = time.monotonic()
                try:
                    # 截取全屏（monitor[0] = 所有显示器合并区域）
                    monitor = sct.monitors[0]
                    raw = sct.grab(monitor)
                    # mss 返回 BGRA，转为 BGR
                    frame_bgr = cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2BGR)

                    # 用缓存的桌面内容填充 GUI 区域，避免黑块
                    frame_bgr = self._fill_gui_region(frame_bgr)

                    # --- 旧接口：直接传入的 DetectionBox 列表 ---
                    with self._boxes_lock:
                        boxes_snapshot = list(self._boxes)

                    for box in boxes_snapshot:
                        pt1 = (box.x, box.y)
                        pt2 = (box.x + box.w, box.y + box.h)
                        cv2.rectangle(frame_bgr, pt1, pt2, box.color_bgr, thickness=2)
                        if box.label:
                            cv2.putText(
                                frame_bgr,
                                box.label,
                                (box.x, box.y - 5),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                box.color_bgr,
                                1,
                            )

                    # --- 新接口：从 DetectionCache 读取框并绘制 ---
                    with self._cache_lock:
                        cache = self._detection_cache
                        show = self._show_boxes

                    if show and cache is not None:
                        cached_boxes = cache.get()
                        if cached_boxes:
                            frame_bgr = _draw_cache_boxes(frame_bgr, cached_boxes)
                            logger.debug(
                                "OverlayDrawer: 绘制了 %d 个检测框", len(cached_boxes)
                            )

                    # JPEG 编码 → base64
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
                    success, jpeg_buf = cv2.imencode(".jpg", frame_bgr, encode_params)
                    if success:
                        b64_str = base64.b64encode(jpeg_buf.tobytes()).decode("ascii")
                        if self._frame_callback is not None:
                            self._frame_callback(b64_str)
                    else:
                        logger.warning("OverlayDrawer: cv2.imencode 失败")

                except Exception as exc:  # noqa: BLE001
                    logger.error("OverlayDrawer capture loop error: %s", exc)

                elapsed = time.monotonic() - t_start
                sleep_time = (1.0 / self._fps) - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
