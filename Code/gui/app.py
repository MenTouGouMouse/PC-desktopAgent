"""
gui.app — PyWebView 窗口管理与 Python↔JS 桥接模块。

包含两个核心类：
- PythonAPI: 前端通过 window.pywebview.api.* 调用的桥接对象
- PyWebViewApp: 管理主窗口与悬浮球窗口生命周期的应用类
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import webview

from automation.file_organizer import run_file_organizer
from automation.object_detector import DetectionCache, VisionOverlayController
from automation.software_installer import run_software_installer
from decision.llm_client import LLMClient
from gui.chat_agent import ChatAgent
from gui.progress_manager import ProgressManager, TaskProgress
from ui.queue_manager import QueueManager

if TYPE_CHECKING:
    from vision.overlay_drawer import OverlayDrawer

_USER_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "user_settings.json"
_DEFAULT_ORGANIZE_SOURCE = os.path.expanduser("~/Desktop")
_DEFAULT_ORGANIZE_TARGET = os.path.expanduser("~/Organized")
_DEFAULT_INSTALLER_DIR = os.path.expanduser("~/Downloads")


class UserSettings(TypedDict):
    """用户可配置路径设置的结构化类型。"""
    organize_source: str
    organize_target: str
    installer_default_dir: str

logger = logging.getLogger(__name__)


class PythonAPI:
    """PyWebView JS↔Python 桥接对象。

    所有公共方法均在 PyWebView 的后台线程中被调用，必须线程安全。
    返回值自动序列化为 JSON 传回前端。
    """

    def __init__(
        self,
        progress_manager: ProgressManager,
        queue_manager: QueueManager,
    ) -> None:
        self._progress_manager = progress_manager
        self._queue_manager = queue_manager
        self._main_win: webview.Window | None = None
        self._ball_win: webview.Window | None = None
        self._stop_event: threading.Event = threading.Event()
        # Track whether the ball window is currently shown (managed internally)
        self._ball_is_shown: bool = False
        # Back-reference to PyWebViewApp for push_log calls; set by PyWebViewApp
        self._app: PyWebViewApp | None = None
        # ChatAgent — initialized lazily when _app is set
        self._chat_agent: ChatAgent | None = None

        # --- 检测框叠加相关 ---
        # 线程安全的检测结果缓存，由 VisionOverlayController 后台线程写入，
        # OverlayDrawer 在每帧绘制时读取
        self._detection_cache: DetectionCache = DetectionCache()
        # 后台检测控制器，set_show_boxes(True) 时启动，False 时停止
        self._overlay_controller: VisionOverlayController | None = None
        # 当前是否显示检测框
        self._show_boxes: bool = False
        # 待确认弹窗：confirm_id → (Event, [bool])
        self._pending_confirmations: dict[str, tuple[threading.Event, list[bool]]] = {}

    # ------------------------------------------------------------------
    # Called by PyWebViewApp after windows are created
    # ------------------------------------------------------------------

    def set_windows(
        self,
        main_win: webview.Window,
        ball_win: webview.Window | None = None,
    ) -> None:
        """Store window references (called by PyWebViewApp after creation)."""
        self._main_win = main_win
        self._ball_win = ball_win

    # ------------------------------------------------------------------
    # 检测框开关（前端 toggle 按钮调用）
    # ------------------------------------------------------------------

    def set_show_boxes(self, show: bool) -> dict:
        """启用或禁用实时检测框叠加。

        show=True  → 启动后台 VisionOverlayController，开始检测并写入缓存；
                     通知 OverlayDrawer 开始从缓存读取框数据绘制到每帧。
        show=False → 停止后台检测线程，清空缓存，OverlayDrawer 停止绘制框。

        Args:
            show: True 表示显示检测框，False 表示隐藏。

        Returns:
            {"success": True, "show": bool}
        """
        try:
            self._show_boxes = bool(show)
            logger.info("set_show_boxes: show=%s", self._show_boxes)

            if self._show_boxes:
                # 启动后台检测线程（已在运行则跳过）
                if self._overlay_controller is None:
                    self._overlay_controller = VisionOverlayController(
                        cache=self._detection_cache,
                        detect_interval_sec=0.5,  # 每 0.5s 检测一次，≤2次/秒
                    )
                self._overlay_controller.start()
                logger.info("set_show_boxes: VisionOverlayController 已启动")
            else:
                # 停止后台检测线程并清空缓存
                if self._overlay_controller is not None:
                    self._overlay_controller.stop()
                    self._overlay_controller = None
                self._detection_cache.clear()
                logger.info("set_show_boxes: VisionOverlayController 已停止，缓存已清空")

            # 通知 OverlayDrawer 更新 show_boxes 状态
            if self._app is not None:
                self._app.overlay_drawer_set_show_boxes(
                    self._show_boxes, self._detection_cache
                )

            return {"success": True, "show": self._show_boxes}
        except Exception as exc:  # noqa: BLE001
            logger.exception("set_show_boxes error")
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Task control
    # ------------------------------------------------------------------

    def start_file_organizer(self) -> dict:
        """Start the file organizer task in a background thread.

        Returns:
            {"success": True, "task_name": "file_organizer"} on success,
            {"success": False, "error": "..."} if already running or on exception.
        """
        try:
            if self._progress_manager.get().is_running:
                return {"success": False, "error": "Task already running"}
            self._stop_event.clear()

            settings = self._load_user_settings()
            source_dir = settings.get("organize_source") or os.path.expanduser("~/Downloads")
            _base_target = settings.get("organize_target") or os.path.expanduser("~/Organized")
            # Create a timestamped subfolder: YY.MM.DD-AgentOrganized
            _ts = datetime.now().strftime("%y.%m.%d")
            target_dir = str(Path(_base_target) / f"{_ts}-AgentOrganized")

            def _task() -> None:
                def _callback(step: str, percent: int) -> None:
                    self._progress_manager.update(percent, step, "file_organizer", is_running=True)
                    if self._app is not None:
                        self._app.push_log(f"[文件整理] {step}")
                    self._push_js_progress(percent, step, is_running=True)
                    self._push_js_log(f"[文件整理] {step}")

                try:
                    run_file_organizer(source_dir, target_dir, _callback, self._stop_event,
                                       confirm_callback=self._request_confirmation)
                    self._progress_manager.update(100, "文件整理完成", "file_organizer", is_running=False)
                    self._push_js_progress(100, "文件整理完成", is_running=False)
                    if self._app is not None:
                        self._app.push_log("[文件整理] 任务完成")
                except Exception as exc:
                    logger.exception("start_file_organizer task error")
                    self._progress_manager.update(
                        self._progress_manager.get().percent, "任务出错", "file_organizer", is_running=False
                    )
                    self._push_js_log(f"[文件整理] 错误：{exc}")
                    self._push_js_progress(0, "任务出错", is_running=False)

            thread = threading.Thread(target=_task, daemon=True)
            thread.start()
            return {"success": True, "task_name": "file_organizer"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("start_file_organizer unexpected error")
            return {"success": False, "error": str(exc)}

    def start_smart_installer(self) -> dict:
        """Start the smart installer task in a background thread.

        Opens a file dialog for the user to select an installer package,
        then launches it with UAC elevation and monitors installation progress.

        Returns:
            {"success": True, "task_name": "smart_installer"} on success,
            {"success": False, "error": "..."} if already running, user cancelled, or on exception.
        """
        try:
            if self._progress_manager.get().is_running:
                return {"success": False, "error": "Task already running"}

            # Let user pick the installer file first
            settings = self._load_user_settings()
            installer_default_dir = settings.get("installer_default_dir") or os.path.expanduser("~/Downloads")
            logger.info("start_smart_installer: opening file dialog, initial_dir=%s", installer_default_dir)

            if self._main_win is None:
                return {"success": False, "error": "主窗口未初始化"}

            file_result = self._main_win.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=installer_default_dir,
                allow_multiple=False,
                file_types=("安装包 (*.exe;*.msi)", "所有文件 (*.*)"),
            )
            if not file_result or len(file_result) == 0:
                logger.info("start_smart_installer: user cancelled file dialog")
                return {"success": False, "error": "用户取消了文件选择"}

            package_path = file_result[0]
            logger.info("start_smart_installer: selected package=%s", package_path)

            if not Path(package_path).exists():
                logger.warning("start_smart_installer: package file does not exist: %s", package_path)
                return {"success": False, "error": "安装包文件不存在，请重新选择"}

            self._stop_event.clear()

            def _task() -> None:
                def _callback(step: str, percent: int) -> None:
                    self._progress_manager.update(percent, step, "smart_installer", is_running=True)
                    if self._app is not None:
                        self._app.push_log(f"[智能安装] {step}")
                    self._push_js_progress(percent, step, is_running=True)
                    self._push_js_log(f"[智能安装] {step}")

                try:
                    run_software_installer(package_path, _callback, self._stop_event, initial_dir=installer_default_dir, detection_cache=self._detection_cache)
                    self._progress_manager.update(100, "智能安装完成", "smart_installer", is_running=False)
                    self._push_js_progress(100, "智能安装完成", is_running=False)
                    if self._app is not None:
                        self._app.push_log("[智能安装] 任务完成")
                except Exception as exc:
                    logger.exception("start_smart_installer task error")
                    self._progress_manager.update(
                        self._progress_manager.get().percent, "任务出错", "smart_installer", is_running=False
                    )
                    self._push_js_log(f"[智能安装] 错误：{exc}")
                    self._push_js_progress(0, "任务出错", is_running=False)

            thread = threading.Thread(target=_task, daemon=True)
            thread.start()
            return {"success": True, "task_name": "smart_installer"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("start_smart_installer unexpected error")
            return {"success": False, "error": str(exc)}

    def stop_task(self) -> None:
        """Signal the running task to stop and mark progress as not running."""
        self._stop_event.set()
        self._progress_manager.update(
            self._progress_manager.get().percent,
            "已停止",
            self._progress_manager.get().task_name,
            is_running=False,
        )
        logger.info("stop_task called; stop_event set")

    def chat_with_agent(self, message: str) -> dict:
        """Receive a user message and process it asynchronously via ChatAgent.

        Immediately returns {"success": True} without blocking the PyWebView main thread.
        The actual processing happens in a background thread.

        Args:
            message: User's natural language message string.

        Returns:
            {"success": True} on successful dispatch,
            {"success": False, "error": "..."} on exception.
        """
        try:
            agent = self._get_or_create_chat_agent()
            thread = threading.Thread(
                target=agent.handle_message,
                args=(message,),
                daemon=True,
            )
            thread.start()
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat_with_agent unexpected error")
            return {"success": False, "error": str(exc)}

    def clear_chat_context(self) -> dict:
        """Clear the ChatAgent's conversation context.

        Returns:
            {"success": True}
        """
        try:
            agent = self._get_or_create_chat_agent()
            agent.clear_context()
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("clear_chat_context unexpected error")
            return {"success": False, "error": str(exc)}

    def _get_or_create_chat_agent(self) -> ChatAgent:
        """Lazily initialize and return the ChatAgent instance."""
        if self._chat_agent is None:
            push_fn = self._app.push_chat_message if self._app is not None else lambda r, c: None
            llm_client = LLMClient()
            self._chat_agent = ChatAgent(
                llm_client=llm_client,
                progress_manager=self._progress_manager,
                stop_event=self._stop_event,
                push_fn=push_fn,
            )
        return self._chat_agent

    def get_progress(self) -> dict:
        """Return the current TaskProgress as a JSON-serializable dict."""
        return dataclasses.asdict(self._progress_manager.get())

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def minimize_to_ball(self) -> None:
        """Hide the main window and show the floating ball.

        Lazy creation: if the ball window has never been created, create it now.
        If it already exists, show() it (unless already shown).
        """
        if self._main_win is not None:
            self._main_win.hide()
        if self._ball_win is None:
            # First call: lazily create the floating ball window
            self._ball_win = webview.create_window(
                title="",
                url="frontend/floating.html",
                js_api=self,
                width=80,
                height=80,
                resizable=False,
                frameless=True,
                on_top=True,
                transparent=True,
                easy_drag=False,
            )
            self._ball_is_shown = True
        else:
            self._ball_win.show()
            self._ball_is_shown = True
        logger.debug("minimize_to_ball: main hidden, ball shown")

    def restore_main_window(self) -> None:
        """Hide the floating ball and show the main window."""
        if self._ball_win is not None:
            self._ball_win.hide()
            self._ball_is_shown = False
        if self._main_win is not None:
            self._main_win.show()
        logger.debug("restore_main_window: ball hidden, main shown")

    def move_ball_window(self, x: int, y: int) -> None:
        """Move the floating ball window to the given screen coordinates."""
        if self._ball_win is not None:
            self._ball_win.move(x, y)

    # ------------------------------------------------------------------
    # Settings API
    # ------------------------------------------------------------------

    def get_default_paths(self) -> dict:
        """返回当前用户配置的默认路径。

        Returns:
            {"organize_source": str, "organize_target": str, "installer_default_dir": str}
            异常时返回 {"success": False, "error": str}
        """
        try:
            settings = self._load_user_settings()
            return {
                "organize_source": settings.get("organize_source", _DEFAULT_ORGANIZE_SOURCE),
                "organize_target": settings.get("organize_target", _DEFAULT_ORGANIZE_TARGET),
                "installer_default_dir": settings.get("installer_default_dir", _DEFAULT_INSTALLER_DIR),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("get_default_paths error: %s", exc)
            return {"success": False, "error": str(exc)}

    def save_default_paths(self, organize_source: str, organize_target: str, installer_default_dir: str) -> dict:
        """将三个路径持久化到 config/user_settings.json。

        Returns:
            {"success": True}
            异常时返回 {"success": False, "error": str}
        """
        try:
            self._save_user_settings(UserSettings(
                organize_source=organize_source,
                organize_target=organize_target,
                installer_default_dir=installer_default_dir,
            ))
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            logger.error("save_default_paths error: %s", exc)
            return {"success": False, "error": str(exc)}

    def resolve_confirmation(self, confirm_id: str, answer: bool) -> dict:
        """前端确认按钮回调：将用户的是/否答案写入等待中的 Event。

        Args:
            confirm_id: 与 _pending_confirmations 中的 key 对应的 ID。
            answer: True = 是，False = 否。

        Returns:
            {"success": True}
        """
        event_and_result = self._pending_confirmations.get(confirm_id)
        if event_and_result is not None:
            event_and_result[1][0] = answer
            event_and_result[0].set()
        return {"success": True}

    def open_folder_dialog(self) -> dict:
        """调用系统原生文件夹选择对话框。

        Returns:
            {"path": "<selected_path>"} 或取消时 {"path": ""}
        """
        if self._main_win is None:
            logger.warning("open_folder_dialog: main window not initialized")
            return {"path": ""}
        try:
            result = self._main_win.create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                return {"path": result[0]}
            return {"path": ""}
        except Exception as exc:  # noqa: BLE001
            logger.error("open_folder_dialog error: %s", exc)
            return {"path": ""}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _push_js_progress(self, percent: int, status_text: str, is_running: bool) -> None:
        """Push a progress update directly to the main window via evaluate_js."""
        if self._main_win is None:
            return
        try:
            is_running_js = str(is_running).lower()
            safe_status = json.dumps(status_text)
            self._main_win.evaluate_js(
                f"updateProgress({percent}, {safe_status}, {is_running_js})"
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_push_js_progress evaluate_js failed: %s", exc)

    def _request_confirmation(self, message: str, timeout: float = 300.0) -> bool:
        """向前端推送一条带是/否按钮的确认消息，阻塞等待用户响应。

        通过 appendChatMessage('system', ...) 推送到对话窗口，
        同时通过 appendLog(...) 推送到执行日志。
        前端点击按钮后调用 resolve_confirmation()，解除阻塞。

        Args:
            message: 要显示的确认消息（支持 **bold** 标记）。
            timeout: 等待超时秒数，超时默认返回 False。

        Returns:
            True = 用户选择"是"，False = 用户选择"否"或超时。
        """
        confirm_id = uuid.uuid4().hex
        event = threading.Event()
        result: list[bool] = [False]
        self._pending_confirmations[confirm_id] = (event, result)

        # Push to chat window with inline yes/no buttons
        payload = json.dumps({"type": "confirm", "id": confirm_id, "message": message})
        if self._main_win is not None:
            try:
                self._main_win.evaluate_js(f"appendConfirmMessage({payload})")
            except Exception as exc:
                logger.debug("_request_confirmation evaluate_js failed: %s", exc)
        # Also push to log
        self._push_js_log(f"⚠️ {message}")

        answered = event.wait(timeout=timeout)
        self._pending_confirmations.pop(confirm_id, None)
        if not answered:
            logger.warning("_request_confirmation: 等待用户响应超时（%.0fs），默认返回 False", timeout)
            return False
        return result[0]

    def _push_js_log(self, message: str) -> None:
        """Push a log message directly to the main window via evaluate_js."""
        if self._main_win is None:
            return
        try:
            safe_msg = json.dumps(message)
            self._main_win.evaluate_js(f"appendLog({safe_msg})")
        except Exception as exc:  # noqa: BLE001
            logger.debug("_push_js_log evaluate_js failed: %s", exc)

    def _get_setting(self, key: str, default: str = "") -> str:
        """Read a dot-separated key from config/settings.yaml."""
        try:
            import yaml
            config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
            with open(config_path, encoding="utf-8") as f:
                settings = yaml.safe_load(f) or {}
            keys = key.split(".")
            val = settings
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    val = None
                if val is None:
                    return default
            return str(val) if val else default
        except Exception:  # noqa: BLE001
            return default

    def _load_user_settings(self) -> UserSettings:
        """读取 user_settings.json，损坏或不存在时返回默认值字典。"""
        defaults: UserSettings = {
            "organize_source": _DEFAULT_ORGANIZE_SOURCE,
            "organize_target": _DEFAULT_ORGANIZE_TARGET,
            "installer_default_dir": _DEFAULT_INSTALLER_DIR,
        }
        if not _USER_SETTINGS_PATH.exists():
            return defaults
        try:
            with open(_USER_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults for any missing keys
            return {**defaults, **data}
        except Exception as exc:  # noqa: BLE001
            logger.warning("_load_user_settings: failed to parse %s: %s", _USER_SETTINGS_PATH, exc)
            return defaults

    def _save_user_settings(self, data: UserSettings) -> None:
        """将 data 写入 user_settings.json，文件不存在时创建。"""
        _USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_SETTINGS_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))


class PyWebViewApp:
    """管理主窗口与悬浮球窗口生命周期的应用类。

    负责创建 PyWebView 窗口、订阅进度推送、启动截图线程。
    """

    def __init__(
        self,
        progress_manager: ProgressManager,
        queue_manager: QueueManager,
        overlay_drawer: OverlayDrawer,
    ) -> None:
        self._progress_manager = progress_manager
        self._queue_manager = queue_manager
        self._overlay_drawer = overlay_drawer
        self._main_win: webview.Window | None = None
        self._ball_win: webview.Window | None = None
        self.api = PythonAPI(progress_manager, queue_manager)
        self.api._app = self  # back-reference for push_log

    def overlay_drawer_set_show_boxes(
        self, show: bool, cache: DetectionCache
    ) -> None:
        """将 DetectionCache 绑定到 OverlayDrawer 并控制是否绘制检测框。

        由 PythonAPI.set_show_boxes() 调用，确保 OverlayDrawer 在每帧
        截图后从缓存读取最新检测结果并绘制到图像上。

        Args:
            show: True 表示启用检测框绘制，False 表示禁用。
            cache: 线程安全的检测结果缓存实例。
        """
        self._overlay_drawer.set_detection_cache(cache if show else None, show)
        logger.info("PyWebViewApp.overlay_drawer_set_show_boxes: show=%s", show)

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Create windows, wire subscriptions, and start the PyWebView event loop."""
        api = self.api

        def _on_main_closed() -> None:
            """Called when the main window is closed by the user.

            Hides the floating ball (if present) and terminates the process
            cleanly so no orphaned windows remain.
            """
            if self._ball_win is not None:
                try:
                    self._ball_win.hide()
                except Exception as e:  # noqa: BLE001
                    logger.warning("Failed to hide ball window on main close: %s", e)
            sys.exit(0)

        self._main_win = webview.create_window(
            title="AutoAgent Desktop",
            url="frontend/dist/index.html",
            js_api=api,
            width=1280,
            height=800,
            resizable=True,
            frameless=False,
        )
        self._main_win.events.closed += _on_main_closed

        api.set_windows(self._main_win, None)

        # Subscribe progress updates → push to both windows
        self._progress_manager.subscribe(self.push_progress)

        # Start overlay drawer → push frames to main window
        self._overlay_drawer.start(self.push_frame)

        webview.start(self._on_webview_started)

    def _on_webview_started(self) -> None:
        """Called by PyWebView after the event loop is ready."""
        pass

    # ------------------------------------------------------------------
    # Push helpers
    # ------------------------------------------------------------------

    def push_frame(self, b64: str) -> None:
        """Push a base64 JPEG frame to the main window if it is visible."""
        if self._main_win is None:
            return
        try:
            if not getattr(self._main_win, "shown", True):
                return
            self._main_win.evaluate_js(f"updateFrame('{b64}')")
        except Exception as exc:  # noqa: BLE001
            logger.debug("push_frame evaluate_js failed: %s", exc)

    def push_progress(self, progress: TaskProgress) -> None:
        """Push a progress update to both windows if they are visible."""
        is_running_js = str(progress.is_running).lower()
        safe_status = json.dumps(progress.status_text)
        js_call = (
            f"updateProgress({progress.percent}, "
            f"{safe_status}, "
            f"{is_running_js})"
        )

        if self._main_win is not None and getattr(self._main_win, "shown", True):
            try:
                self._main_win.evaluate_js(js_call)
            except Exception as exc:  # noqa: BLE001
                logger.debug("push_progress main_win evaluate_js failed: %s", exc)

        if self._ball_win is not None and getattr(self._ball_win, "shown", True):
            try:
                self._ball_win.evaluate_js(js_call)
            except Exception as exc:  # noqa: BLE001
                logger.debug("push_progress ball_win evaluate_js failed: %s", exc)

    def push_log(self, message: str) -> None:
        """Push a log message to the main window, serialized via json.dumps for XSS safety."""
        if self._main_win is None:
            return
        try:
            if not getattr(self._main_win, "shown", True):
                return
            safe_msg = json.dumps(message)
            self._main_win.evaluate_js(f"appendLog({safe_msg})")
        except Exception as exc:  # noqa: BLE001
            logger.debug("push_log evaluate_js failed: %s", exc)

    def push_chat_message(self, role: str, content: str) -> None:
        """Push a chat message to the main window via evaluate_js.

        Calls the frontend appendChatMessage(role, content) function.
        Parameters are serialized via json.dumps to prevent XSS.
        Exceptions from evaluate_js are caught and logged at DEBUG level.

        Args:
            role: Message role ("user" | "assistant" | "system").
            content: Message content string.
        """
        if self._main_win is None:
            return
        try:
            safe_role = json.dumps(role)
            safe_content = json.dumps(content)
            self._main_win.evaluate_js(f"appendChatMessage({safe_role}, {safe_content})")
        except Exception as exc:  # noqa: BLE001
            logger.debug("push_chat_message evaluate_js failed: %s", exc)
