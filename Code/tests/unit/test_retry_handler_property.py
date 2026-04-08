"""属性测试：execution/retry_handler.py — Retry_Handler 属性测试。

# Feature: cv-desktop-automation-agent, Property 12: 重试耗尽后抛出含重试次数的异常
# Validates: Requirements 7.2, 7.4
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from execution.retry_handler import RetryExhaustedError, with_retry


# Feature: cv-desktop-automation-agent, Property 12: 重试耗尽后抛出含重试次数的异常
# Validates: Requirements 7.2, 7.4
@settings(max_examples=100)
@given(
    error_message=st.text(),
)
def test_retry_exhausted_call_count_and_exception_contains_retry_count(
    error_message: str,
) -> None:
    """Property 12: 对于任意总是失败的操作函数，经 with_retry 装饰后：
    - 函数被调用的总次数必须恰好为 4（1次原始 + 3次重试）
    - 最终抛出的异常必须包含重试次数信息（"3"）

    Validates: Requirements 7.2, 7.4
    """
    call_count = 0

    @with_retry
    def always_fail() -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError(error_message)

    # Reset counter for each hypothesis example
    call_count = 0

    with patch("tenacity.nap.time.sleep"), patch("time.sleep"):
        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()

    # 1 original call + 3 retries = 4 total
    assert call_count == 4, f"Expected 4 total calls, got {call_count}"

    # Exception must contain the retry count
    assert "3" in str(exc_info.value), (
        f"RetryExhaustedError string '{exc_info.value}' does not contain '3'"
    )

    # retry_count attribute must be exactly 3
    assert exc_info.value.retry_count == 3
