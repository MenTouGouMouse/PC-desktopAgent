"""
Bug Condition Exploration Test — Bug 2: Qwen-VL 返回 found=True 但 coords=None 时不重试

这些测试在未修复代码上 MUST FAIL，失败即证明 bug 存在。
DO NOT fix the code when tests fail.

Expected outcome on UNFIXED code: FAILS
- _call_qwen_vl_api is called exactly 1 time (no retries)
- Test expects call_count IN [2, 4] (at least 1 retry)

Validates: Requirements 1.3, 1.4
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Mock dashscope before importing element_locator
# ---------------------------------------------------------------------------

def _setup_dashscope_mock():
    if "dashscope" not in sys.modules:
        mock_dashscope = types.ModuleType("dashscope")
        mock_dashscope.MultiModalConversation = MagicMock()
        sys.modules["dashscope"] = mock_dashscope


_setup_dashscope_mock()


@pytest.fixture
def screenshot() -> np.ndarray:
    return np.zeros((480, 640, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Test: _locate_by_qwen_vl retries when coords=None
# ---------------------------------------------------------------------------

class TestQwenVLRetryOnCoordsNone:
    def test_api_called_more_than_once_when_coords_none(self, screenshot):
        """
        Bug condition: _call_qwen_vl_api always returns {"found": True, "coords": None}.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed code calls _call_qwen_vl_api exactly 1 time then returns None
        - Fixed code should retry up to 3 times (call_count IN [2, 4])

        Counterexample: call_count = 1 (no retries happened)
        """
        from perception.element_locator import ElementLocator

        locator = ElementLocator()
        call_count = 0

        def mock_api(b64_image, element_description):
            nonlocal call_count
            call_count += 1
            return {"found": True, "coords": None}

        with patch.object(locator, "_call_qwen_vl_api", side_effect=mock_api), \
             patch("time.sleep"):  # speed up test
            result = locator._locate_by_qwen_vl(screenshot, "完成")

        # FAILS on unfixed code: call_count == 1 (no retries)
        assert call_count in range(2, 5), (
            f"Expected _call_qwen_vl_api to be called 2-4 times (1 initial + up to 3 retries), "
            f"but was called {call_count} time(s). "
            f"Bug: unfixed code does not retry when coords=None, call_count=1."
        )

    def test_returns_none_after_all_retries_exhausted(self, screenshot):
        """
        Bug condition: _call_qwen_vl_api always returns {"found": True, "coords": None}.

        After all retries are exhausted, result should be None (fallback to next strategy).
        This part should pass on both fixed and unfixed code.
        """
        from perception.element_locator import ElementLocator

        locator = ElementLocator()

        def mock_api(b64_image, element_description):
            return {"found": True, "coords": None}

        with patch.object(locator, "_call_qwen_vl_api", side_effect=mock_api), \
             patch("time.sleep"):
            result = locator._locate_by_qwen_vl(screenshot, "完成")

        assert result is None, (
            f"Expected None after all retries exhausted, but got {result!r}."
        )

    def test_retry_count_is_at_most_3(self, screenshot):
        """
        Bug condition: _call_qwen_vl_api always returns {"found": True, "coords": None}.

        Fixed code should retry at most 3 times (total calls <= 4).

        EXPECTED OUTCOME on UNFIXED code: FAILS (call_count=1, not in [2,4])
        """
        from perception.element_locator import ElementLocator

        locator = ElementLocator()
        call_count = 0

        def mock_api(b64_image, element_description):
            nonlocal call_count
            call_count += 1
            return {"found": True, "coords": None}

        with patch.object(locator, "_call_qwen_vl_api", side_effect=mock_api), \
             patch("time.sleep"):
            locator._locate_by_qwen_vl(screenshot, "完成")

        # Total calls: 1 initial + up to 3 retries = max 4
        assert call_count <= 4, (
            f"Expected at most 4 total calls (1 + 3 retries), but got {call_count}."
        )
        # And at least 2 (1 initial + at least 1 retry)
        assert call_count >= 2, (
            f"Expected at least 2 calls (1 initial + 1 retry), but got {call_count}. "
            f"Bug: unfixed code makes only 1 call with no retries."
        )
