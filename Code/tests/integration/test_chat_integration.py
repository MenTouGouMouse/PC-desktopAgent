"""集成测试：chat-automation-interface 端到端链路验证。

测试 ChatAgent → 自动化模块 → push_fn 完整链路，以及 PythonAPI 桥接。
所有外部 I/O（DashScope API、evaluate_js）均被 mock。
"""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from gui.chat_agent import ChatAgent, IntentResult
from gui.progress_manager import ProgressManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent_response(intent: str, params: dict | None = None) -> dict:
    payload = {"intent": intent, "params": params or {}}
    return {"role": "assistant", "content": json.dumps(payload)}


def _wait_for(condition_fn, timeout: float = 3.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Integration: file organizer
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_chat_agent_file_organizer_integration() -> None:
    """端到端验证文件整理任务的进度推送和日志推送。

    验证：需求 5.1, 5.2, 5.3
    """
    progress_manager = ProgressManager()
    stop_event = threading.Event()
    push_calls: list[tuple[str, str]] = []

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_intent_response(
        "file_organize", {"source": "/src", "target": "/dst", "filters": []}
    )

    with patch("os.environ.get", return_value="fake-key"):
        agent = ChatAgent(
            llm_client=mock_llm,
            progress_manager=progress_manager,
            stop_event=stop_event,
            push_fn=lambda role, content: push_calls.append((role, content)),
        )

    with patch("os.environ.get", return_value="fake-key"), \
         patch("automation.file_organizer.time.sleep"):  # speed up
        agent.handle_message("整理文件")

    # Wait for background thread to complete
    assert _wait_for(lambda: not progress_manager.get().is_running, timeout=5.0), \
        "File organizer task did not complete in time"

    # Verify system logs were pushed
    system_logs = [content for role, content in push_calls if role == "system"]
    assert len(system_logs) > 0, "No system logs were pushed"

    # Verify completion message was pushed
    assistant_msgs = [content for role, content in push_calls if role == "assistant"]
    assert any("完成" in msg for msg in assistant_msgs), "No completion message pushed"

    # Verify progress reached 100%
    assert progress_manager.get().percent == 100


# ---------------------------------------------------------------------------
# Integration: software installer
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_chat_agent_software_installer_integration() -> None:
    """端到端验证安装任务的进度推送和日志推送。

    验证：需求 6.1, 6.2, 6.3
    """
    progress_manager = ProgressManager()
    stop_event = threading.Event()
    push_calls: list[tuple[str, str]] = []

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_intent_response(
        "software_install", {"package_path": "/setup.exe"}
    )

    with patch("os.environ.get", return_value="fake-key"):
        agent = ChatAgent(
            llm_client=mock_llm,
            progress_manager=progress_manager,
            stop_event=stop_event,
            push_fn=lambda role, content: push_calls.append((role, content)),
        )

    with patch("os.environ.get", return_value="fake-key"), \
         patch("automation.software_installer.time.sleep"):  # speed up
        agent.handle_message("安装软件")

    assert _wait_for(lambda: not progress_manager.get().is_running, timeout=5.0), \
        "Software installer task did not complete in time"

    system_logs = [content for role, content in push_calls if role == "system"]
    assert len(system_logs) > 0

    assistant_msgs = [content for role, content in push_calls if role == "assistant"]
    assert any("完成" in msg for msg in assistant_msgs)

    assert progress_manager.get().percent == 100


# ---------------------------------------------------------------------------
# Integration: PythonAPI → ChatAgent → push_chat_message bridge
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_python_api_chat_bridge() -> None:
    """验证 PythonAPI.chat_with_agent → ChatAgent → push_chat_message 完整链路。

    验证：需求 8.1, 8.4
    """
    from gui.app import PythonAPI
    from gui.progress_manager import ProgressManager
    from ui.queue_manager import QueueManager

    progress_manager = ProgressManager()
    queue_manager = MagicMock(spec=QueueManager)

    api = PythonAPI(progress_manager, queue_manager)

    # Set up mock app with push_chat_message
    mock_app = MagicMock()
    push_calls: list[tuple[str, str]] = []
    mock_app.push_chat_message.side_effect = lambda role, content: push_calls.append((role, content))
    api._app = mock_app

    # Mock LLMClient and ChatAgent to avoid real API calls
    with patch("gui.app.LLMClient") as MockLLMClient, \
         patch("gui.app.ChatAgent") as MockChatAgent:

        mock_llm_instance = MagicMock()
        MockLLMClient.return_value = mock_llm_instance

        # Simulate ChatAgent.handle_message calling push_fn
        def _fake_handle(message: str) -> None:
            # Simulate the agent pushing a response
            api._app.push_chat_message("assistant", f"收到：{message}")

        mock_agent_instance = MagicMock()
        mock_agent_instance.handle_message.side_effect = _fake_handle
        MockChatAgent.return_value = mock_agent_instance

        # Call chat_with_agent
        result = api.chat_with_agent("测试消息")

    # Should return success immediately
    assert result == {"success": True}

    # Wait for background thread
    assert _wait_for(lambda: len(push_calls) > 0, timeout=3.0), \
        "push_chat_message was never called"

    assert any("收到" in content for _, content in push_calls)
