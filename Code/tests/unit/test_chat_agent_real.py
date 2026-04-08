"""
单元测试：gui.chat_agent ChatAgent 真实集成。
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from gui.chat_agent import ChatAgent
from gui.progress_manager import ProgressManager


def make_agent() -> tuple[ChatAgent, list[tuple[str, str]]]:
    """Create a ChatAgent with mocked dependencies. Returns (agent, messages)."""
    pm = ProgressManager()
    stop_event = threading.Event()
    messages: list[tuple[str, str]] = []
    push_fn = lambda role, content: messages.append((role, content))
    llm_client = MagicMock()

    agent = ChatAgent(
        llm_client=llm_client,
        progress_manager=pm,
        stop_event=stop_event,
        push_fn=push_fn,
    )
    return agent, messages


class TestChatAgentFileOrganizerNullParams:
    def test_source_none_asks_user_not_calls_run(self):
        """source 为 None 时追问用户，不调用 run_file_organizer。"""
        agent, messages = make_agent()

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            agent._run_file_organizer({"source": None, "target": "/some/target"})

        # Should have pushed an assistant clarification message
        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1
        assert any("路径" in m for m in assistant_msgs)

    def test_target_none_asks_user_not_calls_run(self):
        """target 为 None 时追问用户，不调用 run_file_organizer。"""
        agent, messages = make_agent()

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            agent._run_file_organizer({"source": "/some/source", "target": None})
            mock_fo.assert_not_called()

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1

    def test_both_none_asks_user(self):
        """source 和 target 均为 None 时追问用户。"""
        agent, messages = make_agent()

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            agent._run_file_organizer({"source": None, "target": None})
            mock_fo.assert_not_called()

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1


class TestChatAgentSoftwareInstallerNullParams:
    def test_package_path_none_asks_user_not_calls_run(self):
        """package_path 为 None 时追问用户，不调用 run_software_installer。"""
        agent, messages = make_agent()

        with patch("automation.software_installer.run_software_installer") as mock_si:
            agent._run_software_installer({"package_path": None})
            mock_si.assert_not_called()

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1
        assert any("路径" in m or "安装包" in m for m in assistant_msgs)

    def test_missing_package_path_key_asks_user(self):
        """params 中缺少 package_path 键时追问用户。"""
        agent, messages = make_agent()

        with patch("automation.software_installer.run_software_installer") as mock_si:
            agent._run_software_installer({})
            mock_si.assert_not_called()

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1


class TestChatAgentCompletionMessages:
    def test_file_organizer_completion_contains_source_and_target(self, tmp_path):
        """Property 10: 完成消息包含 source 和 target 路径。"""
        agent, messages = make_agent()
        source = str(tmp_path / "source")
        target = str(tmp_path / "target")

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            mock_fo.return_value = None  # Simulate successful completion
            agent._run_file_organizer({"source": source, "target": target})

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1
        completion_msg = assistant_msgs[-1]
        assert source in completion_msg, f"source path not in completion message: {completion_msg}"
        assert target in completion_msg, f"target path not in completion message: {completion_msg}"

    def test_software_installer_completion_contains_package_path(self, tmp_path):
        """Property 10: 完成消息包含 package_path。"""
        agent, messages = make_agent()
        pkg = str(tmp_path / "installer.exe")

        with patch("automation.software_installer.run_software_installer") as mock_si:
            mock_si.return_value = None
            agent._run_software_installer({"package_path": pkg})

        assistant_msgs = [c for r, c in messages if r == "assistant"]
        assert len(assistant_msgs) >= 1
        completion_msg = assistant_msgs[-1]
        assert pkg in completion_msg, f"package_path not in completion message: {completion_msg}"


class TestChatAgentExceptionHandling:
    def test_file_organizer_exception_sets_is_running_false(self, tmp_path):
        """Property 8: 文件整理异常时 is_running 重置为 False。"""
        pm = ProgressManager()
        stop_event = threading.Event()
        messages: list[tuple[str, str]] = []
        agent = ChatAgent(
            llm_client=MagicMock(),
            progress_manager=pm,
            stop_event=stop_event,
            push_fn=lambda r, c: messages.append((r, c)),
        )

        source = str(tmp_path / "source")
        target = str(tmp_path / "target")

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            mock_fo.side_effect = RuntimeError("测试异常")
            agent._run_file_organizer({"source": source, "target": target})

        assert not pm.get().is_running, "is_running should be False after exception"

    def test_software_installer_exception_sets_is_running_false(self, tmp_path):
        """Property 8: 软件安装异常时 is_running 重置为 False。"""
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
            mock_si.side_effect = RuntimeError("安装异常")
            agent._run_software_installer({"package_path": "/fake/path.exe"})

        assert not pm.get().is_running, "is_running should be False after exception"

    def test_file_organizer_exception_pushes_error_message(self, tmp_path):
        """异常时通过 _push_fn 推送错误信息。"""
        agent, messages = make_agent()
        source = str(tmp_path / "source")
        target = str(tmp_path / "target")

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            mock_fo.side_effect = RuntimeError("具体错误信息")
            agent._run_file_organizer({"source": source, "target": target})

        system_msgs = [c for r, c in messages if r == "system"]
        assert any("错误" in m or "出错" in m for m in system_msgs)


class TestChatAgentParamPassthrough:
    def test_file_organizer_passes_filters_correctly(self, tmp_path):
        """Property 9: filters 参数正确透传给 run_file_organizer。"""
        agent, messages = make_agent()
        source = str(tmp_path / "source")
        target = str(tmp_path / "target")
        filters = [".jpg", ".png"]

        with patch("automation.file_organizer.run_file_organizer") as mock_fo:
            mock_fo.return_value = None
            agent._run_file_organizer({"source": source, "target": target, "filters": filters})

        mock_fo.assert_called_once()
        call_args = mock_fo.call_args
        # run_file_organizer(source, target, _cb, stop_event, filters)
        assert call_args[0][0] == source
        assert call_args[0][1] == target
        assert call_args[0][4] == filters

    def test_software_installer_passes_package_path_correctly(self, tmp_path):
        """Property 9: package_path 参数正确透传给 run_software_installer。"""
        agent, messages = make_agent()
        pkg = "/path/to/installer.exe"

        with patch("automation.software_installer.run_software_installer") as mock_si:
            mock_si.return_value = None
            agent._run_software_installer({"package_path": pkg})

        mock_si.assert_called_once()
        call_args = mock_si.call_args
        assert call_args[0][0] == pkg
