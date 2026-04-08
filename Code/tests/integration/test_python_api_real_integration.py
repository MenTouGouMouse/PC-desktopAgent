"""
集成测试：PythonAPI → ProgressManager → evaluate_js 链路集成。
"""
from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from gui.app import PythonAPI
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager


@pytest.mark.integration
class TestPythonAPIRealIntegration:
    def test_callback_triggers_progress_manager_and_evaluate_js(self):
        """验证 callback 触发时 ProgressManager.update 和 evaluate_js 均被调用。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        mock_win = MagicMock()
        api._main_win = mock_win

        updates: list[tuple] = []
        original_update = pm.update

        def tracking_update(percent, status_text, task_name="", is_running=True):
            updates.append((percent, status_text, task_name, is_running))
            original_update(percent, status_text, task_name, is_running)

        pm.update = tracking_update

        with patch("gui.app.run_file_organizer") as mock_fo:
            def fake_run(source, target, cb, stop_event, file_filters=None):
                cb("步骤1", 33)
                cb("步骤2", 66)
                cb("步骤3", 100)

            mock_fo.side_effect = fake_run
            api.start_file_organizer()
            time.sleep(0.2)

        # ProgressManager.update called for each step
        step_updates = [u for u in updates if u[2] == "file_organizer" and u[3] is True]
        assert len(step_updates) >= 3

        # evaluate_js called with appendLog
        calls = [str(c) for c in mock_win.evaluate_js.call_args_list]
        assert any("appendLog" in c for c in calls)

    def test_task_completion_sets_is_running_false(self):
        """验证任务完成后 is_running=False。"""
        pm = ProgressManager()
        qm = MagicMock(spec=QueueManager)
        api = PythonAPI(pm, qm)
        api._main_win = MagicMock()

        with patch("gui.app.run_file_organizer") as mock_fo:
            mock_fo.return_value = None
            api.start_file_organizer()
            time.sleep(0.2)

        assert not pm.get().is_running
