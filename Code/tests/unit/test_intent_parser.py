"""单元测试：IntentParser 意图解析器。

测试各 intent 类型解析、LLMCallError 传播、Markdown 剥离、字段校验等。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from decision.llm_client import LLMCallError
from gui.chat_agent import IntentParser, IntentResult


@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture
def parser(mock_llm: MagicMock) -> IntentParser:
    return IntentParser(mock_llm)


def _make_response(content: str) -> dict:
    return {"role": "assistant", "content": content}


# ---------------------------------------------------------------------------
# _strip_markdown
# ---------------------------------------------------------------------------

class TestStripMarkdown:
    def test_no_markdown(self, parser: IntentParser) -> None:
        raw = '{"intent": "unknown"}'
        assert parser._strip_markdown(raw) == raw

    def test_json_code_block(self, parser: IntentParser) -> None:
        wrapped = '```json\n{"intent": "unknown"}\n```'
        assert parser._strip_markdown(wrapped) == '{"intent": "unknown"}'

    def test_plain_code_block(self, parser: IntentParser) -> None:
        wrapped = '```\n{"intent": "unknown"}\n```'
        assert parser._strip_markdown(wrapped) == '{"intent": "unknown"}'

    def test_code_block_no_trailing_newline(self, parser: IntentParser) -> None:
        wrapped = '```json\n{"intent": "unknown"}```'
        assert parser._strip_markdown(wrapped) == '{"intent": "unknown"}'

    def test_strips_surrounding_whitespace(self, parser: IntentParser) -> None:
        wrapped = '  ```json\n{"intent": "unknown"}\n```  '
        result = parser._strip_markdown(wrapped)
        assert json.loads(result)["intent"] == "unknown"


# ---------------------------------------------------------------------------
# _validate_and_build
# ---------------------------------------------------------------------------

class TestValidateAndBuild:
    def test_valid_file_organize(self, parser: IntentParser) -> None:
        raw = {"intent": "file_organize", "params": {"source": "/tmp", "target": "/out"}}
        result = parser._validate_and_build(raw)
        assert result.intent == "file_organize"
        assert result.params["source"] == "/tmp"
        assert result.clarification is None

    def test_valid_software_install(self, parser: IntentParser) -> None:
        raw = {"intent": "software_install", "params": {"package_path": "/setup.exe"}}
        result = parser._validate_and_build(raw)
        assert result.intent == "software_install"

    def test_missing_intent_returns_unknown(self, parser: IntentParser) -> None:
        result = parser._validate_and_build({"params": {}})
        assert result.intent == "unknown"

    def test_non_string_intent_returns_unknown(self, parser: IntentParser) -> None:
        result = parser._validate_and_build({"intent": 42, "params": {}})
        assert result.intent == "unknown"

    def test_non_dict_input_returns_unknown(self, parser: IntentParser) -> None:
        result = parser._validate_and_build("not a dict")  # type: ignore[arg-type]
        assert result.intent == "unknown"

    def test_clarification_preserved(self, parser: IntentParser) -> None:
        raw = {"intent": "file_organize", "params": {"source": None}, "clarification": "请提供源目录"}
        result = parser._validate_and_build(raw)
        assert result.clarification == "请提供源目录"

    def test_missing_params_defaults_to_empty_dict(self, parser: IntentParser) -> None:
        raw = {"intent": "unknown"}
        result = parser._validate_and_build(raw)
        assert result.params == {}


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

class TestParse:
    def test_parse_file_organize(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        payload = {"intent": "file_organize", "params": {"source": "/src", "target": "/dst", "filters": []}}
        mock_llm.chat.return_value = _make_response(json.dumps(payload))
        result = parser.parse([{"role": "user", "content": "整理文件"}])
        assert result.intent == "file_organize"
        assert result.params["source"] == "/src"

    def test_parse_software_install(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        payload = {"intent": "software_install", "params": {"package_path": "/setup.exe"}}
        mock_llm.chat.return_value = _make_response(json.dumps(payload))
        result = parser.parse([{"role": "user", "content": "安装软件"}])
        assert result.intent == "software_install"

    def test_parse_unknown_intent(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        payload = {"intent": "unknown", "params": {}, "clarification": "无法处理"}
        mock_llm.chat.return_value = _make_response(json.dumps(payload))
        result = parser.parse([{"role": "user", "content": "你好"}])
        assert result.intent == "unknown"

    def test_parse_with_clarification(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        payload = {"intent": "file_organize", "params": {"source": None}, "clarification": "请提供源目录路径"}
        mock_llm.chat.return_value = _make_response(json.dumps(payload))
        result = parser.parse([{"role": "user", "content": "整理文件"}])
        assert result.clarification == "请提供源目录路径"

    def test_parse_strips_markdown_before_json(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        payload = {"intent": "unknown", "params": {}}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        mock_llm.chat.return_value = _make_response(wrapped)
        result = parser.parse([{"role": "user", "content": "test"}])
        assert result.intent == "unknown"

    def test_parse_invalid_json_returns_unknown(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        mock_llm.chat.return_value = _make_response("这不是 JSON")
        result = parser.parse([{"role": "user", "content": "test"}])
        assert result.intent == "unknown"

    def test_parse_llm_call_error_propagates(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        mock_llm.chat.side_effect = LLMCallError("API 失败", status_code=500)
        with pytest.raises(LLMCallError):
            parser.parse([{"role": "user", "content": "test"}])

    def test_parse_includes_system_prompt(self, parser: IntentParser, mock_llm: MagicMock) -> None:
        mock_llm.chat.return_value = _make_response('{"intent": "unknown", "params": {}}')
        parser.parse([{"role": "user", "content": "test"}])
        call_args = mock_llm.chat.call_args[0][0]
        assert call_args[0]["role"] == "system"
        assert "JSON" in call_args[0]["content"]
