"""Unit tests for decision/llm_client.py - LLMClient and LLMCallError."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from decision.llm_client import LLMCallError, LLMClient, _load_api_key

# Patch target: Generation is imported at module level in llm_client.py
_GEN_PATCH = "decision.llm_client.Generation.call"


# ---------------------------------------------------------------------------
# LLMCallError
# ---------------------------------------------------------------------------


class TestLLMCallError:
    def test_str_representation(self):
        err = LLMCallError("call failed", code="RateLimit", status_code=429)
        s = str(err)
        assert "429" in s
        assert "RateLimit" in s
        assert "call failed" in s

    def test_default_code_and_status(self):
        err = LLMCallError("failed")
        assert err.code == ""
        assert err.status_code == 0

    def test_is_exception(self):
        with pytest.raises(LLMCallError):
            raise LLMCallError("test")


# ---------------------------------------------------------------------------
# _load_api_key
# ---------------------------------------------------------------------------


class TestLoadApiKey:
    def test_raises_when_env_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DASHSCOPE_API_KEY", None)
            with patch("decision.llm_client.Path.exists", return_value=False):
                with pytest.raises(LLMCallError) as exc_info:
                    _load_api_key()
        assert exc_info.value.code == "MissingApiKey"

    def test_returns_key_from_env(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key-123"}):
            with patch("decision.llm_client.Path.exists", return_value=False):
                key = _load_api_key()
        assert key == "test-key-123"

    def test_loads_dotenv_when_file_exists(self):
        with patch("decision.llm_client.Path.exists", return_value=True):
            with patch("decision.llm_client.load_dotenv") as mock_load:
                with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "from-dotenv"}):
                    key = _load_api_key()
        mock_load.assert_called_once()
        assert key == "from-dotenv"


# ---------------------------------------------------------------------------
# LLMClient.__init__
# ---------------------------------------------------------------------------


class TestLLMClientInit:
    def test_init_with_explicit_api_key(self):
        client = LLMClient(api_key="explicit-key")
        assert client._api_key == "explicit-key"
        assert client._model == "qwen-plus"

    def test_init_with_custom_model(self):
        client = LLMClient(api_key="key", model="qwen-max")
        assert client._model == "qwen-max"

    def test_init_without_key_calls_load_api_key(self):
        with patch("decision.llm_client._load_api_key", return_value="loaded-key") as mock_load:
            client = LLMClient()
        mock_load.assert_called_once()
        assert client._api_key == "loaded-key"


# ---------------------------------------------------------------------------
# LLMClient._do_call
# ---------------------------------------------------------------------------


def _make_response(status_code: int, message_dict: dict | None = None,
                   code: str = "", message: str = "") -> MagicMock:
    """Helper: construct a mock DashScope response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.code = code
    resp.message = message
    if message_dict is not None:
        resp.output.get.side_effect = lambda key, default=None: (
            [{"message": message_dict}] if key == "choices" else default
        )
    else:
        resp.output.get.return_value = None
    return resp


@pytest.fixture()
def client() -> LLMClient:
    return LLMClient(api_key="test-key")


class TestDoCall:
    def test_200_returns_output_message(self, client):
        expected = {"role": "assistant", "content": "hello"}
        mock_resp = _make_response(200, message_dict=expected)

        with patch(_GEN_PATCH, return_value=mock_resp):
            result = client._do_call([{"role": "user", "content": "hi"}], None)

        assert result == expected

    def test_200_with_tools_passes_tool_choice(self, client):
        mock_resp = _make_response(200, message_dict={"role": "assistant", "content": ""})
        tools = [{"type": "function", "function": {"name": "click"}}]

        with patch(_GEN_PATCH, return_value=mock_resp) as mock_call:
            client._do_call([{"role": "user", "content": "hi"}], tools)

        call_kwargs = mock_call.call_args[1]
        assert call_kwargs["tools"] == tools
        assert call_kwargs["tool_choice"] == "auto"

    def test_400_raises_llm_call_error_no_retry(self, client):
        mock_resp = _make_response(400, code="InvalidParameter", message="bad param")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(LLMCallError) as exc_info:
                client._do_call([{"role": "user", "content": "hi"}], None)

        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "InvalidParameter"

    def test_429_raises_runtime_error_for_retry(self, client):
        mock_resp = _make_response(429, code="Throttling", message="rate limit")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(RuntimeError) as exc_info:
                client._do_call([{"role": "user", "content": "hi"}], None)

        assert "429" in str(exc_info.value)

    def test_500_raises_runtime_error_for_retry(self, client):
        mock_resp = _make_response(500, code="InternalError", message="server error")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(RuntimeError):
                client._do_call([{"role": "user", "content": "hi"}], None)

    def test_503_raises_runtime_error_for_retry(self, client):
        mock_resp = _make_response(503, code="ServiceUnavailable", message="unavailable")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(RuntimeError):
                client._do_call([{"role": "user", "content": "hi"}], None)

    def test_other_non_200_raises_llm_call_error(self, client):
        mock_resp = _make_response(403, code="Forbidden", message="no access")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(LLMCallError) as exc_info:
                client._do_call([{"role": "user", "content": "hi"}], None)

        assert exc_info.value.status_code == 403

    def test_no_tools_does_not_pass_tool_choice(self, client):
        mock_resp = _make_response(200, message_dict={"role": "assistant", "content": "ok"})

        with patch(_GEN_PATCH, return_value=mock_resp) as mock_call:
            client._do_call([{"role": "user", "content": "hi"}], None)

        call_kwargs = mock_call.call_args[1]
        assert "tools" not in call_kwargs
        assert "tool_choice" not in call_kwargs


# ---------------------------------------------------------------------------
# LLMClient.chat (integration with retry)
# ---------------------------------------------------------------------------


class TestChat:
    def test_chat_success_returns_message(self, client):
        expected = {"role": "assistant", "content": "done"}
        mock_resp = _make_response(200, message_dict=expected)

        with patch(_GEN_PATCH, return_value=mock_resp):
            result = client.chat([{"role": "user", "content": "hi"}])

        assert result == expected

    def test_chat_400_raises_llm_call_error_immediately(self, client):
        """400 error should not retry, raise LLMCallError immediately."""
        mock_resp = _make_response(400, code="InvalidParam", message="bad")

        with patch(_GEN_PATCH, return_value=mock_resp) as mock_call:
            with pytest.raises(LLMCallError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])

        assert mock_call.call_count == 1
        assert exc_info.value.status_code == 400

    def test_chat_retryable_error_exhausts_and_raises_llm_call_error(self, client):
        """429/500/503 retries exhausted -> LLMCallError with RetryExhausted code."""
        mock_resp = _make_response(429, code="Throttling", message="rate limit")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(LLMCallError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])

        assert exc_info.value.code == "RetryExhausted"

    def test_chat_with_tools(self, client):
        expected = {"role": "assistant", "content": "tool call"}
        mock_resp = _make_response(200, message_dict=expected)
        tools = [{"type": "function", "function": {"name": "click"}}]

        with patch(_GEN_PATCH, return_value=mock_resp):
            result = client.chat([{"role": "user", "content": "click"}], tools=tools)

        assert result == expected

    def test_chat_other_non_200_raises_llm_call_error(self, client):
        mock_resp = _make_response(403, code="Forbidden", message="no access")

        with patch(_GEN_PATCH, return_value=mock_resp):
            with pytest.raises(LLMCallError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])

        assert exc_info.value.status_code == 403
