"""交互层：Gradio Web UI 模块。

负责构建 Gradio Blocks 界面，提供：
- 自然语言指令输入框与执行按钮
- 录制开始/停止按钮
- 实时屏幕预览（≥15 fps），识别到元素时叠加红色矩形框
- 日志展示区，实时显示 Agent 操作日志与状态信息
- 通过 multiprocessing.Queue 与执行进程通信，进程崩溃时 UI 保持可用
- VisionOverlayAPI：识别框叠加功能的状态管理与图像编码
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from datetime import datetime, timezone
from multiprocessing import Queue
from typing import Generator

import cv2
import gradio as gr
import numpy as np
import pyautogui
from PIL import Image

from automation.object_detector import DetectionCache, VisionOverlayController
from automation.vision_box_drawer import draw_boxes_on_image
from config.config_loader import VisionBoxConfig, load_vision_box_config
from perception.dpi_adapter import DPIAdapter
from perception.element_locator import ElementResult
from perception.screen_capturer import ScreenCapturer
from ui.queue_manager import QueueManager, StatusMessage

logger = logging.getLogger(__name__)

# 预览帧率目标（≥15 fps → 间隔 ≤ 66 ms）
_PREVIEW_FPS: int = 15
_PREVIEW_INTERVAL_MS: int = 1000 // _PREVIEW_FPS  # ~66 ms

# 元素标注颜色：红色 BGR (0, 0, 255)
_ANNOTATION_COLOR_BGR: tuple[int, int, int] = (0, 0, 255)
_ANNOTATION_THICKNESS: int = 2

# 路径高亮：匹配 Windows/Unix 路径及常见安装包扩展名
import re as _re
_PATH_PATTERN = _re.compile(
    r'(?:[A-Za-z]:)?[/\\][^\s,，。；;]+|[^\s,，。；;]+\.(?:exe|zip|msi|dmg|tar|gz|pkg|deb|rpm)',
    _re.IGNORECASE,
)


def _highlight_paths_plain(text: str) -> str:
    """在纯文本日志中用【】标记路径，提升可读性。"""
    return _PATH_PATTERN.sub(lambda m: f"【{m.group()}】", text)


def annotate_elements(
    frame: np.ndarray,
    elements: list[ElementResult],
) -> np.ndarray:
    """在截图上用红色矩形框标注已识别的 GUI 元素。

    Args:
        frame: BGR numpy 数组，原始屏幕截图。
        elements: 已识别的元素列表，每个元素包含 bbox (x, y, w, h)。

    Returns:
        标注后的 BGR numpy 数组（原数组的副本）。
    """
    annotated = frame.copy()
    for elem in elements:
        x, y, w, h = elem.bbox
        pt1 = (x, y)
        pt2 = (x + w, y + h)
        cv2.rectangle(annotated, pt1, pt2, _ANNOTATION_COLOR_BGR, _ANNOTATION_THICKNESS)
        logger.debug(
            "annotate_elements: element=%s bbox=%s",
            elem.name,
            elem.bbox,
        )
    return annotated


def _draw_cursor(frame: np.ndarray, cx: int, cy: int, scale: float = 1.0) -> np.ndarray:
    """在帧上绘制鼠标光标叠加层（十字准星 + 圆点）。

    pyautogui.position() 返回逻辑坐标，mss 截图是物理像素。
    需要乘以 scale_factor 将逻辑坐标换算为图像像素坐标。

    Args:
        frame: BGR numpy 数组（物理像素）。
        cx: 鼠标逻辑 X 坐标。
        cy: 鼠标逻辑 Y 坐标。
        scale: DPI 缩放比例（物理像素 / 逻辑像素），默认 1.0。

    Returns:
        绘制了光标的图像副本。
    """
    h, w = frame.shape[:2]
    # 逻辑坐标 → 物理像素坐标
    px = int(round(cx * scale))
    py = int(round(cy * scale))
    px = max(0, min(px, w - 1))
    py = max(0, min(py, h - 1))

    out = frame.copy()
    arm = 16
    gap = 5
    color = (0, 255, 0)
    outline = (0, 0, 0)
    thickness = 2

    for col, th in ((outline, thickness + 2), (color, thickness)):
        if px - gap > 0:
            cv2.line(out, (max(0, px - arm), py), (px - gap, py), col, th)
        if px + gap < w:
            cv2.line(out, (px + gap, py), (min(w - 1, px + arm), py), col, th)
        if py - gap > 0:
            cv2.line(out, (px, max(0, py - arm)), (px, py - gap), col, th)
        if py + gap < h:
            cv2.line(out, (px, py + gap), (px, min(h - 1, py + arm)), col, th)

    cv2.circle(out, (px, py), 4, outline, -1)
    cv2.circle(out, (px, py), 3, color, -1)

    return out


def _bgr_to_pil(frame: np.ndarray) -> Image.Image:
    """将 BGR numpy 数组转换为 PIL RGB Image，供 Gradio 展示。

    Args:
        frame: BGR uint8 numpy 数组。

    Returns:
        PIL Image（RGB 模式）。
    """
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(tz=timezone.utc).isoformat()


class VisionOverlayAPI:
    """识别框叠加功能的状态管理与图像编码。

    封装 show_boxes_flag、DetectionCache、VisionOverlayController 的生命周期，
    提供 set_show_boxes / get_screen_with_boxes 两个公共方法供 Gradio UI 调用。
    可独立实例化，便于单元测试。
    """

    def __init__(
        self,
        capturer: ScreenCapturer,
        vision_config: VisionBoxConfig | None = None,
    ) -> None:
        """初始化 VisionOverlayAPI。

        Args:
            capturer: 屏幕截图实例，用于 get_screen_with_boxes 截图。
            vision_config: 识别框配置；为 None 时从 settings.yaml 读取。
        """
        self._capturer = capturer
        self._vision_config: VisionBoxConfig = (
            vision_config if vision_config is not None else load_vision_box_config()
        )
        self._detection_cache: DetectionCache = DetectionCache()
        self._overlay_controller: VisionOverlayController | None = None
        self.show_boxes_flag: bool = False

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def get_detection_cache(self) -> DetectionCache:
        """返回内部 DetectionCache 实例，供外部模块写入检测结果。"""
        return self._detection_cache

    def draw_boxes(self, frame: np.ndarray, boxes: list) -> np.ndarray:
        """用配置的参数在帧上绘制检测框，封装对 _vision_config 的访问。

        Args:
            frame: BGR numpy 数组。
            boxes: BoundingBoxDict 列表。

        Returns:
            绘制了检测框的图像副本。
        """
        return draw_boxes_on_image(
            frame,
            boxes,
            confidence_threshold=self._vision_config.confidence_threshold,
            show_confidence=self._vision_config.show_confidence,
        )

    def set_show_boxes(self, show: bool) -> None:
        """更新 show_boxes_flag，并启动/停止后台检测线程。

        - vision_config.enabled=False 时静默返回，不修改 flag，不启动线程
        - show=True 且 enabled=True：更新 flag，启动 VisionOverlayController
        - show=False：更新 flag，停止 VisionOverlayController，清空缓存

        Args:
            show: 是否显示识别框。
        """
        if not self._vision_config.enabled:
            logger.debug("set_show_boxes: vision_box.enabled=False，忽略调用")
            return

        self.show_boxes_flag = show

        if show:
            if self._overlay_controller is None:
                self._overlay_controller = VisionOverlayController(
                    cache=self._detection_cache,
                )
            self._overlay_controller.start()
            logger.info("set_show_boxes: 识别框已启用，后台检测线程已启动")
        else:
            if self._overlay_controller is not None:
                self._overlay_controller.stop()
                self._overlay_controller = None
            self._detection_cache.clear()
            logger.info("set_show_boxes: 识别框已禁用，缓存已清空")

    def get_screen_with_boxes(self) -> str:
        """截图并根据 show_boxes_flag 决定是否叠加检测框，返回 base64 JPEG 字符串。

        - show_boxes_flag=True:  capture → get cached boxes → draw → encode → return b64
        - show_boxes_flag=False: capture → encode → return b64
        - 任何异常: 记录 ERROR，返回 ""

        Returns:
            base64 编码的 JPEG 字符串；异常时返回 ""。
        """
        try:
            frame = self._capturer.capture_full()

            if self.show_boxes_flag:
                boxes = self._detection_cache.get()
                frame = draw_boxes_on_image(
                    frame,
                    boxes,
                    confidence_threshold=self._vision_config.confidence_threshold,
                    show_confidence=self._vision_config.show_confidence,
                )

            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
            success, buf = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                logger.error("get_screen_with_boxes: cv2.imencode 失败")
                return ""

            return base64.b64encode(buf.tobytes()).decode("utf-8")

        except Exception as exc:  # noqa: BLE001
            logger.error("get_screen_with_boxes 异常: %s", exc)
            return ""


def build_app(cmd_queue: Queue, status_queue: Queue) -> gr.Blocks:
    """构建 Gradio UI，返回 Blocks 实例。

    UI 进程通过 cmd_queue 向执行进程发送指令，
    通过 status_queue 接收执行进程的状态消息。
    执行进程崩溃（poll_status 超时）时，日志区显示错误，UI 保持可用。

    Args:
        cmd_queue: UI → 执行进程的指令队列。
        status_queue: 执行进程 → UI 的状态队列。

    Returns:
        配置好的 gr.Blocks 实例（未启动）。
    """
    # 用传入的 Queue 构造 QueueManager，避免重新创建新队列
    queue_manager = QueueManager(cmd_queue=cmd_queue, status_queue=status_queue)

    # 从 settings.yaml 读取超时配置
    _queue_timeout: float = 300.0
    try:
        import yaml
        _settings_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
        with open(_settings_path, encoding="utf-8") as _f:
            _settings = yaml.safe_load(_f) or {}
        _queue_timeout = float(_settings.get("ui", {}).get("queue_timeout_sec", 300.0))
    except Exception:  # noqa: BLE001
        pass

    capturer = ScreenCapturer()
    dpi = DPIAdapter()

    # Vision Overlay API（识别框叠加功能）
    vision_api = VisionOverlayAPI(capturer=capturer)

    # 共享状态：当前已识别的元素列表（由执行进程通过 status_queue 更新）
    _state_lock = threading.Lock()
    _current_elements: list[ElementResult] = []
    _log_lines: list[str] = []

    def _append_log(message: str) -> None:
        """线程安全地追加一条日志。"""
        ts = _now_iso()
        line = f"[{ts}] {message}"
        with _state_lock:
            _log_lines.append(line)
            # 保留最近 500 条，防止内存无限增长
            if len(_log_lines) > 500:
                _log_lines.pop(0)
        logger.info("UI log: %s", message)

    def _get_log_text() -> str:
        with _state_lock:
            return "\n".join(_log_lines[-100:])

    # ------------------------------------------------------------------
    # 执行指令
    # ------------------------------------------------------------------

    def on_execute(instruction: str) -> tuple[str, str]:
        """处理"执行"按钮点击事件。

        Args:
            instruction: 用户输入的自然语言指令。

        Returns:
            (状态文本, 日志文本) 元组。
        """
        if not instruction.strip():
            _append_log("⚠️ 指令为空，请输入自然语言指令后再执行。")
            return "空指令", _get_log_text()

        _append_log(f"▶ 执行指令：{_highlight_paths_plain(instruction)}")
        try:
            queue_manager.send_command("execute", {"instruction": instruction})
            logger.info("on_execute: command sent, instruction=%r", instruction)
        except Exception as exc:  # noqa: BLE001
            err_msg = f"❌ 发送指令失败：{exc}"
            _append_log(err_msg)
            logger.error("on_execute: failed to send command: %s", exc)
            return "发送失败", _get_log_text()

        # 在后台线程中等待状态，避免阻塞 UI
        def _wait_status() -> None:
            try:
                status_msg: StatusMessage = queue_manager.poll_status(timeout=_queue_timeout)
                if status_msg.status == "timeout":
                    _append_log(
                        f"⏰ 执行进程超时（{int(_queue_timeout)} 秒内未返回状态），可能已崩溃。UI 保持可用。"
                    )
                    logger.warning("on_execute: poll_status timed out")
                elif status_msg.status == "error":
                    _append_log(f"❌ 执行失败：{_highlight_paths_plain(status_msg.message)}")
                elif status_msg.status == "success":
                    _append_log(f"✅ 执行成功：{_highlight_paths_plain(status_msg.message)}")
                else:
                    _append_log(f"ℹ️ 状态更新：[{status_msg.status}] {_highlight_paths_plain(status_msg.message)}")
            except Exception as exc:  # noqa: BLE001
                _append_log(f"❌ 等待执行状态时发生异常：{exc}")
                logger.error("_wait_status: exception: %s", exc)

        t = threading.Thread(target=_wait_status, daemon=True)
        t.start()

        return "执行中…", _get_log_text()

    # ------------------------------------------------------------------
    # 文件整理
    # ------------------------------------------------------------------

    def on_file_organize() -> tuple[str, str]:
        """处理"文件整理"按钮点击事件。

        在 UI 进程内的后台线程直接执行文件整理，
        这样可以把 detection_cache 传入，
        让文件定位结果实时显示在预览识别框上。

        Returns:
            (状态文本, 日志文本) 元组。
        """
        from automation.file_organizer import run_file_organizer  # noqa: PLC0415

        source_path = os.path.expanduser("~/Desktop")
        _append_log(f"📁 文件整理：源目录 {source_path}")

        _stop = threading.Event()

        def _cb(step: str, percent: int) -> None:
            _append_log(f"[文件整理] {step} ({percent}%)")

        def _run() -> None:
            try:
                run_file_organizer(
                    source_path,
                    source_path,  # 目标目录与源目录相同（按扩展名分类到子目录）
                    _cb,
                    _stop,
                    detection_cache=vision_api.get_detection_cache(),
                )
                _append_log("✅ 文件整理完成")
            except Exception as exc:  # noqa: BLE001
                _append_log(f"❌ 文件整理出错：{exc}")
                logger.error("on_file_organize: error: %s", exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return "整理中…", _get_log_text()

    # ------------------------------------------------------------------
    # 录制控制
    # ------------------------------------------------------------------

    def on_start_record() -> tuple[str, str]:
        """处理"开始录制"按钮点击事件。"""
        _append_log("🔴 开始录制…")
        try:
            queue_manager.send_command("record", {"action": "start"})
        except Exception as exc:  # noqa: BLE001
            err_msg = f"❌ 发送录制开始指令失败：{exc}"
            _append_log(err_msg)
            logger.error("on_start_record: %s", exc)
            return "录制启动失败", _get_log_text()
        return "录制中…", _get_log_text()

    def on_stop_record() -> tuple[str, str]:
        """处理"停止录制"按钮点击事件。"""
        _append_log("⏹ 停止录制…")
        try:
            queue_manager.send_command("record", {"action": "stop"})
        except Exception as exc:  # noqa: BLE001
            err_msg = f"❌ 发送录制停止指令失败：{exc}"
            _append_log(err_msg)
            logger.error("on_stop_record: %s", exc)
            return "录制停止失败", _get_log_text()

        def _wait_record_result() -> None:
            try:
                status_msg = queue_manager.poll_status(timeout=30.0)
                if status_msg.status == "timeout":
                    _append_log("⏰ 录制停止超时，执行进程可能已崩溃。UI 保持可用。")
                elif status_msg.status == "success":
                    _append_log(f"✅ 录制已保存：{_highlight_paths_plain(status_msg.message)}")
                elif status_msg.status == "error":
                    _append_log(f"❌ 录制保存失败：{_highlight_paths_plain(status_msg.message)}")
                else:
                    _append_log(f"ℹ️ 录制状态：[{status_msg.status}] {_highlight_paths_plain(status_msg.message)}")
            except Exception as exc:  # noqa: BLE001
                _append_log(f"❌ 等待录制结果时发生异常：{exc}")
                logger.error("_wait_record_result: %s", exc)

        t = threading.Thread(target=_wait_record_result, daemon=True)
        t.start()
        return "录制停止中…", _get_log_text()

    # ------------------------------------------------------------------
    # 实时屏幕预览（≥15 fps）
    # ------------------------------------------------------------------

    def preview_stream() -> Generator[Image.Image, None, None]:
        """生成器：持续捕获屏幕并叠加元素标注、识别框和实时鼠标光标，供 Gradio Image streaming 使用。

        - 鼠标光标：截图后立刻读取逻辑坐标，乘以 DPI scale_factor 换算为物理像素后绘制
        - 检测框：只要 show_boxes_flag=True 且缓存有数据就绘制，坐标已是物理像素（_run_detection 输出）

        Yields:
            PIL Image（RGB），帧率 ≥15 fps。
        """
        import time

        scale = dpi.scale_factor  # 物理像素 / 逻辑像素，例如 125% DPI → 1.25
        interval = 1.0 / _PREVIEW_FPS
        while True:
            start = time.monotonic()
            try:
                # 截图（物理像素）与鼠标位置（逻辑坐标）紧邻采样
                frame = capturer.capture_full(monitor_index=0)
                mouse_pos = pyautogui.position()

                # ElementResult 标注
                with _state_lock:
                    elements_snapshot = list(_current_elements)
                if elements_snapshot:
                    frame = annotate_elements(frame, elements_snapshot)

                # 检测框：show_boxes_flag=True 时从缓存读取并绘制
                if vision_api.show_boxes_flag:
                    boxes = vision_api.get_detection_cache().get()
                    if boxes:
                        frame = vision_api.draw_boxes(frame, boxes)
                        logger.debug("preview_stream: drew %d box(es)", len(boxes))

                # 鼠标光标：逻辑坐标 × scale → 物理像素坐标
                frame = _draw_cursor(frame, mouse_pos.x, mouse_pos.y, scale=scale)

                yield _bgr_to_pil(frame)
            except Exception as exc:  # noqa: BLE001
                logger.error("preview_stream: error: %s", exc)
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                yield _bgr_to_pil(placeholder)

            elapsed = time.monotonic() - start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ------------------------------------------------------------------
    # 日志轮询（每秒刷新）
    # ------------------------------------------------------------------

    def poll_log() -> str:
        """返回最新日志文本，供 Gradio 定时刷新。"""
        return _get_log_text()

    # ------------------------------------------------------------------
    # 识别框切换
    # ------------------------------------------------------------------

    def on_toggle_boxes() -> str:
        """处理"🔍 显示识别框"切换按钮点击事件。

        直接读取 vision_api.show_boxes_flag 判断当前状态，
        避免依赖按钮 label 字符串（Gradio 中不可靠）。

        Returns:
            新的按钮标签文字。
        """
        new_show = not vision_api.show_boxes_flag
        vision_api.set_show_boxes(new_show)
        logger.info("on_toggle_boxes: show_boxes → %s", new_show)
        if new_show:
            return "✅ 识别框已启用"
        return "🔍 显示识别框"

    # ------------------------------------------------------------------
    # 构建 Gradio Blocks UI
    # ------------------------------------------------------------------

    with gr.Blocks(title="CV 桌面自动化智能体") as app:
        gr.Markdown("# CV 桌面自动化智能体")
        gr.Markdown("通过自然语言指令控制桌面操作，支持实时屏幕预览与录制回放。")

        with gr.Row():
            # 左列：控制面板
            with gr.Column(scale=1):
                gr.Markdown("### 指令执行")
                instruction_input = gr.Textbox(
                    label="自然语言指令",
                    placeholder='例如：打开微信，向文件传输助手发送"你好"',
                    lines=3,
                )
                execute_btn = gr.Button("▶ 执行", variant="primary")
                execute_status = gr.Textbox(label="执行状态", interactive=False, lines=1)

                gr.Markdown("### 文件整理")
                file_organize_btn = gr.Button("📁 文件整理", variant="secondary")
                file_organize_status = gr.Textbox(label="整理状态", interactive=False, lines=1)

                gr.Markdown("### 录制控制")
                with gr.Row():
                    start_record_btn = gr.Button("🔴 开始录制", variant="secondary")
                    stop_record_btn = gr.Button("⏹ 停止录制", variant="secondary")
                record_status = gr.Textbox(label="录制状态", interactive=False, lines=1)

                gr.Markdown("### 操作日志")
                log_output = gr.Textbox(
                    label="日志",
                    interactive=False,
                    lines=15,
                    max_lines=20,
                    autoscroll=True,
                )

            # 右列：实时屏幕预览
            with gr.Column(scale=2):
                gr.Markdown("### 实时屏幕预览")
                with gr.Row():
                    toggle_boxes_btn = gr.Button("🔍 显示识别框", variant="secondary")
                preview_image = gr.Image(
                    label="屏幕预览（≥15 fps）",
                    streaming=True,
                    height=600,
                )

        # ------------------------------------------------------------------
        # 事件绑定
        # ------------------------------------------------------------------

        execute_btn.click(
            fn=on_execute,
            inputs=[instruction_input],
            outputs=[execute_status, log_output],
        )

        file_organize_btn.click(
            fn=on_file_organize,
            inputs=[],
            outputs=[file_organize_status, log_output],
        )

        start_record_btn.click(
            fn=on_start_record,
            inputs=[],
            outputs=[record_status, log_output],
        )

        stop_record_btn.click(
            fn=on_stop_record,
            inputs=[],
            outputs=[record_status, log_output],
        )

        # 实时预览：使用 Gradio streaming
        preview_image.stream(
            fn=preview_stream,
            inputs=[],
            outputs=[preview_image],
            time_limit=None,
        )

        # 日志定时刷新（每秒）：Gradio ≥4.x 使用 gr.Timer
        log_timer = gr.Timer(value=1)
        log_timer.tick(fn=poll_log, inputs=[], outputs=[log_output])

        # 识别框切换按钮
        toggle_boxes_btn.click(
            fn=on_toggle_boxes,
            inputs=[],
            outputs=[toggle_boxes_btn],
        )

    logger.info("build_app: Gradio Blocks built successfully")
    return app
