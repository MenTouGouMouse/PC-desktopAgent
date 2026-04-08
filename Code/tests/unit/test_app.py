"""
Unit tests for gui.app (PythonAPI and PyWebViewApp).

Validates: Requirements 1.1-1.7, 4.1-4.8, 7.1-7.4, 8.1-8.4, 9.5, 11.3
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out the 'webview' module so tests run without pywebview installed
# ---------------------------------------------------------------------------
_webview_stub = types.ModuleType("webview")
_webview_stub.Window = MagicMock  # type: ignore[attr-defined]
_webview_stub.create_window = MagicMock()  # type: ignore[attr-defined]
_webview_stub.start = MagicMock()  # type: ignore[attr-defined]
_webview_stub.OPEN_DIALOG = 10  # type: ignore[attr-defined]
_webview_stub.FOLDER_DIALOG = 20  # type: ignore[attr-defined]
sys.modules.setdefault("webview", _webview_stub)

from gui.app import PythonAPI, PyWebViewApp  # noqa: E402
from gui.progress_manager import ProgressManager, TaskProgress  # noqa: E402
from ui.queue_manager import QueueManager  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_window(shown: bool = True) -> MagicMock:
    """Return a mock webview.Window with controllable .shown attribute."""
    win = MagicMock()
    win.shown = shown
    return win


def _make_api(is_running: bool = False) -> tuple[PythonAPI, ProgressManager]:
    """Return a PythonAPI instance with a real ProgressManager."""
    pm = ProgressManager()
    if is_running:
        pm.update(50, "running", task_name="file_organizer", is_running=True)
    qm = QueueManager()
    api = PythonAPI(pm, qm)
    return api, pm


# ---------------------------------------------------------------------------
# PythonAPI — window management
# ---------------------------------------------------------------------------


class TestMinimizeToBall:
    def test_hides_main_and_shows_ball(self) -> None:
        api, _ = _make_api()
        main_win = _make_window()
        ball_win = _make_window()
        api.set_windows(main_win, ball_win)

        api.minimize_to_ball()

        main_win.hide.assert_called_once()
        ball_win.show.assert_called_once()

    def test_does_not_raise_when_windows_not_set(self) -> None:
        api, _ = _make_api()
        api.minimize_to_ball()  # should not raise


class TestRestoreMainWindow:
    def test_hides_ball_and_shows_main(self) -> None:
        api, _ = _make_api()
        main_win = _make_window()
        ball_win = _make_window()
        api.set_windows(main_win, ball_win)

        api.restore_main_window()

        ball_win.hide.assert_called_once()
        main_win.show.assert_called_once()

    def test_does_not_raise_when_windows_not_set(self) -> None:
        api, _ = _make_api()
        api.restore_main_window()  # should not raise


# ---------------------------------------------------------------------------
# PythonAPI — stop_task
# ---------------------------------------------------------------------------


class TestStopTask:
    def test_stop_task_sets_is_running_false(self) -> None:
        api, pm = _make_api(is_running=True)
        assert pm.get().is_running is True

        api.stop_task()

        assert pm.get().is_running is False

    def test_stop_task_sets_stop_event(self) -> None:
        api, _ = _make_api()
        assert not api._stop_event.is_set()

        api.stop_task()

        assert api._stop_event.is_set()


# ---------------------------------------------------------------------------
# PythonAPI — start_file_organizer / start_smart_installer
# ---------------------------------------------------------------------------


class TestStartTaskAlreadyRunning:
    def test_start_file_organizer_returns_failure_when_running(self) -> None:
        api, _ = _make_api(is_running=True)
        result = api.start_file_organizer()

        assert result["success"] is False
        assert "error" in result
        assert result["error"]  # non-empty

    def test_start_smart_installer_returns_failure_when_running(self) -> None:
        api, _ = _make_api(is_running=True)
        result = api.start_smart_installer()

        assert result["success"] is False
        assert "error" in result
        assert result["error"]

    def test_start_file_organizer_succeeds_when_not_running(self) -> None:
        api, _ = _make_api(is_running=False)
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            result = api.start_file_organizer()

        assert result["success"] is True
        assert result["task_name"] == "file_organizer"
        mock_thread.start.assert_called_once()

    def test_start_smart_installer_succeeds_when_not_running(self) -> None:
        api, _ = _make_api(is_running=False)
        mock_window = _make_window()
        mock_window.create_file_dialog.return_value = [r"C:\tools\setup.exe"]
        api._main_win = mock_window

        with patch("pathlib.Path.exists", return_value=True), \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            result = api.start_smart_installer()

        assert result["success"] is True
        assert result["task_name"] == "smart_installer"
        mock_thread.start.assert_called_once()


# ---------------------------------------------------------------------------
# PythonAPI — start_smart_installer pre-flight file existence check (Req 2.4)
# ---------------------------------------------------------------------------


class TestStartSmartInstallerPreflight:
    """Validates the pre-flight file existence check added in Task 3.3.

    Validates: Requirements 2.4
    """

    def test_preflight_missing_file_returns_chinese_error_without_spawning_thread(
        self,
    ) -> None:
        """**Validates: Requirements 2.4**

        When the selected file does not exist on the filesystem,
        start_smart_installer must return a Chinese error message immediately
        and must NOT spawn a background thread.
        """
        api, _ = _make_api(is_running=False)
        mock_window = _make_window()
        mock_window.create_file_dialog.return_value = [r"C:\nonexistent\setup.exe"]
        api._main_win = mock_window

        with patch("pathlib.Path.exists", return_value=False), \
             patch("threading.Thread") as mock_thread_cls:
            result = api.start_smart_installer()

        assert result["success"] is False
        assert "安装包文件不存在" in result.get("error", ""), (
            f"Expected Chinese error '安装包文件不存在' but got: {result}"
        )
        mock_thread_cls.assert_not_called()

    def test_preflight_existing_file_spawns_thread(self) -> None:
        """**Validates: Requirements 2.4**

        When the selected file exists, start_smart_installer proceeds normally
        and spawns the background thread.
        """
        api, _ = _make_api(is_running=False)
        mock_window = _make_window()
        mock_window.create_file_dialog.return_value = [r"C:\tools\setup.exe"]
        api._main_win = mock_window

        with patch("pathlib.Path.exists", return_value=True), \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            result = api.start_smart_installer()

        assert result["success"] is True
        mock_thread.start.assert_called_once()


class TestStartTaskExceptionSafety:
    def test_start_file_organizer_returns_failure_on_exception(self) -> None:
        api, pm = _make_api()
        # Force an exception by making progress_manager.get() raise
        pm.get = MagicMock(side_effect=RuntimeError("boom"))

        result = api.start_file_organizer()

        assert result["success"] is False
        assert "boom" in result["error"]

    def test_start_smart_installer_returns_failure_on_exception(self) -> None:
        api, pm = _make_api()
        pm.get = MagicMock(side_effect=RuntimeError("crash"))

        result = api.start_smart_installer()

        assert result["success"] is False
        assert "crash" in result["error"]


# ---------------------------------------------------------------------------
# PythonAPI — get_progress
# ---------------------------------------------------------------------------


class TestGetProgress:
    def test_returns_dict_with_all_fields(self) -> None:
        api, pm = _make_api()
        pm.update(42, "halfway", task_name="file_organizer", is_running=True)

        result = api.get_progress()

        assert result["percent"] == 42
        assert result["status_text"] == "halfway"
        assert result["task_name"] == "file_organizer"
        assert result["is_running"] is True

    def test_returns_json_serializable_dict(self) -> None:
        api, _ = _make_api()
        result = api.get_progress()
        # Should not raise
        json.dumps(result)


# ---------------------------------------------------------------------------
# PyWebViewApp — push_log XSS safety
# ---------------------------------------------------------------------------


class TestPushLog:
    def _make_app_with_visible_main(self) -> tuple[PyWebViewApp, MagicMock]:
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)
        main_win = _make_window(shown=True)
        ball_win = _make_window(shown=False)
        app._main_win = main_win
        app._ball_win = ball_win
        app.api.set_windows(main_win, ball_win)
        return app, main_win

    def test_push_log_uses_json_dumps(self) -> None:
        app, main_win = self._make_app_with_visible_main()
        message = 'hello "world" <script>alert(1)</script>'

        app.push_log(message)

        call_args = main_win.evaluate_js.call_args[0][0]
        # The injected JS must contain the json.dumps-serialized message
        expected_safe = json.dumps(message)
        assert expected_safe in call_args

    def test_push_log_xss_special_chars(self) -> None:
        app, main_win = self._make_app_with_visible_main()
        # Strings that would break naive string interpolation
        for dangerous in [
            "'); alert(1); //",
            '<script>evil()</script>',
            '\\n\\r\\t',
            '"double" and \'single\'',
        ]:
            main_win.reset_mock()
            app.push_log(dangerous)
            call_args = main_win.evaluate_js.call_args[0][0]
            assert json.dumps(dangerous) in call_args

    def test_push_log_skips_when_main_hidden(self) -> None:
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)
        main_win = _make_window(shown=False)
        app._main_win = main_win

        app.push_log("hello")

        main_win.evaluate_js.assert_not_called()

    def test_push_log_catches_evaluate_js_exception(self) -> None:
        app, main_win = self._make_app_with_visible_main()
        main_win.evaluate_js.side_effect = RuntimeError("js error")

        # Should not raise
        app.push_log("test message")


# ---------------------------------------------------------------------------
# PyWebViewApp — push_progress visibility guard
# ---------------------------------------------------------------------------


class TestPushProgress:
    def _make_app(
        self,
        main_shown: bool = True,
        ball_shown: bool = True,
    ) -> tuple[PyWebViewApp, MagicMock, MagicMock]:
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)
        main_win = _make_window(shown=main_shown)
        ball_win = _make_window(shown=ball_shown)
        app._main_win = main_win
        app._ball_win = ball_win
        return app, main_win, ball_win

    def test_pushes_to_both_when_both_visible(self) -> None:
        app, main_win, ball_win = self._make_app(main_shown=True, ball_shown=True)
        progress = TaskProgress(percent=50, status_text="mid", task_name="t", is_running=True)

        app.push_progress(progress)

        main_win.evaluate_js.assert_called_once()
        ball_win.evaluate_js.assert_called_once()

    def test_skips_main_when_hidden(self) -> None:
        app, main_win, ball_win = self._make_app(main_shown=False, ball_shown=True)
        progress = TaskProgress(percent=50, status_text="mid", task_name="t", is_running=True)

        app.push_progress(progress)

        main_win.evaluate_js.assert_not_called()
        ball_win.evaluate_js.assert_called_once()

    def test_skips_ball_when_hidden(self) -> None:
        app, main_win, ball_win = self._make_app(main_shown=True, ball_shown=False)
        progress = TaskProgress(percent=50, status_text="mid", task_name="t", is_running=True)

        app.push_progress(progress)

        main_win.evaluate_js.assert_called_once()
        ball_win.evaluate_js.assert_not_called()

    def test_skips_both_when_both_hidden(self) -> None:
        app, main_win, ball_win = self._make_app(main_shown=False, ball_shown=False)
        progress = TaskProgress(percent=50, status_text="mid", task_name="t", is_running=True)

        app.push_progress(progress)

        main_win.evaluate_js.assert_not_called()
        ball_win.evaluate_js.assert_not_called()

    def test_catches_evaluate_js_exception_and_continues(self) -> None:
        app, main_win, ball_win = self._make_app(main_shown=True, ball_shown=True)
        main_win.evaluate_js.side_effect = RuntimeError("main error")
        progress = TaskProgress(percent=10, status_text="x", task_name="t", is_running=False)

        # Should not raise; ball_win should still be called
        app.push_progress(progress)

        ball_win.evaluate_js.assert_called_once()

    def test_js_call_contains_correct_values(self) -> None:
        app, main_win, _ = self._make_app(main_shown=True, ball_shown=False)
        progress = TaskProgress(percent=75, status_text="running", task_name="t", is_running=True)

        app.push_progress(progress)

        call_arg: str = main_win.evaluate_js.call_args[0][0]
        assert "75" in call_arg
        assert "running" in call_arg
        assert "true" in call_arg
