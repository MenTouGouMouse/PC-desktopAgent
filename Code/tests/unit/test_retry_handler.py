"""Unit tests for execution/retry_handler.py."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from execution.retry_handler import RetryExhaustedError, wait_for_element, with_retry


# ---------------------------------------------------------------------------
# RetryExhaustedError
# ---------------------------------------------------------------------------


class TestRetryExhaustedError:
    def test_str_contains_retry_count(self) -> None:
        err = RetryExhaustedError(reason="boom", retry_count=3)
        assert "3" in str(err)

    def test_str_contains_reason(self) -> None:
        err = RetryExhaustedError(reason="network error", retry_count=3)
        assert "network error" in str(err)

    def test_attributes(self) -> None:
        err = RetryExhaustedError(reason="fail", retry_count=3)
        assert err.reason == "fail"
        assert err.retry_count == 3


# ---------------------------------------------------------------------------
# with_retry decorator
# ---------------------------------------------------------------------------


class TestWithRetry:
    def test_succeeds_on_first_call(self) -> None:
        """Function that succeeds immediately should return its value."""
        @with_retry
        def always_ok() -> str:
            return "ok"

        assert always_ok() == "ok"

    def test_total_call_count_is_four_on_exhaustion(self) -> None:
        """1 original + 3 retries = 4 total calls before raising."""
        call_count = 0

        @with_retry
        def always_fail() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        # Patch sleep at both tenacity locations to avoid real waiting
        with patch("tenacity.nap.time.sleep"), patch("time.sleep"):
            with pytest.raises(RetryExhaustedError):
                always_fail()

        assert call_count == 4

    def test_raises_retry_exhausted_error(self) -> None:
        @with_retry
        def always_fail() -> None:
            raise ValueError("bad value")

        with patch("tenacity.nap.time.sleep"):
            with pytest.raises(RetryExhaustedError) as exc_info:
                always_fail()

        assert exc_info.value.retry_count == 3

    def test_retry_exhausted_error_contains_reason(self) -> None:
        @with_retry
        def always_fail() -> None:
            raise RuntimeError("original cause")

        with patch("tenacity.nap.time.sleep"):
            with pytest.raises(RetryExhaustedError) as exc_info:
                always_fail()

        assert "original cause" in str(exc_info.value)

    def test_succeeds_after_transient_failures(self) -> None:
        """Function that fails twice then succeeds should return the value."""
        attempts = [0]

        @with_retry
        def flaky() -> str:
            attempts[0] += 1
            if attempts[0] < 3:
                raise RuntimeError("transient")
            return "recovered"

        with patch("tenacity.nap.time.sleep"):
            result = flaky()

        assert result == "recovered"
        assert attempts[0] == 3

    def test_preserves_function_name(self) -> None:
        @with_retry
        def my_function() -> None:
            pass

        assert my_function.__name__ == "my_function"

    def test_passes_args_and_kwargs(self) -> None:
        @with_retry
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(2, b=3) == 5


# ---------------------------------------------------------------------------
# wait_for_element
# ---------------------------------------------------------------------------


class TestWaitForElement:
    def test_returns_immediately_when_found(self) -> None:
        mock_result = MagicMock()
        locator = MagicMock(return_value=mock_result)

        result = wait_for_element(locator, timeout=5.0)

        assert result is mock_result
        locator.assert_called_once()

    def test_polls_until_element_appears(self) -> None:
        mock_result = MagicMock()
        # Return None twice, then the result
        locator = MagicMock(side_effect=[None, None, mock_result])

        with patch("time.sleep"):
            result = wait_for_element(locator, timeout=5.0)

        assert result is mock_result
        assert locator.call_count == 3

    def test_raises_timeout_error_when_element_never_found(self) -> None:
        locator = MagicMock(return_value=None)

        # monotonic() is called: once for `start`, then twice per loop iteration
        # (once after locator_fn, once for elapsed check). Provide enough values
        # so the second iteration sees elapsed >= timeout.
        # Values: start=0.0, elapsed_check1=0.3, elapsed_check2=0.3 (< 10),
        #         elapsed_check3=11.0 (>= 10) → break
        with patch("time.sleep"), patch("execution.retry_handler.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.3, 0.3, 11.0]
            mock_time.sleep = MagicMock()
            with pytest.raises(TimeoutError):
                wait_for_element(locator, timeout=10.0)

    def test_default_timeout_is_ten_seconds(self) -> None:
        """Verify the default timeout parameter is 10.0."""
        import inspect
        sig = inspect.signature(wait_for_element)
        assert sig.parameters["timeout"].default == 10.0

    def test_timeout_error_message_contains_timeout_value(self) -> None:
        locator = MagicMock(return_value=None)

        with patch("execution.retry_handler.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.3, 0.3, 11.0]
            mock_time.sleep = MagicMock()
            with pytest.raises(TimeoutError) as exc_info:
                wait_for_element(locator, timeout=10.0)

        assert "10" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st


# Feature: cv-desktop-automation-agent, Property 12: 重试耗尽后抛出含重试次数的异常
# Validates: Requirements 7.2, 7.4
@settings(max_examples=100)
@given(error_message=st.text())
def test_retry_exhausted_call_count_and_exception_contains_retry_count(
    error_message: str,
) -> None:
    """Property 12: For any always-failing function, with_retry must call it
    exactly 4 times (1 original + 3 retries) and raise RetryExhaustedError
    containing the retry count (3).

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
