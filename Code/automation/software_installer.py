"""
automation.software_installer — 真实智能安装执行器。

支持三种安装模式（通过 install_mode 参数控制）：

- "silent"：静默模式，pywinauto 控件 API 直接定位点击，无视觉 API 调用，速度最快。
- "visual"：纯视觉模式，Qwen-VL / OCR 定位，失败则抛出异常（不降级）。
- "visual_with_fallback"（默认）：视觉优先，视觉失败时自动降级到 pywinauto，
  始终向 detection_cache 推送识别框供 GUI 展示。
"""
from __future__ import annotations

import base64
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
from typing import TYPE_CHECKING, Literal

import cv2
import numpy as np

if TYPE_CHECKING:
    from automation.object_detector import DetectionCache

InstallMode = Literal["silent", "visual", "visual_with_fallback"]

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
        logger.info("_activate_installer_window: 已激活 %r 区域=(%d,%d,%d,%d)",
                     buf.value, rect.left, rect.top, w, h)
        return (rect.left, rect.top, w, h)
    return None


def _launch_package(pkg: Path) -> bool:
    """启动安装包，按优先级尝试三种方式。

    1. subprocess.Popen(shell=True) — 最可靠，shell 自动处理特殊字符和空格
    2. os.startfile — 简单路径的快速路径
    3. ShellExecuteW runas — 需要管理员权限时的最后手段

    Args:
        pkg: 已规范化的安装包绝对路径。

    Returns:
        True 表示使用了 ShellExecuteW runas 提权启动，False 表示普通启动。

    Raises:
        RuntimeError: 三种方式均失败时抛出，包含中文错误说明。
    """
    # 方式一：subprocess.Popen with shell=True
    try:
        subprocess.Popen(f'"{pkg}"', shell=True)  # noqa: S602
        logger.info("subprocess.Popen 启动成功：%s", pkg)
        return False
    except Exception as exc:
        logger.warning("subprocess.Popen 失败，尝试 os.startfile: %s", exc)

    # 方式二：os.startfile
    try:
        os.startfile(str(pkg))  # type: ignore[attr-defined]
        logger.info("os.startfile 启动成功：%s", pkg)
        return False
    except OSError as exc:
        logger.warning("os.startfile 失败，尝试 ShellExecuteW runas: %s", exc)

    # 方式三：ShellExecuteW with runas（触发 UAC 提权弹窗）
    import ctypes as _ctypes  # noqa: PLC0415
    ret = _ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", str(pkg), None, str(pkg.parent), 1
    )
    if ret <= 32:
        raise RuntimeError(f"无法启动安装包（{translate_shell_error(ret)}）：{pkg}")
    logger.info("ShellExecuteW runas 启动成功（已提权）：%s", pkg)
    return True  # 使用了提权启动


