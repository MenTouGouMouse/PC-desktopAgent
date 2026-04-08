"""
Preservation Property Test — Qwen-VL 正常返回时不触发重试

这些测试在未修复代码上 MUST PASS — 记录基线行为，修复后必须保持。

Validates: Requirements 3.2
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from perception.element_locator import ElementLocator, ElementResult


def _make_screenshot() -> np.ndarray:
    """Create a minimal valid BGR screenshot."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


class TestQwenVLPreservationProperty:
    """Property: when Qwen-VL returns found=True with valid coords, call_count=1 and result.coords is not None."""

    @given(st.integers(1, 1920), st.integers(1, 1080))
    @settings(max_examples=30)
    def test_valid_coords_returns_immediately_call_count_1(self, x: int, y: int) -> None:
        """
        **Validates: Requirements 3.2**

        Property: For any valid coords [x, y], _locate_by_qwen_vl returns ElementResult
        with call_count=1 (no retry triggered).
        """
        locator = ElementLocator()
        screenshot = _make_screenshot()

        api_response = {"found": True, "coords": [x, y], "confidence": 0.9}
        call_count = 0

        def mock_api(b64_image: str, element_description: str) -> dict:
            nonlocal call_count
            call_count += 1
            return api_response

        with patch.object(locator, "_call_qwen_vl_api", side_effect=mock_api), \
             patch("cv2.imencode", return_value=(True, np.zeros((10,), dtype=np.uint8))):
            result = locator._locate_by_qwen_vl(screenshot, "安装按钮")

        # Preservation: valid coords → exactly 1 call, no retry
        assert call_count == 1, (
            f"Expected _call_qwen_vl_api to be called exactly 1 time for valid coords [{x}, {y}], "
            f"but was called {call_count} times."
        )
        assert result is not None, (
            f"Expected ElementResult for valid coords [{x}, {y}], but got None."
        )
        assert result.coords is not None, (
            f"Expected result.coords to be non-None for valid coords [{x}, {y}]."
        )

    @given(st.integers(1, 1920), st.integers(1, 1080))
    @settings(max_examples=30)
    def test_valid_coords_result_coords_match(self, x: int, y: int) -> None:
        """
        **Validates: Requirements 3.2**

        Property: result.coords center point is derived from the returned [x, y].
        """
        locator = ElementLocator()
        screenshot = _make_screenshot()

        api_response = {"found": True, "coords": [x, y], "confidence": 0.9}

        with patch.object(locator, "_call_qwen_vl_api", return_value=api_response), \
             patch("cv2.imencode", return_value=(True, np.zeros((10,), dtype=np.uint8))):
            result = locator._locate_by_qwen_vl(screenshot, "安装按钮")

        assert result is not None
        # bbox center should be close to (x, y)
        bx, by, bw, bh = result.bbox
        cx = bx + bw // 2
        cy = by + bh // 2
        assert cx == x, f"Expected bbox center x={x}, got {cx}"
        assert cy == y, f"Expected bbox center y={y}, got {cy}"


@property
def coords(self) -> tuple[int, int] | None:
    """Helper: extract center coords from ElementResult bbox."""
    bx, by, bw, bh = self.bbox
    return (bx + bw // 2, by + bh // 2)


# Monkey-patch for convenience in tests above
ElementResult.coords = property(lambda self: (self.bbox[0] + self.bbox[2] // 2, self.bbox[1] + self.bbox[3] // 2))  # type: ignore[method-assign]
