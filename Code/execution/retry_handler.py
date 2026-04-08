"""执行层：重试处理模块。

负责为 Action_Engine 方法提供统一的指数退避重试装饰器，以及元素等待轮询工具。
所有重试逻辑集中在此模块，其他模块不得自行添加临时重试。
"""
from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

if TYPE_CHECKING:
    from perception.element_locator import ElementResult

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class RetryExhaustedError(Exception):
    """所有重试次数耗尽后抛出。

    Attributes:
        reason: 最后一次失败的原因描述
        retry_count: 已执行的重试次数（不含首次调用）
    """

    def __init__(self, reason: str, retry_count: int) -> None:
        super().__init__(f"操作在 {retry_count} 次重试后仍然失败：{reason}")
        self.reason: str = reason
        self.retry_count: int = retry_count

    def __str__(self) -> str:
        return f"RetryExhaustedError(retry_count={self.retry_count}): {self.reason}"


def with_retry(func: F) -> F:
    """装饰器：指数退避重试，初始 1s，最多 3 次重试，jitter 0–1s。

    使用 tenacity 实现：
    - stop_after_attempt(3)：最多重试 3 次（共 4 次调用）
    - wait_exponential(multiplier=1, min=1, max=8) + wait_random(0, 1)：指数退避 + 随机抖动
    - before_sleep_log：每次重试前记录 WARNING 日志

    当 3 次重试全部失败后，捕获 tenacity.RetryError 并重新抛出为
    :class:`RetryExhaustedError`，包含失败原因和重试次数（3）。

    Args:
        func: 被装饰的可调用对象。

    Returns:
        包装后的可调用对象，行为与原函数相同，但具备重试能力。
    """
    # stop_after_attempt(4) = 1 original call + 3 retries = 4 total attempts
    _retry_decorator = retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8) + wait_random(0, 1),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )
    wrapped = _retry_decorator(func)

    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return wrapped(*args, **kwargs)
        except RetryError as exc:
            cause = exc.last_attempt.exception()
            reason = str(cause) if cause is not None else repr(exc)
            raise RetryExhaustedError(reason=reason, retry_count=3) from exc

    # Preserve function metadata
    functools.update_wrapper(_wrapper, func)
    _wrapper.__wrapped__ = func  # type: ignore[attr-defined]

    return _wrapper  # type: ignore[return-value]


def wait_for_element(
    locator_fn: Callable[[], ElementResult | None],
    timeout: float = 10.0,
) -> ElementResult:
    """轮询等待元素出现，超时抛出 TimeoutError。

    每隔 0.5 秒调用一次 ``locator_fn()``，直到返回非 ``None`` 结果或超时。

    Args:
        locator_fn: 无参可调用对象，成功时返回 :class:`~perception.element_locator.ElementResult`，
                    未找到时返回 ``None``。
        timeout: 最长等待时间（秒），默认 10.0 秒。

    Returns:
        第一个非 ``None`` 的 :class:`~perception.element_locator.ElementResult`。

    Raises:
        TimeoutError: 在 ``timeout`` 秒内 ``locator_fn`` 始终返回 ``None``。
    """
    _poll_interval: float = 0.5
    start: float = time.monotonic()

    while True:
        result = locator_fn()
        if result is not None:
            elapsed = time.monotonic() - start
            logger.debug("wait_for_element: 元素已找到，耗时 %.2fs", elapsed)
            return result
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            break
        logger.debug("wait_for_element: 元素未出现，继续轮询（已等待 %.1fs）", elapsed)
        time.sleep(_poll_interval)

    raise TimeoutError(f"等待元素超时（{timeout}s 内未找到）")
