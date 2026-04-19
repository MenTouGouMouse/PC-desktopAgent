"""DPI 适配模块：读取 Windows 系统 DPI 缩放比例，处理逻辑坐标与物理坐标的转换，支持多显示器环境。"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    """单个显示器的 DPI 与偏移信息。"""

    index: int
    left: int
    top: int
    scale_factor: float


def _enumerate_monitors() -> list[MonitorInfo]:
    """枚举所有显示器，读取各自的 DPI 缩放比例和全局偏移量。

    Returns:
        每个显示器的 MonitorInfo 列表；若枚举失败则返回包含单个默认显示器的列表。
    """
    monitors: list[MonitorInfo] = []

    if sys.platform != "win32":
        logger.warning(
            "Non-Windows platform detected; DPI enumeration unavailable, using scale_factor=1.0"
        )
        return [MonitorInfo(index=0, left=0, top=0, scale_factor=1.0)]

    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        shcore = ctypes.windll.shcore  # type: ignore[attr-defined]

        # RECT 结构体必须在 MonitorEnumProc 之前定义，供回调类型声明使用
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        # MONITORENUMPROC callback signature: (hMonitor, hdcMonitor, lprcMonitor, dwData) -> BOOL
        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong,        # hMonitor
            ctypes.c_ulong,        # hdcMonitor
            ctypes.POINTER(RECT),  # lprcMonitor (RECT*)
            ctypes.c_double,       # dwData
        )

        raw_monitors: list[tuple[int, int, int]] = []  # (hMonitor, left, top)

        def _callback(
            h_monitor: int,
            _hdc: int,
            lp_rect: ctypes.POINTER,  # type: ignore[type-arg]
            _data: float,
        ) -> bool:
            rect = lp_rect.contents
            raw_monitors.append((h_monitor, rect.left, rect.top))
            return True

        cb = MonitorEnumProc(_callback)
        user32.EnumDisplayMonitors(None, None, cb, 0)

        for idx, (h_monitor, left, top) in enumerate(raw_monitors):
            scale_factor = 1.0
            try:
                # Per-Monitor DPI Aware v2 模式下，mss 截图、SetCursorPos、SendInput
                # 均使用物理像素坐标，无需缩放转换，scale_factor 固定为 1.0。
                # GetDpiForMonitor 返回的是 UI 渲染缩放比（用于字体/控件大小），
                # 不代表坐标系差异，因此不用于坐标转换。
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to read DPI for monitor %d: %s; using scale_factor=1.0",
                    idx,
                    exc,
                )

            monitors.append(MonitorInfo(index=idx, left=left, top=top, scale_factor=scale_factor))

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to enumerate monitors via ctypes: %s; falling back to single monitor with scale_factor=1.0",
            exc,
        )
        return [MonitorInfo(index=0, left=0, top=0, scale_factor=1.0)]

    if not monitors:
        logger.warning("No monitors found during enumeration; using single monitor with scale_factor=1.0")
        return [MonitorInfo(index=0, left=0, top=0, scale_factor=1.0)]

    return monitors


class DPIAdapter:
    """DPI 适配器：在逻辑坐标与物理坐标之间进行转换，支持多显示器环境。

    逻辑坐标是操作系统报告的坐标（受 DPI 缩放影响），物理坐标是屏幕实际像素坐标。
    所有层间坐标传递使用逻辑坐标，仅在 Action_Engine 内部通过本类转换为物理坐标。
    """

    def __init__(self, scale_factor: float | None = None) -> None:
        """初始化 DPIAdapter。

        Args:
            scale_factor: 可选的覆盖缩放比例（主要用于测试）。若为 None，则从系统读取。
        """
        self._monitors: list[MonitorInfo] = _enumerate_monitors()

        if scale_factor is not None:
            # Override all monitors with the provided scale factor (useful for testing)
            self.scale_factor: float = scale_factor
            for m in self._monitors:
                m.scale_factor = scale_factor
        else:
            # Primary scale factor is taken from the first monitor
            self.scale_factor = self._monitors[0].scale_factor

        logger.debug(
            "DPIAdapter initialized: %d monitor(s), primary scale_factor=%.2f",
            len(self._monitors),
            self.scale_factor,
        )

    def _get_monitor(self, monitor_index: int) -> MonitorInfo:
        """获取指定索引的显示器信息，索引越界时回退到第一个显示器。

        Args:
            monitor_index: 显示器索引（从 0 开始）。

        Returns:
            对应的 MonitorInfo。
        """
        if 0 <= monitor_index < len(self._monitors):
            return self._monitors[monitor_index]
        logger.warning(
            "Monitor index %d out of range (available: 0-%d); falling back to monitor 0",
            monitor_index,
            len(self._monitors) - 1,
        )
        return self._monitors[0]

    def to_physical(self, lx: int, ly: int, monitor_index: int = 0) -> tuple[int, int]:
        """将逻辑坐标转换为物理坐标（含显示器全局偏移）。

        Args:
            lx: 逻辑 X 坐标（相对于目标显示器左上角）。
            ly: 逻辑 Y 坐标（相对于目标显示器左上角）。
            monitor_index: 目标显示器索引（从 0 开始）。

        Returns:
            (px, py) 全局物理坐标元组。
        """
        monitor = self._get_monitor(monitor_index)
        scale = monitor.scale_factor

        # Convert logical coords to physical, then add the monitor's global offset
        px = round(lx * scale) + monitor.left
        py = round(ly * scale) + monitor.top

        logger.debug(
            "to_physical: logical=(%d, %d) -> physical=(%d, %d) [monitor=%d, scale=%.2f, offset=(%d, %d)]",
            lx, ly, px, py, monitor_index, scale, monitor.left, monitor.top,
        )
        return px, py

    def to_logical(self, px: int, py: int, monitor_index: int = 0) -> tuple[int, int]:
        """将物理坐标转换为逻辑坐标（含显示器全局偏移）。

        Args:
            px: 全局物理 X 坐标。
            py: 全局物理 Y 坐标。
            monitor_index: 目标显示器索引（从 0 开始）。

        Returns:
            (lx, ly) 逻辑坐标元组（相对于目标显示器左上角）。
        """
        monitor = self._get_monitor(monitor_index)
        scale = monitor.scale_factor

        # Remove the monitor's global offset, then convert physical to logical
        lx = round((px - monitor.left) / scale)
        ly = round((py - monitor.top) / scale)

        logger.debug(
            "to_logical: physical=(%d, %d) -> logical=(%d, %d) [monitor=%d, scale=%.2f, offset=(%d, %d)]",
            px, py, lx, ly, monitor_index, scale, monitor.left, monitor.top,
        )
        return lx, ly

    @property
    def monitor_count(self) -> int:
        """返回已检测到的显示器数量。"""
        return len(self._monitors)

    def get_monitor_info(self, monitor_index: int = 0) -> MonitorInfo:
        """返回指定显示器的信息。

        Args:
            monitor_index: 显示器索引（从 0 开始）。

        Returns:
            对应的 MonitorInfo。
        """
        return self._get_monitor(monitor_index)
