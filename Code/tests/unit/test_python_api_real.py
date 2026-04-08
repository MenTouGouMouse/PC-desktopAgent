"""
单元测试：gui.app PythonAPI 真实集成（移除模拟代码验证）。
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from gui.app import PythonAPI
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager


def make_api() -> PythonAPI:
    """Create a PythonAPI instance with mocked dependencies."""
    pm = ProgressManager()
    qm = MagicMock(spec=QueueManager)
    api = PythonAPI(pm, qm)
    # Mock the main window
    api._main_win = MagicMock()
    return api


class TestPythonAPINoSimulationCode:
    def test_simulate_task_method_does_not_exist(self):
        """_simulate_task 方法不存在（smoke test）。"""
        api = make_api()
        assert not hasattr(api, "_simulate_task"), "_simulate_task should not exist"

    def test_task_steps_constant_does_not_exist(self):
        """_TASK_STEPS 模块级常量不存在。"""
        import gui.app as app_module
        assert not hasattr(app_module, "_TASK_STEPS"), "_TASK_STEPS should not exist"

    def test_step_delay_constant_does_not_exist(self):
        """_STEP_DELAY 模块级常量不存在。"""
        import gui.app as app_module
        assert not hasattr(app_module, "_STEP_DELAY"), "_STEP_DELAY should not exist"

    def test_file_organizer_steps_not_imported(self):
        """file_organizer.STEPS 不被引用。"""
        import automation.file_organizer as fo
        assert not hasattr(fo, "STEPS"), "file_organizer.STEPS should not exist"

    def test_software_installer_steps_not_imported(self):
        """software_installer.STEPS 不被引用。"""
        import automation.software_installer as si
        assert not hasattr(si, "STEPS"), "software_installer.STEPS should not exist"


class TestPythonAPICallbackIntegration:
    def test_callback_calls_progress_manager_update(self):
        """Property 7: callback wrapper 调用 ProgressManager.update。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        api._main_win = MagicMock()

        updates: list[tuple] = []
        original_update = pm.update

        def tracking_update(percent, status_text, task_name="", is_running=True):
            updates.append((percent, status_text, task_name, is_running))
            original_update(percent, status_text, task_name, is_running)

        pm.update = tracking_update

        with patch("gui.app.run_file_organizer") as mock_fo:
            def fake_run(source, target, cb, stop_event, file_filters=None):
                cb("测试步骤", 50)

            mock_fo.side_effect = fake_run

            api.start_file_organizer()
            time.sleep(0.1)  # Let background thread run

        # ProgressManager.update should have been called with the step info
        assert any(u[0] == 50 and u[2] == "file_organizer" for u in updates), (
            f"Expected update with percent=50, task_name='file_organizer', got: {updates}"
        )

    def test_callback_calls_evaluate_js_append_log(self):
        """Property 7: callback wrapper 调用 evaluate_js appendLog。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        mock_win = MagicMock()
        api._main_win = mock_win

        with patch("gui.app.run_file_organizer") as mock_fo:
            def fake_run(source, target, cb, stop_event, file_filters=None):
                cb("测试步骤", 50)

            mock_fo.side_effect = fake_run

            api.start_file_organizer()
            time.sleep(0.1)

        # evaluate_js should have been called with appendLog
        calls = [str(c) for c in mock_win.evaluate_js.call_args_list]
        assert any("appendLog" in c for c in calls), (
            f"evaluate_js should have been called with appendLog, calls: {calls}"
        )

    def test_exception_sets_is_running_false(self):
        """Property 8: 异常时 is_running 必须重置为 False。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        api._main_win = MagicMock()

        with patch("gui.app.run_file_organizer") as mock_fo:
            mock_fo.side_effect = RuntimeError("模拟异常")

            api.start_file_organizer()
            time.sleep(0.2)  # Let background thread run and handle exception

        assert not pm.get().is_running, "is_running should be False after exception"

    def test_exception_pushes_error_log(self):
        """异常时通过 appendLog 推送错误信息。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        mock_win = MagicMock()
        api._main_win = mock_win

        with patch("gui.app.run_file_organizer") as mock_fo:
            mock_fo.side_effect = RuntimeError("测试错误消息")

            api.start_file_organizer()
            time.sleep(0.2)

        calls = [str(c) for c in mock_win.evaluate_js.call_args_list]
        assert any("appendLog" in c for c in calls), (
            "evaluate_js should have been called with appendLog for error"
        )

    def test_start_file_organizer_returns_success(self):
        """start_file_organizer 返回 success=True。"""
        api = make_api()

        with patch("gui.app.run_file_organizer"):
            result = api.start_file_organizer()

        assert result["success"] is True
        assert result["task_name"] == "file_organizer"

    def test_start_smart_installer_returns_success(self):
        """start_smart_installer 返回 success=True。"""
        api = make_api()

        with patch("gui.app.run_software_installer"):
            result = api.start_smart_installer()

        assert result["success"] is True
        assert result["task_name"] == "smart_installer"

    def test_already_running_returns_error(self):
        """任务已在运行时返回 error。"""
        api = make_api()
        api._progress_manager.update(50, "running", "file_organizer", is_running=True)

        result = api.start_file_organizer()

        assert result["success"] is False
        assert "already running" in result["error"]
