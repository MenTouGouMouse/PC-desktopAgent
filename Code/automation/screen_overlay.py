"""automation/screen_overlay.py

Windows 屏幕透明叠加层：在桌面上直接绘制识别框，不依赖 Gradio 预览。

使用 tkinter 创建全屏置顶透明窗口，通过 Canvas 绘制矩形框和标签。
叠加层始终在最顶层（topmost），不拦截鼠标事件（click-through）。
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from automation.vision_box_drawer import BoundingBoxDict

logger = logging.getLogger(__name__)

# 颜色
_COLOR_HIGH = "#FF3333"   # 红色（高置信度）
_COLOR_LOW = "#FF8800"    # 橙色（低置信度）
_COLOR_TEXT_BG = "#000000"
_CONFIDENCE_THRESHOLD = 0.5


class ScreenOverlay:
    """全屏透明置顶叠加层，在 Windows 桌面上直接绘制识别框。

    在独立线程中运行 tkinter 事件循环，主线程通过 show/hide/update_boxes 控制。
    窗口设置为 click-through（鼠标事件穿透），不影响正常操作。
    """

    def __init__(self) -> None:
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._boxes: list[BoundingBoxDict] = []
        self._visible = False

    # ------------------------------------------------------------------
    # 公共接口（线程安全）
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动叠加层（在后台线程中运行 tkinter 事件循环）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_tk, daemon=True, name="screen-overlay")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def stop(self) -> None:
        """销毁叠加层窗口并停止后台线程。"""
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass
        self._root = None
        self._canvas = None

    def show(self) -> None:
        """显示叠加层窗口。"""
        if self._root is not None:
            self._root.after(0, self._root.deiconify)
            self._visible = True

    def hide(self) -> None:
        """隐藏叠加层窗口（不销毁）。"""
        if self._root is not None:
            self._root.after(0, self._root.withdraw)
            self._visible = False

    def update_boxes(self, boxes: list[BoundingBoxDict]) -> None:
        """更新识别框列表并刷新画面。

        Args:
            boxes: 识别框列表，坐标为逻辑坐标（屏幕坐标）。
        """
        with self._lock:
            self._boxes = list(boxes)
        if self._root is not None:
            self._root.after(0, self._redraw)

    def clear(self) -> None:
        """清空所有识别框。"""
        self.update_boxes([])

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _run_tk(self) -> None:
        """在后台线程中运行 tkinter 事件循环。"""
        try:
            root = tk.Tk()
            self._root = root

            # 全屏尺寸
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()

            # 窗口配置：无边框、置顶、透明背景
            root.overrideredirect(True)          # 无标题栏/边框
            root.attributes("-topmost", True)    # 始终置顶
            root.attributes("-transparentcolor", "black")  # 黑色透明
            root.attributes("-alpha", 1.0)
            root.geometry(f"{sw}x{sh}+0+0")
            root.configure(bg="black")

            # 设置 click-through（鼠标事件穿透到下层窗口）
            try:
                import ctypes  # noqa: PLC0415
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                # WS_EX_LAYERED | WS_EX_TRANSPARENT
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20)
            except Exception as e:
                logger.debug("click-through 设置失败（非致命）: %s", e)

            canvas = tk.Canvas(root, bg="black", highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)
            self._canvas = canvas

            self._ready.set()
            root.mainloop()
        except Exception as exc:
            logger.error("ScreenOverlay._run_tk 异常: %s", exc)
            self._ready.set()

    def _redraw(self) -> None:
        """在 tkinter 主线程中重绘所有识别框（必须从 after() 调用）。"""
        if self._canvas is None:
            return
        self._canvas.delete("all")

        with self._lock:
            boxes = list(self._boxes)

        for box in boxes:
            try:
                x1, y1, x2, y2 = box["bbox"]
                label = box["label"]
                confidence = box["confidence"]
                color = _COLOR_HIGH if confidence >= _CONFIDENCE_THRESHOLD else _COLOR_LOW

                # 矩形框（2px 宽）
                self._canvas.create_rectangle(
                    x1, y1, x2, y2,
                    outline=color, width=2, fill="",
                )

                # 标签背景 + 文字
                text = f"{label} {confidence:.2f}"
                # 文字位置：矩形框上方，若空间不足则放在框内
                ty = y1 - 18 if y1 > 20 else y1 + 2
                # 黑色背景矩形（估算文字宽度）
                text_w = len(text) * 7
                self._canvas.create_rectangle(
                    x1, ty, x1 + text_w, ty + 16,
                    fill=_COLOR_TEXT_BG, outline="",
                )
                self._canvas.create_text(
                    x1 + 2, ty + 1,
                    text=text, fill=color,
                    anchor="nw", font=("Consolas", 9),
                )
            except Exception as exc:
                logger.debug("_redraw: 绘制框失败: %s", exc)
