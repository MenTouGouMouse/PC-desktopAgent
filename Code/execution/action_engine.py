"""执行层：动作执行引擎。

封装鼠标/键盘模拟操作，使用三次贝塞尔曲线生成拟人化鼠标轨迹。
坐标越界时记录 ERROR 日志并返回 False，不执行操作。
中文文本输入通过 pyperclip 剪贴板粘贴方式实现，避免输入法兼容性问题。
系统级操作（UAC 弹窗）使用 pywinauto Application(backend="uia") 模式。

坐标约定：
- main_gui.py 启动时调用 SetProcessDpiAwareness(2)（Per-Monitor DPI Aware v2）
- 设置后 mss 截图、SetCursorPos、GetCursorPos 均使用物理像素坐标，坐标系完全一致
- 无需任何 DPI 转换，直接使用截图坐标即可
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import math
import random
import subprocess
import sys
import time
from typing import Literal

import pyautogui
import pyperclip

from execution.retry_handler import with_retry
from perception.dpi_adapter import DPIAdapter

logger = logging.getLogger(__name__)

_ULONG_PTR = getattr(wintypes, "ULONG_PTR", wintypes.WPARAM)

# 禁用 pyautogui 的 fail-safe 和额外延迟
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0  # 去掉每次调用的 0.1s 强制等待，由我们自己控制节奏

# 中文别名 → Windows 可执行命令映射
_ALIAS_MAP: dict[str, str] = {
    "文件资源管理器": "explorer",
    "资源管理器": "explorer",
    "文件管理器": "explorer",
    "记事本": "notepad",
    "计算器": "calc",
    "画图": "mspaint",
    "命令提示符": "cmd",
    "任务管理器": "taskmgr",
    "控制面板": "control",
}


# ---------------------------------------------------------------------------
# 贝塞尔曲线拟人化鼠标移动
# ---------------------------------------------------------------------------

def _bezier(p0: tuple[float, float], p1: tuple[float, float],
            p2: tuple[float, float], p3: tuple[float, float],
            t: float) -> tuple[float, float]:
    """计算三次贝塞尔曲线在参数 t 处的坐标。

    Args:
        p0: 起点。
        p1: 控制点 1。
        p2: 控制点 2。
        p3: 终点。
        t: 参数，范围 [0, 1]。

    Returns:
        曲线上 t 处的 (x, y) 坐标。
    """
    u = 1.0 - t
    x = u**3 * p0[0] + 3*u**2*t * p1[0] + 3*u*t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3*u**2*t * p1[1] + 3*u*t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _generate_path(
    start: tuple[float, float],
    end: tuple[float, float],
) -> list[tuple[int, int]]:
    """生成从 start 到 end 的拟人化鼠标轨迹点列表。

    使用三次贝塞尔曲线 + 随机控制点，轨迹具有自然弯曲。
    控制点偏移量严格限制在屏幕范围内，避免 SetCursorPos 钳制导致轨迹变形。

    Args:
        start: 起点 (x, y)。
        end: 终点 (x, y)。

    Returns:
        轨迹点列表，每个元素为整数坐标 (x, y)。
    """
    left, top, sw, sh = _get_virtual_screen_rect()
    right = left + sw - 1
    bottom = top + sh - 1
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)

    n_points = int(max(20, min(50, dist / 15)))

    # 控制点偏移：限制在 ±80px 以内，避免飞出屏幕
    max_offset = min(80.0, dist * 0.15)
    if dist > 0:
        nx, ny = -dy / dist, dx / dist
    else:
        nx, ny = 0.0, 1.0

    offset1 = random.uniform(-max_offset, max_offset)
    offset2 = random.uniform(-max_offset, max_offset)

    cp1 = (
        start[0] + dx * random.uniform(0.25, 0.4) + nx * offset1,
        start[1] + dy * random.uniform(0.25, 0.4) + ny * offset1,
    )
    cp2 = (
        start[0] + dx * random.uniform(0.6, 0.75) + nx * offset2,
        start[1] + dy * random.uniform(0.6, 0.75) + ny * offset2,
    )

    points: list[tuple[int, int]] = []
    for i in range(n_points + 1):
        t = i / n_points
        bx, by = _bezier(start, cp1, cp2, end, t)
        # 微抖动：接近终点时衰减
        jitter_scale = max(0.0, 1.0 - t / 0.8) if t > 0.8 else 1.0
        jitter_x = random.uniform(-1.0, 1.0) * jitter_scale
        jitter_y = random.uniform(-1.0, 1.0) * jitter_scale
        # 钳制到屏幕范围，防止 SetCursorPos 静默截断
        px = int(max(left, min(bx + jitter_x, right)))
        py = int(max(top, min(by + jitter_y, bottom)))
        points.append((px, py))

    # 最后一个点强制精确到终点
    points[-1] = (int(end[0]), int(end[1]))
    return points


def _ease_out(t: float) -> float:
    """ease-out 缓动函数：先快后慢，模拟人类减速停止。"""
    return 1.0 - (1.0 - t) ** 3


def human_like_move(target_x: int, target_y: int) -> None:
    """从当前鼠标位置沿贝塞尔曲线拟人化移动到目标坐标。

    target_x/target_y 是 mss 物理像素坐标。
    内部自动读取 DPI scale 和 awareness，转换为 pyautogui 期望的坐标系。
    """
    cur_phys_x, cur_phys_y = _get_cursor_pos()

    start = (float(cur_phys_x), float(cur_phys_y))
    end = (float(target_x), float(target_y))
    dist = math.hypot(end[0] - start[0], end[1] - start[1])

    if dist < 5:
        _send_move(target_x, target_y)
        return

    total_time = max(0.15, min(0.5, dist / 2000))
    path = _generate_path(start, end)  # 物理坐标系路径
    n = len(path)
    hesitate_idx = int(n * 0.85)
    hesitated = False

    for i, (px, py) in enumerate(path):
        _send_move(px, py)

        if not hesitated and i >= hesitate_idx:
            time.sleep(random.uniform(0.02, 0.06))
            hesitated = True
            continue

        t_curr = i / n
        t_next = (i + 1) / n
        dt = (_ease_out(t_next) - _ease_out(t_curr)) * total_time
        dt *= random.uniform(0.8, 1.2)
        time.sleep(max(0.002, min(0.012, dt)))


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

class CoordinateOutOfBoundsError(Exception):
    """目标坐标超出屏幕边界时抛出。"""


def _get_virtual_screen_rect() -> tuple[int, int, int, int]:
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            left = int(user32.GetSystemMetrics(76))
            top = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(78))
            height = int(user32.GetSystemMetrics(79))
            if width > 0 and height > 0:
                return left, top, width, height
        except Exception:
            pass

    import mss as _mss
    with _mss.mss() as sct:
        m = sct.monitors[0]
        return int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])


def _get_dpi_scale() -> float:
    """从 OS 读取主显示器的 DPI 缩放比例。

    优先使用 GetScaleFactorForMonitor（最准确，不受 DPI awareness 影响）。
    回退到 GetDpiForSystem / GetDeviceCaps。
    150% 缩放返回 1.5，100% 返回 1.0。
    """
    try:
        import ctypes.wintypes as _wt
        # 获取主显示器句柄
        hmon = ctypes.windll.user32.MonitorFromPoint(  # type: ignore[attr-defined]
            _wt.POINT(0, 0), 2  # MONITOR_DEFAULTTOPRIMARY
        )
        sf = ctypes.c_uint(0)
        hr = ctypes.windll.shcore.GetScaleFactorForMonitor(hmon, ctypes.byref(sf))  # type: ignore[attr-defined]
        if hr == 0 and sf.value > 0:
            return sf.value / 100.0
    except Exception:  # noqa: BLE001
        pass

    # 回退：GetDpiForSystem
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()  # type: ignore[attr-defined]
        if dpi > 0:
            return dpi / 96.0
    except Exception:  # noqa: BLE001
        pass

    # 最后回退：GetDeviceCaps
    try:
        hdc = ctypes.windll.user32.GetDC(0)  # type: ignore[attr-defined]
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX  # type: ignore[attr-defined]
        ctypes.windll.user32.ReleaseDC(0, hdc)  # type: ignore[attr-defined]
        if dpi > 0:
            return dpi / 96.0
    except Exception:  # noqa: BLE001
        pass

    return 1.0


# ---------------------------------------------------------------------------
# DPI 自适应：缓存 scale 和 awareness，避免每次调用都重新读取
# ---------------------------------------------------------------------------

def _get_awareness() -> int:
    """读取当前进程的 DPI awareness 级别（0=UNAWARE, 1=SYSTEM, 2=PER_MONITOR）。"""
    try:
        v = ctypes.c_int(0)
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(v))  # type: ignore[attr-defined]
        return v.value
    except Exception:  # noqa: BLE001
        return 0


def _phys_to_logical(px: int, py: int, scale: float, awareness: int) -> tuple[int, int]:
    """将 mss 物理像素坐标转换为 pyautogui.moveTo 期望的坐标。

    awareness < 2 时 pyautogui 使用逻辑坐标（物理/scale）。
    awareness >= 2 时 pyautogui 使用物理坐标，无需转换。
    """
    if awareness >= 2 or scale <= 1.0:
        return px, py
    return round(px / scale), round(py / scale)


def _logical_to_phys(lx: int, ly: int, scale: float, awareness: int) -> tuple[int, int]:
    """将 pyautogui.position() 返回的坐标转换为物理像素坐标。"""
    if awareness >= 2 or scale <= 1.0:
        return lx, ly
    return round(lx * scale), round(ly * scale)


def _is_in_bounds(x: int, y: int) -> bool:
    """检查物理像素坐标是否在主屏幕范围内。"""
    left, top, w, h = _get_virtual_screen_rect()
    return left <= x < left + w and top <= y < top + h


def _clamp_to_virtual_screen(x: int, y: int) -> tuple[int, int]:
    left, top, w, h = _get_virtual_screen_rect()
    right = left + w - 1
    bottom = top + h - 1
    return max(left, min(x, right)), max(top, min(y, bottom))


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _get_cursor_pos() -> tuple[int, int]:
    if sys.platform != "win32":
        p = pyautogui.position()
        return int(p.x), int(p.y)
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    pt = _POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]


_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000


def _to_absolute(x: int, y: int) -> tuple[int, int]:
    left, top, w, h = _get_virtual_screen_rect()
    if w <= 1 or h <= 1:
        return 0, 0
    ax = int(round((x - left) * 65535 / (w - 1)))
    ay = int(round((y - top) * 65535 / (h - 1)))
    return max(0, min(ax, 65535)), max(0, min(ay, 65535))


def _send_inputs(inputs: list[_INPUT]) -> None:
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    arr = (_INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error())


def _send_move(x: int, y: int) -> None:
    x, y = _clamp_to_virtual_screen(x, y)
    if sys.platform != "win32":
        pyautogui.moveTo(x, y)
        return
    ax, ay = _to_absolute(x, y)
    inp = _INPUT(
        type=_INPUT_MOUSE,
        mi=_MOUSEINPUT(
            dx=ax,
            dy=ay,
            mouseData=0,
            dwFlags=_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
            time=0,
            dwExtraInfo=0,
        ),
    )
    _send_inputs([inp])


def _send_click(click_type: Literal["single", "double", "right"]) -> None:
    if sys.platform != "win32":
        if click_type == "right":
            pyautogui.rightClick()
        elif click_type == "double":
            pyautogui.doubleClick()
        else:
            pyautogui.click()
        return

    if click_type == "right":
        down_flag, up_flag = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
        n = 1
    else:
        down_flag, up_flag = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
        n = 2 if click_type == "double" else 1

    for i in range(n):
        _send_inputs([
            _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=0)),
            _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=0)),
        ])
        if i + 1 < n:
            time.sleep(0.08)


# ---------------------------------------------------------------------------
# ctypes 备用点击（当 pyautogui 静默失败时使用）
# ---------------------------------------------------------------------------

# Windows mouse_event flags
_MOUSEEVENTF_MOVE       = 0x0001
_MOUSEEVENTF_LEFTDOWN   = 0x0002
_MOUSEEVENTF_LEFTUP     = 0x0004
_MOUSEEVENTF_RIGHTDOWN  = 0x0008
_MOUSEEVENTF_RIGHTUP    = 0x0010
_MOUSEEVENTF_ABSOLUTE   = 0x8000


def _ctypes_click(x: int, y: int, right: bool = False) -> None:
    """使用 ctypes SetCursorPos + mouse_event 执行点击（pyautogui 的备用方案）。

    适用于 pyautogui 被系统拦截或静默失败的场景（如管理员权限窗口）。

    Args:
        x: 目标 X 坐标（物理像素坐标）。
        y: 目标 Y 坐标（物理像素坐标）。
        right: True 为右键点击，False 为左键点击。
    """
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        if right:
            user32.mouse_event(_MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(_MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        else:
            user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        logger.info("_ctypes_click: 已在 (%d, %d) 执行 %s 点击", x, y, "右键" if right else "左键")
    except Exception as exc:  # noqa: BLE001
        logger.error("_ctypes_click: 失败 (%d, %d): %s", x, y, exc)


# ---------------------------------------------------------------------------
# ActionEngine
# ---------------------------------------------------------------------------

class ActionEngine:
    """动作执行引擎：封装鼠标/键盘模拟操作，使用贝塞尔曲线拟人化移动。"""

    def __init__(self, dpi_adapter: DPIAdapter | None = None) -> None:
        """初始化 ActionEngine。

        Args:
            dpi_adapter: 保留参数，当前 DPI-unaware 模式下不使用。
        """
        self._dpi = dpi_adapter if dpi_adapter is not None else DPIAdapter()
        logger.info("ActionEngine 初始化完成，DPI scale_factor=%.2f", self._dpi.scale_factor)

    def click(
        self,
        x: int,
        y: int,
        click_type: Literal["single", "double", "right"] = "single",
        monitor_index: int = 0,
    ) -> bool:
        """在逻辑坐标处执行拟人化鼠标点击。

        全程使用 ctypes SetCursorPos + mouse_event，绕过 pyautogui 在后台线程
        的坐标系偏移问题，也不受 with_retry 的重试等待影响。

        Args:
            x: 目标 X 坐标（与 mss 截图同坐标系）。
            y: 目标 Y 坐标。
            click_type: "single"、"double" 或 "right"。
            monitor_index: 保留参数，当前未使用。

        Returns:
            操作成功返回 True，失败返回 False。
        """
        x, y = _clamp_to_virtual_screen(x, y)
        left, top, sw, sh = _get_virtual_screen_rect()

        t0 = time.monotonic()
        logger.info("click: 开始 — 逻辑目标=(%d,%d) virtual=(%d,%d,%d,%d)", x, y, left, top, sw, sh)

        try:
            scale = _get_dpi_scale()
            awareness = _get_awareness()

            # 将逻辑坐标转换为物理坐标，human_like_move 和 _send_move 需要物理坐标
            phys_x, phys_y = self._dpi.to_physical(x, y)
            logger.info(
                "click: 逻辑=(%d,%d) -> 物理=(%d,%d) scale=%.2f awareness=%d",
                x, y, phys_x, phys_y, scale, awareness,
            )

            human_like_move(phys_x, phys_y)
            time.sleep(0.02)

            actual_phys_x, actual_phys_y = _get_cursor_pos()
            deviation = math.hypot(actual_phys_x - phys_x, actual_phys_y - phys_y)
            logger.info(
                "click: 移动耗时=%.3fs 实际物理=(%d,%d) 期望物理=(%d,%d) 偏差=%.0fpx scale=%.2f awareness=%d",
                time.monotonic() - t0, actual_phys_x, actual_phys_y, phys_x, phys_y, deviation, scale, awareness,
            )

            if deviation > 15:
                logger.warning("click: 偏差%.0fpx 超限，直接跳转", deviation)
                _send_move(phys_x, phys_y)
                time.sleep(0.02)
                actual_phys_x, actual_phys_y = _get_cursor_pos()
                deviation = math.hypot(actual_phys_x - phys_x, actual_phys_y - phys_y)
                if deviation > 15:
                    logger.error(
                        "click: 位置校验失败 目标物理=(%d,%d) 实际=(%d,%d) 偏差=%.0fpx",
                        phys_x, phys_y, actual_phys_x, actual_phys_y, deviation,
                    )
                    return False

            fine_phys_x, fine_phys_y = _clamp_to_virtual_screen(
                phys_x + random.randint(-2, 2),
                phys_y + random.randint(-2, 2),
            )
            _send_move(fine_phys_x, fine_phys_y)
            time.sleep(0.05)

            _send_click(click_type)

            time.sleep(0.15)
            logger.info(
                "click: 完成 — 总耗时=%.3fs 逻辑目标=(%d,%d) 物理落点=(%d,%d) type=%s",
                time.monotonic() - t0, x, y, fine_phys_x, fine_phys_y, click_type,
            )
            return True

        except Exception as exc:
            logger.error("click: 失败 (%d,%d): %s", x, y, exc)
            return False

    @with_retry
    def type_text(self, text: str) -> bool:
        """通过剪贴板粘贴方式输入文本（支持中文）。"""
        if not text:
            logger.warning("type_text: 收到空文本，跳过操作")
            return True
        try:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            logger.info("type_text: 已通过剪贴板粘贴输入文本（长度=%d）", len(text))
            return True
        except Exception as exc:
            logger.error("type_text: 输入文本失败: %s", exc)
            raise

    @with_retry
    def open_application(self, name_or_path: str) -> bool:
        """启动应用程序。"""
        if not name_or_path:
            logger.error("open_application: 应用名称或路径为空")
            return False

        resolved = _ALIAS_MAP.get(name_or_path, name_or_path)
        if resolved != name_or_path:
            logger.info("open_application: 别名 %r → %r", name_or_path, resolved)

        try:
            subprocess.Popen(resolved, shell=True)  # noqa: S602
            logger.info("open_application: 已启动 %r", resolved)
            return True
        except Exception as exc:
            logger.warning("open_application: subprocess 启动失败，尝试 pywinauto: %s", exc)

        try:
            from pywinauto import Application  # type: ignore[import-untyped]
            app = Application(backend="uia")
            app.start(resolved)
            logger.info("open_application: 已通过 pywinauto 启动 %r", resolved)
            return True
        except Exception as exc:
            logger.error("open_application: pywinauto 启动也失败: %s", exc)
            raise

    @with_retry
    def key_press(self, key: str) -> bool:
        """按下并释放指定按键。"""
        if not key:
            logger.error("key_press: 按键名称为空")
            return False
        try:
            pyautogui.press(key)
            logger.info("key_press: 已按下按键 %r", key)
            return True
        except Exception as exc:
            logger.error("key_press: 操作失败 key=%r: %s", key, exc)
            raise

    def move_to(self, x: int, y: int, monitor_index: int = 0) -> bool:
        """拟人化移动鼠标至目标坐标。"""
        if not _is_in_bounds(x, y):
            logger.error("move_to: 坐标 (%d, %d) 超出屏幕边界，操作已取消", x, y)
            return False
        try:
            human_like_move(x, y)
            logger.info("move_to: 鼠标已移动至 (%d, %d)", x, y)
            return True
        except Exception as exc:
            logger.error("move_to: 操作失败 (%d, %d): %s", x, y, exc)
            raise

    @with_retry
    def drag(
        self,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        duration: float = 0.5,
        monitor_index: int = 0,
    ) -> bool:
        """从起点拟人化移动后拖拽到终点。"""
        if not _is_in_bounds(from_x, from_y):
            logger.error("drag: 起点坐标 (%d, %d) 超出屏幕边界，操作已取消", from_x, from_y)
            return False
        if not _is_in_bounds(to_x, to_y):
            logger.error("drag: 终点坐标 (%d, %d) 超出屏幕边界，操作已取消", to_x, to_y)
            return False
        try:
            human_like_move(from_x, from_y)
            if sys.platform == "win32":
                _send_inputs([
                    _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=_MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=0)),
                ])
                steps = max(1, int(duration / 0.01))
                for i in range(1, steps + 1):
                    t = i / steps
                    mx = int(round(from_x + (to_x - from_x) * t))
                    my = int(round(from_y + (to_y - from_y) * t))
                    _send_move(mx, my)
                    time.sleep(0.01)
                _send_inputs([
                    _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=_MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=0)),
                ])
            else:
                pyautogui.dragTo(to_x, to_y, duration=duration, button="left")
            logger.info(
                "drag: 已从 (%d, %d) 拖拽至 (%d, %d)，duration=%.2fs",
                from_x, from_y, to_x, to_y, duration,
            )
            return True
        except Exception as exc:
            logger.error("drag: 操作失败 (%d, %d) -> (%d, %d): %s", from_x, from_y, to_x, to_y, exc)
            raise
