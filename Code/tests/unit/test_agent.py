"""单元测试：decision/agent.py - DesktopAgent。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

import decision.agent  # noqa: F401
from decision.llm_client import LLMCallError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm_client() -> MagicMock:
    """返回一个模拟的 LLMClient，chat() 默认返回无工具调用的成功响应。"""
    client = MagicMock()
    client.chat.return_value = {"role": "assistant", "content": "任务完成", "tool_calls": None}
    return client


@pytest.fixture()
def mock_tools() -> list[MagicMock]:
    """返回四个模拟的 LangChain Tool 对象。"""
    tool_names = ["detect_gui_elements", "click", "type_text", "open_application"]
    tools = []
    for name in tool_names:
        t = MagicMock()
        t.name = name
        t.description = f"Mock tool: {name}"
        t.func = MagicMock(return_value="ok")
        tools.append(t)
    return tools


@pytest.fixture()
def agent(mock_llm_client, mock_tools):
    """构建 DesktopAgent。"""
    from decision.agent import DesktopAgent
    return DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)


@pytest.fixture()
def mock_memory_system() -> MagicMock:
    """返回一个模拟的 MemorySystem。"""
    ms = MagicMock()
    ms.search_similar.return_value = []
    ms.store.return_value = None
    return ms


@pytest.fixture()
def agent_with_memory(mock_llm_client, mock_tools, mock_memory_system):
    """构建带 MemorySystem 的 DesktopAgent。"""
    from decision.agent import DesktopAgent
    ag = DesktopAgent(
        llm_client=mock_llm_client,
        tools=mock_tools,
        memory_system=mock_memory_system,
    )
    return ag, mock_memory_system


# ---------------------------------------------------------------------------
# DesktopAgent.__init__
# ---------------------------------------------------------------------------


class TestDesktopAgentInit:
    def test_agent_stores_llm_client(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        assert ag._llm_client is mock_llm_client

    def test_agent_stores_tools(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        assert len(ag._tools) == 4

    def test_agent_default_max_iterations(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        assert ag._max_iterations == 50

    def test_agent_custom_max_iterations(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools, max_iterations=20)
        assert ag._max_iterations == 20

    def test_agent_default_memory_system_is_none(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        assert ag._memory_system is None

    def test_agent_accepts_memory_system(self, mock_llm_client, mock_tools, mock_memory_system):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools, memory_system=mock_memory_system)
        assert ag._memory_system is mock_memory_system

    def test_tool_map_built_from_tools(self, mock_llm_client, mock_tools):
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        for t in mock_tools:
            assert t.name in ag._tool_map


# ---------------------------------------------------------------------------
# DesktopAgent.run
# ---------------------------------------------------------------------------


class TestDesktopAgentRun:
    def test_run_returns_string_on_success(self, agent, mock_llm_client):
        """run() 成功时应返回字符串。"""
        mock_llm_client.chat.return_value = {"role": "assistant", "content": "任务执行完成", "tool_calls": None}
        result = agent.run("打开记事本")
        assert isinstance(result, str)
        assert result == "任务执行完成"

    def test_run_calls_llm_with_instruction(self, agent, mock_llm_client):
        """run() 应将 instruction 传递给 llm_client.chat()。"""
        mock_llm_client.chat.return_value = {"role": "assistant", "content": "ok", "tool_calls": None}
        agent.run("打开微信")
        mock_llm_client.chat.assert_called()
        messages = mock_llm_client.chat.call_args[0][0]
        # 用户消息应包含指令
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any("打开微信" in m["content"] for m in user_msgs)

    def test_run_catches_llm_call_error_and_returns_string(self, agent, mock_llm_client):
        """run() 捕获 LLMCallError 时必须返回包含错误描述的字符串，不抛出异常。"""
        mock_llm_client.chat.side_effect = LLMCallError("API 调用失败", status_code=429)
        result = agent.run("执行某任务")
        assert isinstance(result, str)
        assert "任务执行失败" in result

    def test_run_llm_error_does_not_call_tool_funcs(self, agent, mock_llm_client, mock_tools):
        """run() 在 LLMCallError 时不应调用任何工具的 func。"""
        mock_llm_client.chat.side_effect = LLMCallError("失败", status_code=500)
        agent.run("某指令")
        for tool in mock_tools:
            tool.func.assert_not_called()

    def test_run_catches_generic_exception_and_returns_string(self, agent, mock_llm_client):
        """run() 捕获通用异常时也应返回错误字符串，不向上抛出。"""
        mock_llm_client.chat.side_effect = RuntimeError("意外崩溃")
        result = agent.run("某指令")
        assert isinstance(result, str)
        assert "任务执行失败" in result

    def test_run_error_string_contains_error_description(self, agent, mock_llm_client):
        """错误返回字符串应包含原始错误信息。"""
        error_msg = "DashScope 服务不可用"
        mock_llm_client.chat.side_effect = LLMCallError(error_msg, status_code=503)
        result = agent.run("某指令")
        assert error_msg in result

    def test_run_handles_empty_content(self, agent, mock_llm_client):
        """LLM 返回空 content 时，run() 应仍返回字符串。"""
        mock_llm_client.chat.return_value = {"role": "assistant", "content": "", "tool_calls": None}
        result = agent.run("指令")
        assert isinstance(result, str)

    def test_run_executes_tool_call(self, agent, mock_llm_client, mock_tools):
        """当 LLM 返回 tool_calls 时，run() 应执行对应工具。"""
        # 第一次调用返回 tool_call，第二次返回最终结果
        mock_llm_client.chat.side_effect = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "click", "arguments": '{"x": 100, "y": 200}'},
                    }
                ],
            },
            {"role": "assistant", "content": "点击完成", "tool_calls": None},
        ]
        result = agent.run("点击按钮")
        # click tool 的 func 应被调用
        click_tool = next(t for t in mock_tools if t.name == "click")
        click_tool.func.assert_called_once()
        assert isinstance(result, str)

    def test_run_stops_after_max_iterations(self, mock_llm_client, mock_tools):
        """达到 max_iterations 时，run() 应停止并返回字符串。"""
        from decision.agent import DesktopAgent
        # 始终返回 tool_calls，触发无限循环
        mock_llm_client.chat.return_value = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "click", "arguments": '{"x": 1, "y": 1}'}}
            ],
        }
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools, max_iterations=3)
        result = ag.run("无限循环指令")
        assert isinstance(result, str)
        assert "最大迭代次数" in result


# ---------------------------------------------------------------------------
# DesktopAgent Memory Integration
# ---------------------------------------------------------------------------


class TestDesktopAgentMemoryIntegration:
    def test_init_accepts_optional_memory_system(self, mock_llm_client, mock_tools, mock_memory_system):
        """DesktopAgent.__init__ 应接受可选的 memory_system 参数。"""
        from decision.agent import DesktopAgent
        ag = DesktopAgent(
            llm_client=mock_llm_client,
            tools=mock_tools,
            memory_system=mock_memory_system,
        )
        assert ag._memory_system is mock_memory_system

    def test_init_without_memory_system_defaults_to_none(self, mock_llm_client, mock_tools):
        """不传 memory_system 时，_memory_system 应为 None。"""
        from decision.agent import DesktopAgent
        ag = DesktopAgent(llm_client=mock_llm_client, tools=mock_tools)
        assert ag._memory_system is None

    def test_run_calls_search_similar_before_llm(self, agent_with_memory):
        """run() 应在 llm_client.chat 之前调用 memory.search_similar()。"""
        ag, ms = agent_with_memory
        call_order: list[str] = []

        ms.search_similar.side_effect = lambda *a, **kw: call_order.append("search") or []
        ag._llm_client.chat.side_effect = lambda *a, **kw: call_order.append("chat") or {
            "role": "assistant", "content": "ok", "tool_calls": None
        }

        ag.run("打开记事本")

        assert "search" in call_order
        assert "chat" in call_order
        assert call_order.index("search") < call_order.index("chat")

    def test_run_calls_search_similar_with_instruction(self, agent_with_memory):
        """run() 应以用户指令作为参数调用 memory.search_similar()。"""
        ag, ms = agent_with_memory
        ag.run("打开微信")
        ms.search_similar.assert_called_once_with("打开微信")

    def test_run_stores_success_record_after_execution(self, agent_with_memory):
        """run() 成功后应调用 memory.store() 持久化记录。"""
        ag, ms = agent_with_memory
        ag._llm_client.chat.return_value = {"role": "assistant", "content": "任务完成", "tool_calls": None}
        ag.run("打开记事本")
        ms.store.assert_called_once()

    def test_run_stores_record_with_success_result(self, agent_with_memory):
        """成功执行后存储的 OperationRecord.result 应为 'success'。"""
        ag, ms = agent_with_memory
        ag._llm_client.chat.return_value = {"role": "assistant", "content": "完成", "tool_calls": None}
        ag.run("打开记事本")

        stored_record = ms.store.call_args[0][0]
        assert stored_record.result == "success"

    def test_run_stores_record_with_failure_result_on_llm_error(self, agent_with_memory):
        """LLMCallError 时存储的 OperationRecord.result 应为 'failure'。"""
        ag, ms = agent_with_memory
        ag._llm_client.chat.side_effect = LLMCallError("API 失败", status_code=500)
        ag.run("打开记事本")

        stored_record = ms.store.call_args[0][0]
        assert stored_record.result == "failure"

    def test_run_stores_record_with_failure_result_on_generic_error(self, agent_with_memory):
        """通用异常时存储的 OperationRecord.result 应为 'failure'。"""
        ag, ms = agent_with_memory
        ag._llm_client.chat.side_effect = RuntimeError("崩溃")
        ag.run("打开记事本")

        stored_record = ms.store.call_args[0][0]
        assert stored_record.result == "failure"

    def test_run_stores_record_with_agent_run_action_type(self, agent_with_memory):
        """存储的 OperationRecord.action_type 应为 'agent_run'。"""
        ag, ms = agent_with_memory
        ag.run("打开记事本")

        stored_record = ms.store.call_args[0][0]
        assert stored_record.action_type == "agent_run"

    def test_run_stores_record_with_instruction_as_description(self, agent_with_memory):
        """存储的 OperationRecord.description 应为原始用户指令。"""
        ag, ms = agent_with_memory
        ag.run("打开微信发消息")

        stored_record = ms.store.call_args[0][0]
        assert stored_record.description == "打开微信发消息"

    def test_run_stores_record_with_iso_timestamp(self, agent_with_memory):
        """存储的 OperationRecord.timestamp 应为 ISO 8601 格式。"""
        ag, ms = agent_with_memory
        ag.run("打开记事本")

        stored_record = ms.store.call_args[0][0]
        datetime.fromisoformat(stored_record.timestamp)

    def test_run_enriches_input_with_history_context(self, agent_with_memory):
        """当 search_similar 返回结果时，LLM 应收到包含历史上下文的消息。"""
        from decision.memory import OperationRecord as OR

        ag, ms = agent_with_memory
        ms.search_similar.return_value = [
            OR(
                timestamp="2024-01-01T00:00:00",
                action_type="agent_run",
                description="打开记事本",
                coordinates=None,
                result="success",
                metadata={},
            )
        ]
        ag.run("打开记事本写日记")

        messages = ag._llm_client.chat.call_args[0][0]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any("相似历史操作参考" in m["content"] for m in user_msgs)
        assert any("打开记事本写日记" in m["content"] for m in user_msgs)

    def test_run_passes_plain_instruction_when_no_history(self, agent_with_memory):
        """search_similar 返回空列表时，LLM 应收到原始指令（不含历史上下文）。"""
        ag, ms = agent_with_memory
        ms.search_similar.return_value = []
        ag.run("打开记事本")

        messages = ag._llm_client.chat.call_args[0][0]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any(m["content"] == "打开记事本" for m in user_msgs)

    def test_run_without_memory_system_does_not_raise(self, agent, mock_llm_client):
        """无 MemorySystem 时，run() 不应抛出异常。"""
        mock_llm_client.chat.return_value = {"role": "assistant", "content": "完成", "tool_calls": None}
        result = agent.run("打开记事本")
        assert result == "完成"

    def test_run_memory_search_failure_does_not_abort_execution(self, agent_with_memory):
        """memory.search_similar 抛出异常时，run() 应继续执行，不中断。"""
        ag, ms = agent_with_memory
        ms.search_similar.side_effect = RuntimeError("ChromaDB 不可用")
        ag._llm_client.chat.return_value = {"role": "assistant", "content": "完成", "tool_calls": None}

        result = ag.run("打开记事本")
        assert result == "完成"

    def test_run_memory_store_failure_does_not_affect_return_value(self, agent_with_memory):
        """memory.store 抛出异常时，run() 应仍返回正确结果，不中断。"""
        ag, ms = agent_with_memory
        ms.store.side_effect = RuntimeError("SQLite 写入失败")
        ag._llm_client.chat.return_value = {"role": "assistant", "content": "完成", "tool_calls": None}

        result = ag.run("打开记事本")
        assert result == "完成"
