"""
automation.software_installer — 真实智能安装执行器。

启动安装包进程，通过感知层定位安装按钮，通过执行层模拟点击，
通过 progress_callback 实时上报每个安装步骤进度。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from automation.object_detector import DetectionCache

logger = logging.getLogger(__name__)


def normalize_path(raw: str | Path) -> Path:
    """规范化安装包路径，消除相对路径分量并返回绝对路径。

    Args:
        raw: 原始路径字符串或 Path 对象（可含空格、特殊字符、相对分量）。

    Returns:
        经 ``Path.resolve()`` 处理后的绝对 Path 对象。
    """
    return Path(raw).resolve()


_SHELL_ERROR_MAP: dict[int, str] = {
    2: "文件未找到",
    3: "路径无效",
    5: "权限不足，请以管理员身份运行",
    8: "内存不足",
    31: "文件关联不存在",
    32: "文件被其他进程占用",
}


def translate_shell_error(code: int) -> str:
    """将 ShellExecuteW 返回的错误码转换为可读的中文说明。

    Args:
        code: ``ShellExecuteW`` 返回的整数错误码。

    Returns:
        对应的中文错误说明；未知错误码时返回 ``f"未知错误（代码 {code}）"``。
    """
    return _SHELL_ERROR_MAP.get(code, f"未知错误（代码 {code}）")


# ---------------------------------------------------------------------------
# UAC 提权检测 (P2)
# ---------------------------------------------------------------------------

def _is_elevated() -> bool:
    """检查当前进程是否以管理员权限运行。"""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 安装窗口查找 helper (P3/P4 共用，纯 ctypes，不依赖 pygetwindow)
# ---------------------------------------------------------------------------

# 常见安装程序窗口标题关键词
_INSTALLER_KEYWORDS: list[str] = ["安装", "Setup", "Install", "Wizard", "向导"]


def _find_installer_hwnd(window_hint: str = "") -> int | None:
    """用 EnumWindows 查找安装窗口句柄，匹配标题关键词。

    遍历所有可见顶层窗口，依次用 window_hint 和通用关键词匹配窗口标题。

    Args:
        window_hint: 优先匹配的关键词（通常为安装包文件名去掉扩展名）。

    Returns:
        匹配的窗口句柄 (hwnd)；未找到时返回 None。
    """
    if sys.platform != "win32":
        return None

    keywords = [window_hint] + _INSTALLER_KEYWORDS if window_hint else list(_INSTALLER_KEYWORDS)
    keywords = [kw for kw in keywords if kw]
    found_hwnd: list[int] = []

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if not title:
            return True
        for kw in keywords:
            if kw.lower() in title.lower():
                found_hwnd.append(hwnd)
                return False  # 停止枚举
        return True

    cb = WNDENUMPROC(_callback)
    user32.EnumWindows(cb, 0)

    if found_hwnd:
        logger.info("_find_installer_hwnd: 找到窗口 hwnd=%d", found_hwnd[0])
        return found_hwnd[0]

    logger.debug("_find_installer_hwnd: 未找到匹配窗口 (keywords=%s)", keywords)
    return None


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """获取窗口的屏幕矩形区域。

    Args:
        hwnd: 窗口句柄。

    Returns:
        (left, top, width, height) 物理像素坐标元组；失败返回 None。
    """
    try:
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))  # type: ignore[attr-defined]
        left = rect.left
        top = rect.top
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return (left, top, width, height)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_get_window_rect: 获取窗口矩形失败 hwnd=%d: %s", hwnd, exc)
        return None


@dataclass
class InstallStep:
    """安装步骤定义（扩展版）。

    Attributes:
        button_text: 要点击的按钮文本（用于 ElementLocator）。
        aliases: 按钮文字的备选变体列表（如"Next"、"下一步(N)"等）。
        step_name: 步骤描述（用于 progress_callback）。
        timeout: 等待按钮出现的超时时间（秒）。
        optional: 若为 True，按钮未找到时跳过而非报错。
    """

    button_text: str
    step_name: str
    timeout: float = 30.0
    optional: bool = False
    aliases: list[str] | None = None


# 通用安装步骤序列。
# optional=True 的步骤在超时后跳过，不同安装器的界面差异不会导致整体失败。
INSTALL_STEPS: list[InstallStep] = [
    InstallStep(
        "下一步", "点击'下一步'按钮", optional=True,
        aliases=["Next", "下一步(N)", "下一步 >", "下一步>", "继续", "Continue"],
    ),
    InstallStep(
        "我同意", "接受许可协议", optional=True,
        aliases=["I Agree", "I agree", "接受", "同意", "我接受", "Accept", "Yes"],
    ),
    InstallStep(
        "安装", "开始安装", optional=True,
        aliases=["Install", "安装(I)", "立即安装", "开始安装", "Install Now"],
    ),
    InstallStep(
        "完成", "完成安装", optional=False,
        aliases=["Finish", "完成(F)", "关闭", "Close", "Done", "退出"],
    ),
]


def _activate_installer_window(window_hint: str = "") -> tuple[int, int, int, int] | None:
    """尝试将安装程序窗口激活到前台，并返回窗口区域。

    使用 ctypes FindWindow + SetForegroundWindow（比 pygetwindow 更可靠），
    同时返回窗口的 (left, top, width, height) 供截图裁剪使用。
    若找不到则静默跳过，返回 None。

    Args:
        window_hint: 窗口标题关键词（通常是安装包文件名去掉扩展名）。

    Returns:
        窗口区域 (left, top, width, height) 或 None（未找到时）。
    """
    import ctypes as _ctypes

    user32 = _ctypes.windll.user32  # type: ignore[attr-defined]

    class RECT(_ctypes.Structure):
        _fields_ = [("left", _ctypes.c_long), ("top", _ctypes.c_long),
                    ("right", _ctypes.c_long), ("bottom", _ctypes.c_long)]

    # 常见安装程序窗口标题关键词
    keywords = [window_hint, "安装", "Setup", "Install", "Wizard", "向导", "安装程序"]
    keywords = [k for k in keywords if k]

    # 枚举所有顶层窗口，找到标题包含关键词的
    found_hwnd = None
    found_title = ""

    EnumWindowsProc = _ctypes.WINFUNCTYPE(_ctypes.c_bool, _ctypes.c_ulong, _ctypes.c_long)
    hwnds: list[int] = []

    def _enum_cb(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = _ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                for kw in keywords:
                    if kw.lower() in title.lower():
                        hwnds.append(hwnd)
                        return True
        return True

    user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)

    if not hwnds:
        # 降级：pygetwindow
        try:
            import pygetwindow as gw  # type: ignore[import-untyped]
            for kw in keywords:
                wins = gw.getWindowsWithTitle(kw)
                if wins:
                    win = wins[0]
                    win.activate()
                    time.sleep(0.2)
                    logger.debug("_activate_installer_window: pygetwindow 激活 %r", win.title)
                    return (win.left, win.top, win.width, win.height)
        except Exception:  # noqa: BLE001
            pass
        logger.debug("_activate_installer_window: 未找到安装窗口")
        return None

    hwnd = hwnds[0]
    # 激活窗口
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # 获取窗口区域
    rect = RECT()
    user32.GetWindowRect(hwnd, _ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w > 0 and h > 0:
        buf = _ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        logger.debug("_activate_installer_window: 已激活 %r 区域=(%d,%d,%d,%d)",
                     buf.value, rect.left, rect.top, w, h)
        return (rect.left, rect.top, w, h)
    return None


def _launch_package(pkg: Path) -> None:
    """启动安装包，按优先级尝试三种方式。

    1. subprocess.Popen(shell=True) — 最可靠，shell 自动处理特殊字符和空格
    2. os.startfile — 简单路径的快速路径
    3. ShellExecuteW runas — 需要管理员权限时的最后手段

    Args:
        pkg: 已规范化的安装包绝对路径。

    Raises:
        RuntimeError: 三种方式均失败时抛出，包含中文错误说明。
    """
    # 方式一：subprocess.Popen with shell=True — 用双引号包裹路径，可靠处理空格和特殊字符
    try:
        subprocess.Popen(f'"{pkg}"', shell=True)  # noqa: S602
        logger.info("subprocess.Popen 启动成功：%s", pkg)
        return
    except Exception as exc:
        logger.warning("subprocess.Popen 失败，尝试 os.startfile: %s", exc)

    # 方式二：os.startfile
    try:
        os.startfile(str(pkg))  # type: ignore[attr-defined]
        logger.info("os.startfile 启动成功：%s", pkg)
        return
    except OSError as exc:
        logger.warning("os.startfile 失败，尝试 ShellExecuteW runas: %s", exc)

    # 方式三：ShellExecuteW with runas（触发 UAC 提权弹窗）
    import ctypes as _ctypes  # noqa: PLC0415
    ret = _ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", str(pkg), None, str(pkg.parent), 1
    )
    if ret <= 32:
        raise RuntimeError(f"无法启动安装包（{translate_shell_error(ret)}）：{pkg}")
    logger.info("ShellExecuteW runas 启动成功：%s", pkg)


def run_software_installer(
    package_path: str | Path,
    progress_callback: Callable[[str, int], None],
    stop_event: threading.Event,
    initial_dir: str | None = None,
    detection_cache: DetectionCache | None = None,
) -> None:
    """执行真实智能安装任务。

    Args:
        package_path: 安装包文件路径（.exe / .msi）。
        progress_callback: 签名 (step_description: str, percent: int) -> None。
        stop_event: 外部停止信号。
        initial_dir: 保留参数，供调用方记录文件选择对话框的初始目录（当前未使用）。
        detection_cache: 可选 DetectionCache，供 GUI 预览叠加识别框。

    Raises:
        FileNotFoundError: package_path 不存在时抛出，消息包含路径。
        TimeoutError: 安装按钮在 timeout 秒内未被定位到时抛出。
    """
    from execution.action_engine import ActionEngine
    from perception.element_locator import ElementLocator
    from perception.screen_capturer import ScreenCapturer
    from automation.object_detector import DetectionCache as _DetectionCache  # noqa: F401
    from automation.vision_box_drawer import BoundingBoxDict

    pkg = normalize_path(package_path)
    if not pkg.exists():
        raise FileNotFoundError(f"安装包不存在：{package_path}")

    screen_capturer = ScreenCapturer()
    element_locator = ElementLocator()
    action_engine = ActionEngine()

    logger.info("启动安装包进程：%s", pkg)
    _launch_package(pkg)

    # 等待安装程序窗口渲染完成（通常需要 2-5 秒）
    logger.info("等待安装程序窗口出现（5秒）...")
    time.sleep(5)

    total = len(INSTALL_STEPS)
    current_percent = 0

    try:
        for i, step in enumerate(INSTALL_STEPS):
            if stop_event.is_set():
                logger.info("智能安装任务收到停止信号，已中止（步骤 %d/%d）", i, total)
                return

            current_percent = int((i + 1) / total * 100)
            logger.info("开始安装步骤 %d/%d：%s", i + 1, total, step.step_name)

            # Wait for button to appear within timeout
            deadline = time.monotonic() + step.timeout
            found = False
            # All candidate texts to try: primary + aliases
            candidates = [step.button_text] + (step.aliases or [])

            while time.monotonic() < deadline:
                if stop_event.is_set():
                    logger.info("智能安装任务收到停止信号，已中止（步骤 %d/%d）", i + 1, total)
                    return

                for candidate in candidates:
                    try:
                        # 激活安装窗口并获取窗口区域（用于裁剪截图，减少干扰）
                        win_rect = _activate_installer_window(pkg.stem)

                        # 优先截取安装窗口区域，减少背景干扰，提升 Qwen-VL 识别准确率
                        if win_rect is not None:
                            wx, wy, ww, wh = win_rect
                            try:
                                screenshot = screen_capturer.capture_region(wx, wy, ww, wh)
                                coord_offset = (wx, wy)
                            except Exception:
                                screenshot = screen_capturer.capture_full()
                                coord_offset = (0, 0)
                        else:
                            screenshot = screen_capturer.capture_full()
                            coord_offset = (0, 0)

                        result = element_locator.locate_by_text(screenshot, candidate)
                        if detection_cache is not None:
                            detection_cache.update([BoundingBoxDict(
                                bbox=list(result.bbox),
                                label=candidate,
                                confidence=result.confidence,
                            )])
                        # bbox 中心点 + 窗口偏移 = 屏幕绝对坐标
                        cx = result.bbox[0] + result.bbox[2] // 2 + coord_offset[0]
                        cy = result.bbox[1] + result.bbox[3] // 2 + coord_offset[1]
                        action_engine.click(cx, cy)
                        logger.info(
                            "点击按钮成功：%s（候选文字=%r），坐标=(%d, %d)",
                            step.button_text, candidate, cx, cy,
                        )
                        found = True
                        break
                    except Exception as exc:
                        logger.warning("候选文字 %r 定位失败：%s", candidate, exc)

                if found:
                    break

                logger.warning("定位或点击按钮失败：%s，所有候选均未找到", step.button_text)
                time.sleep(0.5)

            if not found:
                msg = f"超时：未找到'{step.button_text}'按钮"
                logger.warning(msg)
                progress_callback(msg, current_percent)
                if step.optional:
                    logger.info("步骤 '%s' 为可选步骤，跳过继续", step.button_text)
                    continue
                raise TimeoutError(
                    f"安装按钮'{step.button_text}'在 {step.timeout}s 内未被定位到"
                )

            progress_callback(step.step_name, current_percent)
    except Exception:
        logger.exception("run_software_installer 发生未预期异常")
        progress_callback("安装异常终止", current_percent)
        raise
