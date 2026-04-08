"""感知层：屏幕捕获模块，使用 mss 实现高性能截图，支持全屏与区域截图。"""
from __future__ import annotations

import logging
from typing import Any

import mss
import mss.tools
import numpy as np

logger = logging.getLogger(__name__)


class MonitorNotFoundError(Exception):
    """指定的显示器索引不存在。"""

    def __init__(self, monitor_index: int) -> None:
        self.monitor_index = monitor_index
        super().__init__(f"Monitor index {monitor_index!r} not found.")


class ScreenCapturer:
    """使用 mss 实现高性能屏幕截图，目标帧率 ≥15 fps。

    mss 的 monitors 列表中，索引 0 是所有显示器的合并区域，
    索引 1 开始才是各个独立显示器。本类的 monitor_index 从 0 开始，
    对应 mss monitors[1]（第一块物理显示器）。
    """

    def _get_mss_monitor(self, sct: mss.base.MSSBase, monitor_index: int) -> dict[str, Any]:
        """将用户传入的 monitor_index（0-based）映射到 mss monitors 列表。

        mss monitors[0] 是虚拟全屏合并区域，monitors[1] 起才是真实显示器。
        """
        # monitors[1:] 是真实显示器列表
        real_monitors = sct.monitors[1:]
        if monitor_index < 0 or monitor_index >= len(real_monitors):
            raise MonitorNotFoundError(monitor_index)
        return real_monitors[monitor_index]

    def capture_full(self, monitor_index: int = 0) -> np.ndarray:
        """全屏截图，返回 BGR numpy 数组。

        Args:
            monitor_index: 目标显示器索引（0-based，对应第一块物理显示器）。

        Returns:
            BGR uint8 numpy 数组，shape 为 (height, width, 3)。

        Raises:
            MonitorNotFoundError: 指定的显示器索引不存在。
        """
        with mss.mss() as sct:
            monitor = self._get_mss_monitor(sct, monitor_index)
            screenshot = sct.grab(monitor)
            # mss 返回 BGRA，转为 BGR
            frame = np.array(screenshot)[:, :, :3]
            logger.debug("capture_full: monitor=%d shape=%s", monitor_index, frame.shape)
            return frame

    def capture_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        monitor_index: int = 0,
    ) -> np.ndarray:
        """区域截图，返回 BGR numpy 数组。

        坐标相对于指定显示器的左上角（逻辑坐标）。

        Args:
            x: 区域左上角 x 坐标（相对于目标显示器）。
            y: 区域左上角 y 坐标（相对于目标显示器）。
            width: 区域宽度（像素）。
            height: 区域高度（像素）。
            monitor_index: 目标显示器索引（0-based）。

        Returns:
            BGR uint8 numpy 数组，shape 为 (height, width, 3)。

        Raises:
            MonitorNotFoundError: 指定的显示器索引不存在。
        """
        with mss.mss() as sct:
            monitor = self._get_mss_monitor(sct, monitor_index)
            region = {
                "left": monitor["left"] + x,
                "top": monitor["top"] + y,
                "width": width,
                "height": height,
            }
            screenshot = sct.grab(region)
            frame = np.array(screenshot)[:, :, :3]
            logger.debug(
                "capture_region: monitor=%d region=(%d,%d,%d,%d) shape=%s",
                monitor_index, x, y, width, height, frame.shape,
            )
            return frame

    def get_monitor_info(self) -> list[dict[str, Any]]:
        """返回所有真实显示器的信息列表（不含 mss 的虚拟合并显示器）。

        Returns:
            每个元素为包含 left, top, width, height 的字典，
            索引与 capture_full/capture_region 的 monitor_index 对应。
        """
        with mss.mss() as sct:
            # monitors[0] 是合并区域，跳过
            monitors = [
                {
                    "index": i,
                    "left": m["left"],
                    "top": m["top"],
                    "width": m["width"],
                    "height": m["height"],
                }
                for i, m in enumerate(sct.monitors[1:])
            ]
            logger.debug("get_monitor_info: found %d monitor(s)", len(monitors))
            return monitors
