"""
tests/unit/test_app_push_js_safe.py

Unit tests for Bug 4 fix: WebView2 evaluate_js exception safety.

Validates: Requirements 2.9, 2.10, 2.11
Property 4: _push_js_progress and _push_js_log must not propagate exceptions
            from evaluate_js (e.g. ObjectDisposedException after window disposal).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gui.app import PythonAPI
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager


@pytest.fixture()
def api() -> PythonAPI:
    """Return a PythonAPI instance with a mock main window."""
    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    instance = PythonAPI(progress_manager, queue_manager)

    mock_win = MagicMock()
    instance._main_win = mock_win
    return instance


def test_push_js_progress_survives_evaluate_js_exception(api: PythonAPI) -> None:
    """_push_js_progress must not propagate any exception from evaluate_js.

    Validates: Requirements 2.9, 2.10
    """
    api._main_win.evaluate_js.side_effect = Exception("ObjectDisposedException: window disposed")

    # Must not raise
    api._push_js_progress(50, "测试进度", True)
    api._push_js_progress(100, "智能安装完成", False)


def test_push_js_log_survives_evaluate_js_exception(api: PythonAPI) -> None:
    """_push_js_log must not propagate any exception from evaluate_js.

    Validates: Requirements 2.9, 2.11
    """
    api._main_win.evaluate_js.side_effect = Exception("ObjectDisposedException: window disposed")

    # Must not raise
    api._push_js_log("[智能安装] 任务完成")
    api._push_js_log("任意日志消息")


def test_push_js_progress_logs_debug_on_exception(api: PythonAPI, caplog: pytest.LogCaptureFixture) -> None:
    """_push_js_progress should log at DEBUG level when evaluate_js raises."""
    import logging

    api._main_win.evaluate_js.side_effect = Exception("disposed")

    with caplog.at_level(logging.DEBUG, logger="gui.app"):
        api._push_js_progress(50, "test", True)

    assert any("_push_js_progress" in r.message for r in caplog.records)


def test_push_js_log_logs_debug_on_exception(api: PythonAPI, caplog: pytest.LogCaptureFixture) -> None:
    """_push_js_log should log at DEBUG level when evaluate_js raises."""
    import logging

    api._main_win.evaluate_js.side_effect = Exception("disposed")

    with caplog.at_level(logging.DEBUG, logger="gui.app"):
        api._push_js_log("test message")

    assert any("_push_js_log" in r.message for r in caplog.records)


def test_push_js_progress_no_exception_when_main_win_none() -> None:
    """_push_js_progress must silently return when _main_win is None."""
    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    instance = PythonAPI(progress_manager, queue_manager)
    # _main_win is None by default

    # Must not raise
    instance._push_js_progress(0, "no window", False)


def test_push_js_log_no_exception_when_main_win_none() -> None:
    """_push_js_log must silently return when _main_win is None."""
    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    instance = PythonAPI(progress_manager, queue_manager)

    # Must not raise
    instance._push_js_log("no window")
