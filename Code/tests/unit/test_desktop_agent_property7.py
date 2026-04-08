"""属性测试：decision/agent.py - Property 7: LLM 调用失败时不执行任何操作。

# Feature: cv-desktop-automation-agent, Property 7: LLM 调用失败时不执行任何操作
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from decision.agent import DesktopAgent
from decision.llm_client import LLMCallError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(llm_client: MagicMock) -> DesktopAgent:
    """构建 DesktopAgent，注入 mock LLMClient 和 mock Tools。"""
    tool_names = ["detect_gui_elements", "click", "type_text", "open_application"]
    tools = []
    for name in tool_names:
        t = MagicMock()
        t.name = name
        t.description = f"Mock tool: {name}"
        t.func = MagicMock(return_value="ok")
        tools.append(t)

    return DesktopAgent(llm_client=llm_client, tools=tools)


# ---------------------------------------------------------------------------
# Property 7: LLM 调用失败时不执行任何操作
# Validates: Requirements 4.7
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    instruction=st.text(min_size=1, max_size=200),
    error_message=st.text(min_size=1, max_size=200),
    status_code=st.sampled_from([0, 400, 429, 500, 503]),
    error_code=st.sampled_from(["", "RateLimit", "InvalidParameter", "ServiceUnavailable", "RetryExhausted"]),
)
def test_desktop_agent_run_llm_call_error_returns_error_string_no_action(
    instruction: str,
    error_message: str,
    status_code: int,
    error_code: str,
) -> None:
    """Property 7: 对任意导致 LLMClient.chat() 抛出 LLMCallError 的输入，
    DesktopAgent.run() 必须返回包含错误描述的字符串，且不调用任何 ActionEngine 方法。

    Validates: Requirements 4.7
    """
    # Arrange: mock LLMClient that always raises LLMCallError
    mock_llm_client = MagicMock()
    mock_llm_client.chat.side_effect = LLMCallError(
        error_message, code=error_code, status_code=status_code
    )

    # Mock ActionEngine methods to detect any unwanted calls
    mock_action_engine = MagicMock()

    with patch("execution.action_engine.ActionEngine", return_value=mock_action_engine):
        agent = _make_agent(mock_llm_client)

        # Act
        result = agent.run(instruction)

    # Assert 1: result must be a string
    assert isinstance(result, str), f"Expected str, got {type(result)}"

    # Assert 2: result must contain error description (not empty)
    assert len(result) > 0, "Error result string must not be empty"

    # Assert 3: result must indicate failure (contains error-related content)
    assert "失败" in result or "错误" in result or error_message in result, (
        f"Result '{result}' should contain error description"
    )

    # Assert 4: no ActionEngine methods were called
    mock_action_engine.click.assert_not_called()
    mock_action_engine.type_text.assert_not_called()
    mock_action_engine.open_application.assert_not_called()
    mock_action_engine.move_to.assert_not_called()
