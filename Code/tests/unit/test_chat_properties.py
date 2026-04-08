"""属性测试：chat-automation-interface 正确性属性验证。

使用 Hypothesis 对 IntentParser 和 ChatAgent 的核心属性进行属性测试。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gui.chat_agent import IntentParser, IntentResult, _make_unknown


# ---------------------------------------------------------------------------
# 辅助策略
# ---------------------------------------------------------------------------

def _intent_result_strategy() -> st.SearchStrategy[IntentResult]:
    """生成合法 IntentResult 对象的策略。"""
    intent_st = st.sampled_from(["file_organize", "software_install", "unknown"])
    params_st = st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pc"))),
        values=st.one_of(st.none(), st.text(max_size=50), st.integers()),
        max_size=5,
    )
    clarification_st = st.one_of(st.none(), st.text(max_size=100))
    return st.builds(IntentResult, intent=intent_st, params=params_st, clarification=clarification_st)


def _valid_json_strategy() -> st.SearchStrategy[str]:
    """生成合法 JSON 字符串的策略（简单对象）。"""
    return st.fixed_dictionaries({
        "intent": st.sampled_from(["file_organize", "software_install", "unknown"]),
        "params": st.just({}),
    }).map(json.dumps)


def _json_with_optional_markdown_wrapper() -> st.SearchStrategy[str]:
    """生成可能被 Markdown 代码块包裹的合法 JSON 字符串。"""
    json_st = _valid_json_strategy()
    wrapper_st = st.sampled_from([
        lambda s: s,                          # 无包裹
        lambda s: f"```json\n{s}\n```",       # ```json ... ```
        lambda s: f"```\n{s}\n```",           # ``` ... ```
        lambda s: f"```json\n{s}```",         # 无尾部换行
        lambda s: f"  ```json\n{s}\n```  ",   # 前后空格
    ])
    return st.tuples(json_st, wrapper_st).map(lambda t: t[1](t[0]))


def _large_context_strategy() -> st.SearchStrategy[list[dict]]:
    """生成总字符数超过 8000 的上下文列表。"""
    long_content = "x" * 900  # 每条消息约 900 字符
    msg_st = st.fixed_dictionaries({
        "role": st.sampled_from(["user", "assistant"]),
        "content": st.just(long_content),
    })
    # 生成 10-20 条消息，总字符数必然超过 8000
    return st.lists(msg_st, min_size=10, max_size=20)


def _is_valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 属性 6：Markdown 标记剥离后 JSON 可解析
# ---------------------------------------------------------------------------

@given(_json_with_optional_markdown_wrapper())
@settings(max_examples=100)
def test_strip_markdown_preserves_json(wrapped: str) -> None:
    """Feature: chat-automation-interface, Property 6: Markdown 标记剥离后 JSON 可解析。

    对于任意合法 JSON 字符串，无论是否被 Markdown 代码块包裹，
    经 _strip_markdown 处理后，结果应能被 json.loads 成功解析。
    验证：需求 10.1
    """
    mock_llm = MagicMock()
    parser = IntentParser(mock_llm)
    stripped = parser._strip_markdown(wrapped)
    # 剥离后应能被 json.loads 解析
    parsed = json.loads(stripped)
    assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 属性 7：IntentResult 序列化往返
# ---------------------------------------------------------------------------

@given(_intent_result_strategy())
@settings(max_examples=100)
def test_intent_result_round_trip(result: IntentResult) -> None:
    """Feature: chat-automation-interface, Property 7: IntentResult 序列化往返。

    对于任意合法 IntentResult，序列化为 JSON 后再通过 _validate_and_build 解析，
    应得到与原始对象字段完全等价的 IntentResult。
    验证：需求 10.3
    """
    mock_llm = MagicMock()
    parser = IntentParser(mock_llm)

    # 序列化
    raw_dict: dict[str, Any] = {
        "intent": result.intent,
        "params": result.params,
    }
    if result.clarification is not None:
        raw_dict["clarification"] = result.clarification

    json_str = json.dumps(raw_dict)
    raw = json.loads(json_str)

    # 通过 _validate_and_build 重建
    rebuilt = parser._validate_and_build(raw)

    assert rebuilt.intent == result.intent
    assert rebuilt.params == result.params
    assert rebuilt.clarification == result.clarification


# ---------------------------------------------------------------------------
# 属性 8：非法 JSON 输入返回 unknown IntentResult
# ---------------------------------------------------------------------------

@given(st.text().filter(lambda s: not _is_valid_json(s)))
@settings(max_examples=100)
def test_invalid_json_returns_unknown(text: str) -> None:
    """Feature: chat-automation-interface, Property 8: 非法 JSON 输入返回 unknown IntentResult。

    对于任意无法被 json.loads 解析的字符串，IntentParser.parse 应返回
    intent="unknown" 的默认 IntentResult，且不抛出任何异常。
    验证：需求 10.2
    """
    from decision.llm_client import LLMCallError

    mock_llm = MagicMock()
    mock_llm.chat.return_value = {"role": "assistant", "content": text}
    parser = IntentParser(mock_llm)

    result = parser.parse([{"role": "user", "content": "test"}])
    assert result.intent == "unknown"
    assert isinstance(result.params, dict)


# ---------------------------------------------------------------------------
# 属性 9：缺少 intent 字段时返回 unknown IntentResult
# ---------------------------------------------------------------------------

@given(
    st.dictionaries(
        keys=st.text(min_size=1, max_size=20).filter(lambda k: k != "intent"),
        values=st.one_of(st.none(), st.text(max_size=50), st.integers(), st.booleans()),
        max_size=5,
    )
)
@settings(max_examples=100)
def test_missing_intent_returns_unknown(raw_dict: dict) -> None:
    """Feature: chat-automation-interface, Property 9: 缺少 intent 字段时返回 unknown IntentResult。

    对于任意合法 JSON 对象，若不包含 intent 字段，或 intent 字段值不为字符串类型，
    _validate_and_build 应返回 intent="unknown" 的默认 IntentResult。
    验证：需求 10.4
    """
    mock_llm = MagicMock()
    parser = IntentParser(mock_llm)

    result = parser._validate_and_build(raw_dict)
    assert result.intent == "unknown"


@given(
    st.fixed_dictionaries({
        "intent": st.one_of(st.none(), st.integers(), st.booleans(), st.lists(st.text())),
        "params": st.just({}),
    })
)
@settings(max_examples=100)
def test_non_string_intent_returns_unknown(raw_dict: dict) -> None:
    """Feature: chat-automation-interface, Property 9b: intent 字段非字符串时返回 unknown。

    验证：需求 10.4
    """
    mock_llm = MagicMock()
    parser = IntentParser(mock_llm)

    result = parser._validate_and_build(raw_dict)
    assert result.intent == "unknown"


# ---------------------------------------------------------------------------
# 属性 2：上下文截断保留最近消息
# ---------------------------------------------------------------------------

@given(_large_context_strategy())
@settings(max_examples=100)
def test_context_truncation_keeps_recent(context: list[dict]) -> None:
    """Feature: chat-automation-interface, Property 2: 上下文截断保留最近消息。

    对于任意总字符数超过 8000 的 Conversation_Context，执行截断后，
    上下文长度应 ≤ 10，且保留的消息应与原始上下文的最后 N 条完全一致。
    验证：需求 4.3
    """
    import threading
    from unittest.mock import MagicMock

    from gui.chat_agent import ChatAgent, _CONTEXT_KEEP_RECENT, _CONTEXT_MAX_CHARS

    mock_llm = MagicMock()
    mock_pm = MagicMock()
    mock_pm.get.return_value = MagicMock(is_running=False)
    stop_event = threading.Event()
    push_calls: list[tuple[str, str]] = []

    agent = ChatAgent(
        llm_client=mock_llm,
        progress_manager=mock_pm,
        stop_event=stop_event,
        push_fn=lambda role, content: push_calls.append((role, content)),
    )

    # 注入大上下文
    agent._context = list(context)

    # 确认总字符数确实超过阈值
    total_chars = sum(len(m.get("content", "")) for m in agent._context)
    assert total_chars > _CONTEXT_MAX_CHARS, "测试前提：上下文总字符数必须超过阈值"

    original_last_n = context[-_CONTEXT_KEEP_RECENT:]
    agent._truncate_context_if_needed()

    # 截断后长度 ≤ 10
    assert len(agent._context) <= _CONTEXT_KEEP_RECENT

    # 保留的消息与原始最后 N 条一致
    assert agent._context == original_last_n

    # 推送了截断系统日志
    assert any("截断" in content for _, content in push_calls)
