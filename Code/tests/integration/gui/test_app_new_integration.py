"""
Integration tests for PyWebViewApp and PythonAPI initialization flow.

Validates: Requirements 1.3, 1.4, 13.1, 13.3
"""
from __future__ import annotations

import sys
import types
import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level stubs — must happen before any gui.* import
# ---------------------------------------------------------------------------

def _stub_modules() -> None:
    """Stub out modules that fail to import in the test environment."""
    if "cv2" not in sys.modules or not isinstance(sys.modules["cv2"], MagicMock):
        mock_cv2 = MagicMock()
        sys.modules["cv2"] = mock_cv2
        sys.modules["cv2.dnn"] = MagicMock()
        sys.modules["cv2.typing"] = MagicMock()

    for name in (
        "automation.vision_box_drawer",
        "automation.object_detector",
        "automation.file_organizer",
        "automation.software_installer",
    ):
        if name not in sys.modules:
            stub = MagicMock()
            stub.DetectionCache = MagicMock
            stub.VisionOverlayController = MagicMock
            stub.BoundingBoxDict = dict
            stub.run_file_organizer = MagicMock()
            stub.run_software_installer = MagicMock()
            sys.modules[name] = stub

    for name in ("mss", "pyautogui", "pyperclip", "pynput",
                 "pynput.keyboard", "pynput.mouse", "pywinauto",
                 "win32api", "win32con", "win32gui",
                 "dashscope", "langchain", "langchain.agents",
                 "langchain.tools", "langchain_community", "chromadb",
                 "yaml", "openai"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()


_stub_modules()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_window() -> MagicMock:
    win = MagicMock()
    win.events = MagicMock()
    win.events.closed = MagicMock()
    win.events.closed.__iadd__ = MagicMock(return_value=None)
    win.evaluate_js = MagicMock(return_value=None)
    win.shown = True
    return win


def _make_mock_webview_module() -> types.ModuleType:
    mod = types.ModuleType("webview")
    mod.create_window = MagicMock(return_value=_make_mock_window())
    mod.start = MagicMock(return_value=None)
    mod.OPEN_DIALOG = 10
    mod.FOLDER_DIALOG = 20
    mod.Window = MagicMock
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_webview():
    """Patch `webview` in sys.modules and reload gui.app."""
    fake_webview = _make_mock_webview_module()

    for mod_name in list(sys.modules.keys()):
        if mod_name == "gui.app":
            del sys.modules[mod_name]

    with patch.dict(sys.modules, {"webview": fake_webview}):
        yield fake_webview

    for mod_name in list(sys.modules.keys()):
        if mod_name == "gui.app":
            del sys.modules[mod_name]


@pytest.fixture()
def app_and_window(mock_webview):
    """Instantiate PyWebViewApp with mocked deps; return (app, mock_window)."""
    from gui.app import PyWebViewApp
    from gui.progress_manager import ProgressManager
    from ui.queue_manager import QueueManager

    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    overlay_drawer = MagicMock()

    app = PyWebViewApp(progress_manager, queue_manager, overlay_drawer)

    mock_window = _make_mock_window()
    app._main_win = mock_window
    app.api.set_windows(mock_window, None)

    return app, mock_window


# ---------------------------------------------------------------------------
# Tests: Initialization flow
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPyWebViewAppInitialization:
    """Verify PyWebViewApp and PythonAPI complete initialization flow."""

    def test_api_is_python_api_instance(self, mock_webview):
        """PyWebViewApp.api must be an instance of gui.app.PythonAPI."""
        from gui.app import PyWebViewApp, PythonAPI
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        app = PyWebViewApp(ProgressManager(), QueueManager(), MagicMock())
        assert isinstance(app.api, PythonAPI)

    def test_run_creates_window(self, mock_webview):
        """webview.create_window must be called during run()."""
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        app = PyWebViewApp(ProgressManager(), QueueManager(), MagicMock())
        mock_webview.start = MagicMock(return_value=None)

        app.run()

        mock_webview.create_window.assert_called_once()

    def test_api_back_reference_points_to_app(self, mock_webview):
        """api._app must point back to the PyWebViewApp instance."""
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        app = PyWebViewApp(ProgressManager(), QueueManager(), MagicMock())
        assert app.api._app is app

    def test_progress_manager_subscribe_called_on_run(self, mock_webview):
        """run() must subscribe push_progress to the progress manager."""
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        pm = ProgressManager()
        overlay_drawer = MagicMock()
        app = PyWebViewApp(pm, QueueManager(), overlay_drawer)
        mock_webview.start = MagicMock(return_value=None)

        app.run()

        assert app.push_progress in pm._subscribers

    def test_overlay_drawer_start_called_on_run(self, mock_webview):
        """run() must call overlay_drawer.start(push_frame)."""
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        overlay_drawer = MagicMock()
        app = PyWebViewApp(ProgressManager(), QueueManager(), overlay_drawer)
        mock_webview.start = MagicMock(return_value=None)

        app.run()

        overlay_drawer.start.assert_called_once_with(app.push_frame)


# ---------------------------------------------------------------------------
# Tests: push_frame → evaluate_js("updateFrame(...)") call chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPushFrameCallChain:
    """Verify push_frame → evaluate_js('updateFrame(...)') call chain."""

    def test_push_frame_calls_update_frame_js(self, app_and_window):
        app, mock_window = app_and_window
        app.push_frame("abc123==")
        mock_window.evaluate_js.assert_called_once()
        js_call = mock_window.evaluate_js.call_args[0][0]
        assert js_call.startswith("updateFrame(")

    def test_push_frame_embeds_b64_data(self, app_and_window):
        app, mock_window = app_and_window
        b64 = "dGVzdGRhdGE="
        app.push_frame(b64)
        js_call = mock_window.evaluate_js.call_args[0][0]
        assert b64 in js_call

    def test_push_frame_noop_when_window_is_none(self, mock_webview):
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        app = PyWebViewApp(ProgressManager(), QueueManager(), MagicMock())
        app._main_win = None
        app.push_frame("somedata")  # must not raise

    def test_push_frame_multiple_calls_each_produce_one_evaluate_js(self, app_and_window):
        app, mock_window = app_and_window
        frames = ["frame1", "frame2", "frame3"]
        for f in frames:
            app.push_frame(f)
        assert mock_window.evaluate_js.call_count == len(frames)
        for i, f in enumerate(frames):
            js_call = mock_window.evaluate_js.call_args_list[i][0][0]
            assert "updateFrame(" in js_call
            assert f in js_call


# ---------------------------------------------------------------------------
# Tests: push_chat_message → evaluate_js("appendChatMessage(...)") call chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPushChatMessageCallChain:
    """Verify push_chat_message → evaluate_js('appendChatMessage(...)') call chain."""

    def test_push_chat_message_calls_append_chat_message_js(self, app_and_window):
        app, mock_window = app_and_window
        app.push_chat_message("assistant", "Hello!")
        mock_window.evaluate_js.assert_called_once()
        js_call = mock_window.evaluate_js.call_args[0][0]
        assert js_call.startswith("appendChatMessage(")

    def test_push_chat_message_json_serializes_role_and_content(self, app_and_window):
        app, mock_window = app_and_window
        role = "user"
        content = 'Say "hello" & <world>'
        app.push_chat_message(role, content)
        js_call = mock_window.evaluate_js.call_args[0][0]
        assert json.dumps(role) in js_call
        assert json.dumps(content) in js_call

    def test_push_chat_message_noop_when_window_is_none(self, mock_webview):
        from gui.app import PyWebViewApp
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        app = PyWebViewApp(ProgressManager(), QueueManager(), MagicMock())
        app._main_win = None
        app.push_chat_message("user", "test")  # must not raise

    def test_push_chat_message_all_standard_roles(self, app_and_window):
        app, mock_window = app_and_window
        for role in ("user", "assistant", "system"):
            mock_window.evaluate_js.reset_mock()
            app.push_chat_message(role, f"message from {role}")
            mock_window.evaluate_js.assert_called_once()
            js_call = mock_window.evaluate_js.call_args[0][0]
            assert "appendChatMessage(" in js_call
