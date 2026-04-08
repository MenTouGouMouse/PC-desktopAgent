"""决策层：LLM 客户端模块。

封装 DashScope API 调用，负责与 qwen-plus 模型通信。
从 config/.env 读取 DASHSCOPE_API_KEY，检查响应状态码并按策略处理错误：
- 400：参数错误，记录 ERROR，不重试，抛出 LLMCallError
- 429/500/503：触发指数退避重试（复用 with_retry），最多 3 次
- 其他非 200：记录 WARNING，抛出 LLMCallError
调用失败且不满足重试条件时抛出 LLMCallError，不执行任何操作。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    from dashscope.aigc.generation import Generation  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Generation = None  # type: ignore[assignment,misc]

from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from execution.retry_handler import RetryExhaustedError

logger = logging.getLogger(__name__)

# 需要重试的状态码
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 503})

# 模块级 tenacity 重试装饰器（只创建一次，避免每次调用重建）
_llm_retry = retry(
    retry=retry_if_exception_type(RuntimeError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8) + wait_random(0, 1),
    before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    reraise=False,
)


class LLMCallError(Exception):
    """LLM API 调用失败时抛出。

    Attributes:
        code: API 返回的错误码（如 "InvalidParameter"）
        message: API 返回的错误描述
        status_code: HTTP 状态码
    """

    def __init__(self, message: str, code: str = "", status_code: int = 0) -> None:
        super().__init__(message)
        self.code: str = code
        self.status_code: int = status_code

    def __str__(self) -> str:
        return f"LLMCallError(status_code={self.status_code}, code={self.code!r}): {self.args[0]}"


def _load_api_key() -> str:
    """从 config/.env 加载 DASHSCOPE_API_KEY。

    Returns:
        API Key 字符串。

    Raises:
        LLMCallError: 环境变量未设置时抛出。
    """
    config_dir = Path(__file__).parent.parent / "config"
    env_path = config_dir / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise LLMCallError(
            "DASHSCOPE_API_KEY 未设置，请在 config/.env 或系统环境中配置。",
            code="MissingApiKey",
            status_code=0,
        )
    return api_key


class LLMClient:
    """DashScope qwen-plus 模型客户端。

    封装 Generation.call，处理状态码检查、错误分类和重试逻辑。
    """

    def __init__(self, api_key: str = "", model: str = "qwen-plus") -> None:
        """初始化 LLMClient。

        Args:
            api_key: DashScope API Key；若为空则从 config/.env 自动读取。
            model: 使用的模型 ID，默认 "qwen-plus"。
        """
        self._api_key: str = api_key if api_key else _load_api_key()
        self._model: str = model
        logger.info("LLMClient 初始化完成，model=%s", self._model)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """调用 DashScope API，返回模型响应。

        对 429/500/503 错误自动触发指数退避重试（最多 3 次）。
        400 错误直接记录 ERROR 并抛出 LLMCallError，不重试。
        其他非 200 错误记录 WARNING 并抛出 LLMCallError。

        Args:
            messages: 对话消息列表，格式符合 OpenAI 兼容规范。
            tools: 可选的工具定义列表（Function Call schema）。

        Returns:
            模型响应的 output.message 字典。

        Raises:
            LLMCallError: API 调用失败或返回非 200 状态码时抛出。
        """
        # 将实际 API 调用拆分为内部方法，以便对可重试错误应用 with_retry
        try:
            return self._chat_with_retry(messages, tools)
        except RetryExhaustedError as exc:
            raise LLMCallError(
                f"LLM 调用在重试耗尽后仍然失败：{exc.reason}",
                code="RetryExhausted",
                status_code=0,
            ) from exc

    def _do_call(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> dict:
        """执行单次 DashScope API 调用（不含重试）。

        Args:
            messages: 对话消息列表。
            tools: 工具定义列表。

        Returns:
            模型响应的 output.message 字典。

        Raises:
            LLMCallError: 400 或其他非 200 非重试状态码时抛出（不重试）。
            RuntimeError: 429/500/503 时抛出，供 with_retry 捕获并重试。
        """
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "result_format": "message",
            "api_key": self._api_key,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug("LLMClient._do_call: 发送请求，messages 数量=%d", len(messages))
        response = Generation.call(**kwargs)

        status_code: int = response.status_code
        if status_code == 200:
            logger.debug("LLMClient._do_call: 请求成功")
            # response.output 是类 dict 对象，message 在 choices[0]["message"] 里
            output = response.output
            choices = None
            if hasattr(output, "get"):
                choices = output.get("choices") or []
            elif hasattr(output, "choices"):
                choices = output.choices or []
            if choices:
                msg = choices[0]
                if isinstance(msg, dict):
                    return dict(msg.get("message", {}))
                return dict(getattr(msg, "message", {}))
            # 兜底：旧版 API 直接返回 text 字段
            text = output.get("text", "") if hasattr(output, "get") else getattr(output, "text", "")
            return {"role": "assistant", "content": text or ""}

        code: str = getattr(response, "code", "") or ""
        message: str = getattr(response, "message", "") or ""

        if status_code == 400:
            logger.error(
                "LLMClient._do_call: 参数错误 status_code=400, code=%s, message=%s",
                code,
                message,
            )
            raise LLMCallError(
                f"参数错误：{code} - {message}",
                code=code,
                status_code=status_code,
            )

        if status_code in _RETRYABLE_STATUS_CODES:
            logger.warning(
                "LLMClient._do_call: 可重试错误 status_code=%d, code=%s, message=%s",
                status_code,
                code,
                message,
            )
            # 抛出普通异常，让 with_retry 捕获并重试
            raise RuntimeError(
                f"DashScope API 错误 {status_code}: {code} - {message}"
            )

        # 其他非 200 状态码
        logger.warning(
            "LLMClient._do_call: 未知错误 status_code=%d, code=%s, message=%s",
            status_code,
            code,
            message,
        )
        raise LLMCallError(
            f"API 返回非预期状态码 {status_code}：{code} - {message}",
            code=code,
            status_code=status_code,
        )

    def _chat_with_retry(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> dict:
        """带重试的 chat 调用，仅对 429/500/503 触发重试。

        使用模块级 tenacity 装饰器，仅对 RuntimeError（由 _do_call 在
        429/500/503 时抛出）触发重试；LLMCallError（400 或其他不可重试错误）
        不在重试范围内，直接向上传播。

        Args:
            messages: 对话消息列表。
            tools: 工具定义列表。

        Returns:
            模型响应的 output.message 字典。

        Raises:
            LLMCallError: 400 或其他不可重试错误时直接抛出。
            RetryExhaustedError: 重试耗尽后抛出。
        """
        @_llm_retry
        def _retryable_call() -> dict:
            return self._do_call(messages, tools)

        try:
            return _retryable_call()
        except RetryError as exc:
            cause = exc.last_attempt.exception()
            reason = str(cause) if cause is not None else repr(exc)
            raise RetryExhaustedError(reason=reason, retry_count=3) from exc