def run_software_installer(
    package_path: str | Path,
    progress_callback: Callable[[str, int], None],
    stop_event: threading.Event,
    initial_dir: str | None = None,
    detection_cache: DetectionCache | None = None,
    install_mode: InstallMode = "visual_with_fallback",
) -> None:
    """执行真实智能安装任务。

    Args:
        package_path: 安装包文件路径（.exe / .msi）。
        progress_callback: 签名 (step_description: str, percent: int) -> None。
        stop_event: 外部停止信号。
        initial_dir: 保留参数，供调用方记录文件选择对话框的初始目录（当前未使用）。
        detection_cache: 可选 DetectionCache，供 GUI 预览叠加识别框。
        install_mode: 安装模式。
            - "silent"：pywinauto 控件 API，无视觉调用，速度最快。
            - "visual"：纯视觉（Qwen-VL/OCR），失败不降级。
            - "visual_with_fallback"（默认）：视觉优先，失败降级到 pywinauto，
              始终推送识别框到 detection_cache。

    Raises:
        FileNotFoundError: package_path 不存在时抛出，消息包含路径。
        TimeoutError: 安装按钮在 timeout 秒内未被定位到时抛出。
    """
    from execution.action_engine import ActionEngine
    from perception.element_locator import ElementLocator
    from perception.screen_capturer import ScreenCapturer
    from automation.vision_box_drawer import BoundingBoxDict

    pkg = normalize_path(package_path)
    if not pkg.exists():
        raise FileNotFoundError(f"安装包不存在：{package_path}")

    screen_capturer = ScreenCapturer()
    element_locator = ElementLocator()
    action_engine = ActionEngine()

    logger.info("启动安装包进程：%s", pkg)
    used_elevation = _launch_package(pkg)

    # P2: UAC 提权隔离警告
    if used_elevation and not _is_elevated():
        msg = (
            "⚠️ 安装包以管理员权限启动，但本应用未提权。"
            "Windows UIPI 可能阻止鼠标模拟操作（SetCursorPos/mouse_event 对提权窗口无效）。"
            "建议：右键本应用 → 以管理员身份运行。"
        )
        logger.warning(msg)
        progress_callback(msg, 0)

    # 等待安装程序窗口渲染完成
    logger.info("等待安装程序窗口出现（2秒）...")
    progress_callback("等待安装界面加载…", 0)
    time.sleep(2)

    # 视觉诊断（DEBUG_VISION=true 时在后台线程中执行，不阻塞安装流程）
    try:
        from automation.vision_diagnose import diagnose_vision_async
        _diag_screenshot = screen_capturer.capture_full().copy()
        diagnose_vision_async(_diag_screenshot)
    except Exception as _diag_exc:  # noqa: BLE001
        logger.debug("视觉诊断启动失败（不影响安装）：%s", _diag_exc)

    logger.info("安装模式：%s（GUI-Plus 自主模式）", install_mode)

    # ── GUI-Plus 自主 ReAct 循环 ────────────────────────────────────────
    # 不再使用固定步骤列表，由 GUI-Plus 自己截图、分析界面、决定操作，
    # 循环执行直到模型返回 terminate（安装完成）或超时/停止信号。
    # ──────────────────────────────────────────────────────────────────
    import json as _json
    import math as _math
    import re as _re
    from pathlib import Path as _Path
    from dotenv import load_dotenv as _load_dotenv
    from openai import OpenAI as _OpenAI

    # 确保 API key 已加载
    _load_dotenv(dotenv_path=_Path(__file__).parent.parent / "config" / ".env", override=False)
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法使用 GUI-Plus 自主安装模式")

    # GUI-Plus 官方推荐 system prompt（电脑端完整版）
    _SYSTEM_PROMPT = (
        "# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
        "You are provided with function signatures within <tools></tools> XML tags:\n"
        "<tools>\n"
        '{"type": "function", "function": {"name": "computer_use", "description": '
        '"Use a mouse and keyboard to interact with a computer, and take screenshots.\\n'
        "* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. "
        "You must click on desktop icons to start applications.\\n"
        "* Some applications may take time to start or process actions, so you may need to wait and take "
        "successive screenshots to see the results of your actions.\\n"
        "* The screen's resolution is 1000x1000.\\n"
        '* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. '
        "Don\\'t click boxes on their edges unless asked.\", "
        '"parameters": {"properties": {'
        '"action": {"description": "The action to perform. The available actions are:\\n'
        "* `key`: Performs key down presses on the arguments passed in order, then performs key releases in reverse order.\\n"
        "* `type`: Type a string of text on the keyboard.\\n"
        "* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\\n"
        "* `left_click`: Click the left mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
        "* `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.\\n"
        "* `right_click`: Click the right mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
        "* `double_click`: Double-click the left mouse button at a specified (x, y) pixel coordinate on the screen.\\n"
        "* `scroll`: Performs a scroll of the mouse scroll wheel.\\n"
        "* `wait`: Wait specified seconds for the change to happen.\\n"
        '* `terminate`: Terminate the current task and report its completion status.", '
        '"enum": ["key", "type", "mouse_move", "left_click", "left_click_drag", "right_click", '
        '"double_click", "scroll", "wait", "terminate"], "type": "string"}, '
        '"coordinate": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) '
        "coordinates to move the mouse to. Required only by `action=mouse_move` and `action=left_click_drag`.\", "
        '"type": "array"}, '
        '"keys": {"description": "Required only by `action=key`.", "type": "array"}, '
        '"text": {"description": "Required only by `action=type`.", "type": "string"}, '
        '"pixels": {"description": "The amount of scrolling to perform. Positive values scroll up, negative values scroll down. '
        'Required only by `action=scroll`.", "type": "number"}, '
        '"time": {"description": "The seconds to wait. Required only by `action=wait`.", "type": "number"}, '
        '"status": {"description": "The status of the task. Required only by `action=terminate`.", '
        '"type": "string", "enum": ["success", "failure"]}}, '
        '"required": ["action"], "type": "object"}}}\n'
        "</tools>\n\n"
        "For each function call, return a json object with function name and arguments within "
        "<tool_call></tool_call> XML tags:\n"
        "<tool_call>\n{\"name\": <function-name>, \"arguments\": <args-json-object>}\n</tool_call>\n\n"
        "# Response format\n\n"
        "Response format for every step:\n"
        "1) Action: a short imperative describing what to do in the UI.\n"
        "2) A single <tool_call>...</tool_call> block containing only the JSON.\n\n"
        "Rules:\n"
        "- Output exactly in the order: Action, <tool_call>.\n"
        "- Be brief: one line for Action.\n"
        "- Do not output anything else outside those two parts.\n"
        "- If finishing, use action=terminate in the tool call."
    )

    def _smart_resize(height: int, width: int) -> tuple[int, int]:
        """计算 GUI-Plus 模型内部 resize 后的图像尺寸（官方参数）。"""
        factor = 32
        min_pixels = 3136
        max_pixels = 1_003_520

        def _round(n: int) -> int:
            return round(n / factor) * factor

        def _floor(n: float) -> int:
            return _math.floor(n / factor) * factor

        def _ceil(n: float) -> int:
            return _math.ceil(n / factor) * factor

        h_bar, w_bar = _round(height), _round(width)
        if h_bar * w_bar > max_pixels:
            beta = _math.sqrt((height * width) / max_pixels)
            h_bar, w_bar = _floor(height / beta), _floor(width / beta)
        elif h_bar * w_bar < min_pixels:
            beta = _math.sqrt(min_pixels / (height * width))
            h_bar, w_bar = _ceil(height * beta), _ceil(width * beta)
        return h_bar, w_bar

    def _screenshot_to_b64(frame: np.ndarray) -> str:
        success, buf = cv2.imencode(".png", frame)
        if not success:
            raise RuntimeError("截图编码失败")
        return base64.b64encode(buf.tobytes()).decode("utf-8")

    def _execute_action(args: dict, screenshot: "np.ndarray") -> None:
        """解析 GUI-Plus 返回的 action 并通过 action_engine 执行。"""
        action = args.get("action", "")
        coord = args.get("coordinate")
        h_img, w_img = screenshot.shape[:2]

        if coord and len(coord) >= 2:
            # 归一化坐标（0-1000）→ 原始图像像素坐标
            cx = int(float(coord[0]) / 1000.0 * w_img)
            cy = int(float(coord[1]) / 1000.0 * h_img)
        else:
            cx, cy = 0, 0

        if action == "left_click":
            action_engine.click(cx, cy, click_type="single")
            logger.info("GUI-Plus 执行 left_click (%d,%d)", cx, cy)
        elif action == "double_click":
            action_engine.click(cx, cy, click_type="double")
            logger.info("GUI-Plus 执行 double_click (%d,%d)", cx, cy)
        elif action == "right_click":
            action_engine.click(cx, cy, click_type="right")
            logger.info("GUI-Plus 执行 right_click (%d,%d)", cx, cy)
        elif action == "mouse_move":
            action_engine.move_to(cx, cy)
            logger.info("GUI-Plus 执行 mouse_move (%d,%d)", cx, cy)
        elif action == "left_click_drag":
            # 从当前位置拖拽到目标
            import ctypes as _ctypes, ctypes.wintypes as _wt
            pt = _wt.POINT()
            _ctypes.windll.user32.GetCursorPos(_ctypes.byref(pt))
            action_engine.drag(pt.x, pt.y, cx, cy)
            logger.info("GUI-Plus 执行 left_click_drag -> (%d,%d)", cx, cy)
        elif action == "key":
            keys = args.get("keys", [])
            if keys:
                action_engine.key_press("+".join(keys))
                logger.info("GUI-Plus 执行 key %s", keys)
        elif action == "type":
            text = args.get("text", "")
            if text:
                action_engine.type_text(text)
                logger.info("GUI-Plus 执行 type: %s", text[:30])
        elif action == "scroll":
            pixels = int(args.get("pixels", 3))
            import pyautogui as _pag
            if coord:
                _pag.moveTo(cx, cy)
            _pag.scroll(pixels)
            logger.info("GUI-Plus 执行 scroll %d", pixels)
        elif action == "wait":
            wait_sec = float(args.get("time", 2))
            time.sleep(min(wait_sec, 10))
            logger.info("GUI-Plus 执行 wait %.1fs", wait_sec)
        else:
            logger.warning("GUI-Plus 未知 action：%s", action)

    client = _OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=__import__("httpx").Client(trust_env=False),
    )

    # 多轮对话历史（保留最近 4 轮）
    history: list[dict] = []
    MAX_HISTORY = 4
    MAX_STEPS = 30
    current_percent = 0

    instruction = "请帮我完成这个软件的安装过程。点击所有必要的按钮（如下一步、同意、安装、完成等），直到安装完成。"

    progress_callback("GUI-Plus 正在分析安装界面…", 5)

    try:
        for step_num in range(1, MAX_STEPS + 1):
            if stop_event.is_set():
                logger.info("智能安装任务收到停止信号，已中止（步骤 %d）", step_num)
                return

            # 截图
            screenshot = screen_capturer.capture_full()
            b64 = _screenshot_to_b64(screenshot)
            h_img, w_img = screenshot.shape[:2]

            # 构造多轮对话消息
            history_start = max(0, len(history) - MAX_HISTORY)
            # 早期历史只保留文字摘要
            prev_actions = []
            for idx in range(history_start):
                out = history[idx].get("output", "")
                if "Action:" in out and "<tool_call>" in out:
                    summary = out.split("Action:")[1].split("<tool_call>")[0].strip()
                    prev_actions.append(f"Step {idx + 1}: {summary}")

            prev_str = "\n".join(prev_actions) if prev_actions else "None"
            user_prompt = (
                f"Please generate the next move according to the UI screenshot, "
                f"instruction and previous actions.\n\n"
                f"Instruction: {instruction}\n\n"
                f"Previous actions:\n{prev_str}"
            )

            messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

            # 最近 MAX_HISTORY 轮的完整历史（截图 + 输出）
            recent = history[-MAX_HISTORY:]
            for h_idx, h_item in enumerate(recent):
                if h_idx == 0:
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{h_item['b64']}"}},
                        ],
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{h_item['b64']}"}}],
                    })
                messages.append({"role": "assistant", "content": h_item["output"]})

            # 当前截图
            if recent:
                messages.append({
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}],
                })
            else:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                })

            logger.info("GUI-Plus 步骤 %d/%d：调用模型…", step_num, MAX_STEPS)
            progress_callback(f"GUI-Plus 分析界面（步骤 {step_num}）…", min(5 + step_num * 3, 90))

            # 调用 GUI-Plus
            response = client.chat.completions.create(
                model="gui-plus-2026-02-26",
                messages=messages,
                extra_body={"vl_high_resolution_images": True},
            )
            output_text: str = response.choices[0].message.content or ""
            logger.info("GUI-Plus 步骤 %d 输出：%s", step_num, output_text[:200])

            # 提取 action 描述用于日志
            action_desc = ""
            if "Action:" in output_text:
                action_desc = output_text.split("Action:")[1].split("<tool_call>")[0].strip()
                progress_callback(f"[步骤{step_num}] {action_desc}", min(5 + step_num * 3, 90))

            # 解析 tool_call
            blocks = _re.findall(r"<tool_call>(.*?)</tool_call>", output_text, _re.DOTALL | _re.IGNORECASE)
            if not blocks:
                logger.warning("GUI-Plus 步骤 %d：未找到 tool_call，跳过", step_num)
                history.append({"b64": b64, "output": output_text})
                time.sleep(1)
                continue

            tool_call = _json.loads(blocks[0].strip())
            args = tool_call.get("arguments", {})
            action = args.get("action", "")

            # 推送识别框到 detection_cache
            coord = args.get("coordinate")
            if detection_cache is not None and coord and len(coord) >= 2:
                cx_norm = int(float(coord[0]) / 1000.0 * w_img)
                cy_norm = int(float(coord[1]) / 1000.0 * h_img)
                _box_size = 60
                from automation.vision_box_drawer import BoundingBoxDict
                detection_cache.update([BoundingBoxDict(
                    bbox=[cx_norm - _box_size // 2, cy_norm - _box_size // 2,
                          cx_norm + _box_size // 2, cy_norm + _box_size // 2],
                    label=f"[GUI-Plus] {action_desc[:20]}",
                    confidence=0.92,
                )])

            # terminate = 安装完成
            if action == "terminate":
                status = args.get("status", "success")
                if status == "success":
                    progress_callback("✓ GUI-Plus 安装完成", 100)
                    logger.info("GUI-Plus 报告安装完成（步骤 %d）", step_num)
                else:
                    progress_callback(f"⚠ GUI-Plus 报告失败：{status}", current_percent)
                    logger.warning("GUI-Plus 报告安装失败：%s", status)
                return

            # 执行操作
            _execute_action(args, screenshot)
            current_percent = min(5 + step_num * 3, 90)

            # 保存历史
            history.append({"b64": b64, "output": output_text})

            # 操作后等待界面响应
            time.sleep(1.5)

        # 超过最大步骤数
        progress_callback("⚠ 超过最大步骤数，安装可能未完成", current_percent)
        logger.warning("GUI-Plus 超过最大步骤数 %d，退出", MAX_STEPS)

    except Exception:
        logger.exception("run_software_installer GUI-Plus 模式发生未预期异常")
        progress_callback("安装异常终止", current_percent)
        raise
