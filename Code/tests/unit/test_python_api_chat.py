"""单元测试：PythonAPI 聊天扩展方法。

测试 chat_with_agent 立即返回、后台线程启动，以及 clear_chat_context 行为。
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from gui.app import PythonAPI
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager


@pytest.fixture
def progress_manager() -> ProgressManager:
    return ProgressManager()


@pytest.fixture
def queue_manager() -> MagicMock:
    return MagicMock(spec=QueueManager)


@pytest.fixture
def api(progress_manager: ProgressManager, queue_manager: MagicMock) -> PythonAPI:
    return PythonAPI(progress_manager, queue_manager)


@pytest.fixture
def api_with_app(api: PythonAPI) -> PythonAPI:
    """PythonAPI with a mock _app attached."""
    mock_app = MagicMock()
    mock_app.push_chat_message = MagicMock()
    api._app = mock_app
    return api


# ---------------------------------------------------------------------------
# chat_with_agent
# ---------------------------------------------------------------------------

class TestChatWithAgent:
    def test_returns_success_immediately(self, api_with_app: PythonAPI) -> None:
        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance
            mock_agent_instance.handle_message = MagicMock()

            result = api_with_app.chat_with_agent("你好")

        assert result == {"success": True}

    def test_starts_background_thread(self, api_with_app: PythonAPI) -> None:
        handle_called = threading.Event()

        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance

            def _handle(msg: str) -> None:
                handle_called.set()

            mock_agent_instance.handle_message.side_effect = _handle
            api_with_app.chat_with_agent("测试消息")
            # Should return before handle_message completes
            assert handle_called.wait(timeout=2.0), "handle_message was not called in background thread"

    def test_does_not_block_caller(self, api_with_app: PythonAPI) -> None:
        """chat_with_agent should return before handle_message finishes."""
        start = time.monotonic()

        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance
            mock_agent_instance.handle_message.side_effect = lambda m: time.sleep(0.5)

            result = api_with_app.chat_with_agent("慢消息")

        elapsed = time.monotonic() - start
        assert result == {"success": True}
        assert elapsed < 0.4, f"chat_with_agent blocked for {elapsed:.2f}s"

    def test_returns_error_on_exception(self, api_with_app: PythonAPI) -> None:
        with patch("gui.app.LLMClient", side_effect=Exception("init failed")):
            result = api_with_app.chat_with_agent("test")
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# clear_chat_context
# ---------------------------------------------------------------------------

class TestClearChatContext:
    def test_returns_success(self, api_with_app: PythonAPI) -> None:
        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance

            result = api_with_app.clear_chat_context()

        assert result == {"success": True}

    def test_calls_clear_context_on_agent(self, api_with_app: PythonAPI) -> None:
        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance

            api_with_app.clear_chat_context()

        mock_agent_instance.clear_context.assert_called_once()

    def test_reuses_existing_agent(self, api_with_app: PythonAPI) -> None:
        """Calling clear_chat_context twice should reuse the same ChatAgent."""
        with patch("gui.app.LLMClient"), \
             patch("gui.app.ChatAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            MockAgent.return_value = mock_agent_instance

            api_with_app.clear_chat_context()
            api_with_app.clear_chat_context()

        # ChatAgent constructor called only once
        assert MockAgent.call_count == 1
