"""
集成测试：ChatAgent → run_software_installer → _push_fn 链路集成。
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from gui.chat_agent import ChatAgent
from gui.progress_manager import ProgressManager


@pytest.mark.integration
class TestChatAgentRealIntegration:
    def test_callback_triggers_push_fn_system(self):
        """验证 callback 触发时 _push_fn("system", ...) 被调用。"""
        pm = ProgressManager()
        stop_event = threading.Event()
        messages: list[tuple[str, str]] = []
        agent = ChatAgent(
            llm_client=MagicMock(),
            progress_manager=pm,
            stop_event=stop_event,
            push_fn=lambda r, c: messages.append((r, c)),
        )

        with patch("automation.software_installer.run_software_installer") as mock_si:
            def fake_run(pkg, cb, stop_event):
                cb("安装步骤1", 25)
                cb("安装步骤2", 50)

            mock_si.side_effect = fake_run
            agent._run_software_installer({"package_path": "/fake/installer.exe"})

        system_msgs = [c for r, c in messages if r == "system"]
        assert any("[软件安装]" in m for m in system_msgs)

    def test_completion_push_fn_contains_package_path(self):
        """验证完成后 _push_fn("assistant", ...) 包含 package_path。"""
        pm = ProgressManager()
        stop_event = threading.Event()
        messages: list[tuple[str, str]] = []
        agent = ChatAgent(
            llm_client=MagicMock(),
            progress_manager=pm,
            stop_event=stop_event,
            push_fn=lambda r, c: messages.append((r, c)),
        )

        pkg = "/path/to/my_installer.exe"

        with patch("automation.software_installer.run_software_installer") as mock_si:
            mock_si.return_value = None
            agent._run_software_installer({"package_path": pkg})

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1
        assert pkg in assistant_msgs[-1]
