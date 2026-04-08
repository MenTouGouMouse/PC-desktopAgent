"""单元测试：ChatAgent 对话代理。

测试消息追加、意图路由、上下文截断、并发拒绝等核心行为。
"""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from decision.llm_client import LLMCallError
from gui.chat_agent import ChatAgent, IntentResult
from gui.progress_manager import ProgressManager, TaskProgress


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def progress_manager() -> ProgressManager:
    return ProgressManager()


@pytest.fixture
def stop_event() -> threading.Event:
    return threading.Event()


@pytest.fixture
def push_calls() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def agent(progress_manager: ProgressManager, stop_event: threading.Event, push_calls: list) -> ChatAgent:
    mock_llm = MagicMock()
    with patch("os.environ.get", return_value="fake-key"):
        ag = ChatAgent(
            llm_client=mock_llm,
            progress_manager=progress_manager,
            stop_event=stop_event,
            push_fn=lambda role, content: push_calls.append((role, content)),
        )
    return ag


def _make_intent_response(intent: str, params: dict | None = None, clarification: str | None = None) -> dict:
    payload: dict = {"intent": intent, "params": params or {}}
    if clarification is not None:
        payload["clarification"] = clarification
    return {"role": "assistant", "content": json.dumps(payload)}


# ---------------------------------------------------------------------------
# clear_context
# ---------------------------------------------------------------------------

class TestClearContext:
    def test_clears_context(self, agent: ChatAgent) -> None:
        agent._context = [{"role": "user", "content": "hello"}]
        agent.clear_context()
        assert agent._context == []

    def test_clear_empty_context_is_safe(self, agent: ChatAgent) -> None:
        agent.clear_context()
        assert agent._context == []


# ---------------------------------------------------------------------------
# _truncate_context_if_needed
# ---------------------------------------------------------------------------

class TestTruncateContext:
    def test_no_truncation_when_under_limit(self, agent: ChatAgent, push_calls: list) -> None:
        agent._context = [{"role": "user", "content": "short"}]
        agent._truncate_context_if_needed()
        assert len(agent._context) == 1
        assert not push_calls

    def test_truncates_when_over_limit(self, agent: ChatAgent, push_calls: list) -> None:
        long_msg = "x" * 900
        agent._context = [{"role": "user", "content": long_msg} for _ in range(15)]
        agent._truncate_context_if_needed()
        assert len(agent._context) == 10
        assert any("截断" in content for _, content in push_calls)

    def test_keeps_most_recent_messages(self, agent: ChatAgent) -> None:
        long_msg = "x" * 900
        msgs = [{"role": "user", "content": f"{i}" + long_msg} for i in range(15)]
        agent._context = msgs
        agent._truncate_context_if_needed()
        assert agent._context == msgs[-10:]


# ---------------------------------------------------------------------------
# handle_message — context append
# ---------------------------------------------------------------------------

class TestHandleMessageContextAppend:
    def test_appends_user_message(self, agent: ChatAgent) -> None:
        agent._llm_client.chat.return_value = _make_intent_response("unknown", clarification="无法处理")
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("你好")
        assert any(m["content"] == "你好" for m in agent._context)

    def test_context_grows_by_one(self, agent: ChatAgent) -> None:
        agent._llm_client.chat.return_value = _make_intent_response("unknown", clarification="无法处理")
        initial_len = len(agent._context)
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("测试消息")
        assert len(agent._context) == initial_len + 1


# ---------------------------------------------------------------------------
# handle_message — routing
# ---------------------------------------------------------------------------

class TestHandleMessageRouting:
    def test_clarification_pushes_assistant_message(
        self, agent: ChatAgent, push_calls: list
    ) -> None:
        agent._llm_client.chat.return_value = _make_intent_response(
            "file_organize", clarification="请提供源目录"
        )
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("整理文件")
        assert any(role == "assistant" and "源目录" in content for role, content in push_calls)

    def test_clarification_does_not_start_task(
        self, agent: ChatAgent, progress_manager: ProgressManager
    ) -> None:
        agent._llm_client.chat.return_value = _make_intent_response(
            "file_organize", clarification="请提供源目录"
        )
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("整理文件")
        assert not progress_manager.get().is_running

    def test_unknown_intent_pushes_assistant_message(
        self, agent: ChatAgent, push_calls: list
    ) -> None:
        agent._llm_client.chat.return_value = _make_intent_response(
            "unknown", clarification="无法处理"
        )
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("随便说说")
        assert any(role == "assistant" for role, _ in push_calls)

    def test_file_organize_starts_background_thread(
        self, agent: ChatAgent, progress_manager: ProgressManager
    ) -> None:
        agent._llm_client.chat.return_value = _make_intent_response(
            "file_organize", params={"source": "/src", "target": "/dst"}
        )
        with patch("os.environ.get", return_value="fake-key"), \
             patch("automation.file_organizer.run_file_organizer") as mock_run:
            mock_run.side_effect = lambda cb, ev: None
            agent.handle_message("整理文件")
            time.sleep(0.1)
        # 任务已启动（is_running 可能已完成，但 mock 被调用）
        mock_run.assert_called_once()

    def test_software_install_starts_background_thread(
        self, agent: ChatAgent
    ) -> None:
        agent._llm_client.chat.return_value = _make_intent_response(
            "software_install", params={"package_path": "/setup.exe"}
        )
        with patch("os.environ.get", return_value="fake-key"), \
             patch("automation.software_installer.run_software_installer") as mock_run:
            mock_run.side_effect = lambda cb, ev: None
            agent.handle_message("安装软件")
            time.sleep(0.1)
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# handle_message — concurrent rejection
# ---------------------------------------------------------------------------

class TestConcurrentRejection:
    def test_rejects_new_task_when_running(
        self, agent: ChatAgent, progress_manager: ProgressManager, push_calls: list
    ) -> None:
        # 设置 is_running=True
        progress_manager.update(50, "运行中", "file_organize", is_running=True)
        agent._llm_client.chat.return_value = _make_intent_response(
            "file_organize", params={"source": "/src", "target": "/dst"}
        )
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("再整理一次")
        assert any("正在执行" in content for _, content in push_calls)

    def test_rejects_install_when_running(
        self, agent: ChatAgent, progress_manager: ProgressManager, push_calls: list
    ) -> None:
        progress_manager.update(50, "运行中", "software_install", is_running=True)
        agent._llm_client.chat.return_value = _make_intent_response(
            "software_install", params={"package_path": "/setup.exe"}
        )
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("再安装一次")
        assert any("正在执行" in content for _, content in push_calls)


# ---------------------------------------------------------------------------
# handle_message — missing API key
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_pushes_system_log_when_no_api_key(
        self, agent: ChatAgent, push_calls: list
    ) -> None:
        with patch("os.environ.get", return_value=None):
            agent.handle_message("测试")
        assert any("API 密钥" in content for _, content in push_calls)


# ---------------------------------------------------------------------------
# handle_message — LLMCallError propagation
# ---------------------------------------------------------------------------

class TestLLMCallError:
    def test_llm_error_pushes_system_log(
        self, agent: ChatAgent, push_calls: list
    ) -> None:
        agent._llm_client.chat.side_effect = LLMCallError("API 失败", status_code=500)
        with patch("os.environ.get", return_value="fake-key"):
            agent.handle_message("测试")
        assert any(role == "system" for role, _ in push_calls)
