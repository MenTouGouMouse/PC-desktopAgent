"""Bug condition exploration test for Bug 1:
_build_result in _locate_by_qwen_vl stores physical coords instead of logical coords.

On UNFIXED code: bbox[0] == 280 (cx_orig - 20 = 300 - 20), assertion FAILS.
On FIXED code:   bbox[0] == 180 (lx - 20 = 200 - 20), assertion PASSES.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from perception.dpi_adapter import DPIAdapter
from perception.element_locator import ElementLocator


def test_bug1_build_result_stores_physical_not_logical() -> None:
    """Bug 1 exploration: _build_result must apply to_logical() before storing bbox.

    Setup:
    - DPIAdapter(scale_factor=1.5)  → to_logical(300, 450) = (200, 300)
    - Qwen-VL API returns center=[300, 450], confidence=0.9
    - Screenshot is 900×700 (no upscaling needed, scale_ratio=1.0)

    Expected (FIXED) behavior:
    - cx_orig = int(300 / 1.0) = 300
    - cy_orig = int(450 / 1.0) = 450
    - lx, ly = to_logical(300, 450) = (200, 300)
    - bbox = (lx - 20, ly - 20, 40, 40) = (180, 280, 40, 40)

    On UNFIXED code:
    - bbox = (cx_orig - 20, cy_orig - 20, 40, 40) = (280, 430, 40, 40)
    - Assertions below FAIL → confirms bug exists
    """
    locator = ElementLocator()
    # Override DPI adapter with scale_factor=1.5
    locator._dpi = DPIAdapter(scale_factor=1.5)

    # 900×700 screenshot — no upscaling needed (scale_ratio stays 1.0)
    screenshot = np.zeros((700, 900, 3), dtype=np.uint8)

    mock_api_response = {"found": True, "center": [300, 450], "confidence": 0.9}

    with patch.object(locator, "_call_qwen_vl_api", return_value=mock_api_response):
        result = locator._locate_by_qwen_vl(screenshot, "安装按钮")

    assert result is not None, "_locate_by_qwen_vl returned None unexpectedly"

    # FIXED: lx = round(300 / 1.5) = 200, bbox[0] = 200 - 20 = 180
    assert result.bbox[0] == 180, (
        f"Bug 1 detected: bbox[0]={result.bbox[0]} but expected 180 "
        f"(lx=200 after to_logical(300, scale=1.5), lx-20=180). "
        f"Unfixed code stores physical coord 300, giving bbox[0]=280."
    )

    # FIXED: ly = round(450 / 1.5) = 300, bbox[1] = 300 - 20 = 280
    assert result.bbox[1] == 280, (
        f"Bug 1 detected: bbox[1]={result.bbox[1]} but expected 280 "
        f"(ly=300 after to_logical(450, scale=1.5), ly-20=280). "
        f"Unfixed code stores physical coord 450, giving bbox[1]=430."
    )


# ---------------------------------------------------------------------------
# Preservation tests (Task 2) — MUST PASS on unfixed code
# ---------------------------------------------------------------------------

from hypothesis import given, settings
import hypothesis.strategies as st


@given(cx=st.integers(0, 3840), cy=st.integers(0, 2160))
@settings(max_examples=50)
def test_preservation_build_result_noop_at_scale_1(cx: int, cy: int) -> None:
    """Preservation: scale_factor=1.0 → to_logical is identity, bbox unchanged.

    **Validates: Requirements 3.1**
    """
    locator = ElementLocator()
    locator._dpi = DPIAdapter(scale_factor=1.0)
    screenshot = np.zeros((700, 900, 3), dtype=np.uint8)
    mock_api_response = {"found": True, "center": [cx, cy], "confidence": 0.9}
    with patch.object(locator, "_call_qwen_vl_api", return_value=mock_api_response):
        result = locator._locate_by_qwen_vl(screenshot, "test_element")
    assert result is not None
    # At scale=1.0, to_logical(cx, cy) == (cx, cy), so bbox center == (cx, cy)
    assert result.bbox[0] == cx - 20
    assert result.bbox[1] == cy - 20
