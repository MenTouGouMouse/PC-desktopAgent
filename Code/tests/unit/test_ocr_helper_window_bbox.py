"""Bug condition exploration test for Bug 2:
find_button_bbox does not accept a window_bbox parameter.

On UNFIXED code: calling with window_bbox= raises TypeError → test FAILS.
On FIXED code:   the parameter is accepted, no TypeError → test PASSES.
"""
from __future__ import annotations

import numpy as np
import pytest

from perception.ocr_helper import OCRHelper


def test_bug2_find_button_bbox_accepts_window_bbox_param() -> None:
    """Bug 2 exploration: find_button_bbox must accept window_bbox keyword argument.

    On UNFIXED code:
    - find_button_bbox() has no window_bbox parameter
    - Calling with window_bbox= raises TypeError
    - pytest.fail() is triggered → test FAILS ❌

    On FIXED code:
    - find_button_bbox(screenshot, target, window_bbox=...) is accepted
    - May return None for a blank image (no OCR text), that is fine
    - No TypeError → test PASSES ✅
    """
    ocr = OCRHelper()
    screenshot = np.zeros((600, 800, 3), dtype=np.uint8)

    try:
        result = ocr.find_button_bbox(screenshot, "安装", window_bbox=(0, 300, 800, 200))
        # If we reach here, the parameter was accepted — expected fixed behavior.
        # result may be None for a blank image; that is acceptable.
    except TypeError as e:
        pytest.fail(
            f"Bug 2 detected: find_button_bbox does not accept window_bbox parameter: {e}. "
            f"Unfixed code raises TypeError because the parameter does not exist."
        )


# ---------------------------------------------------------------------------
# Preservation tests (Task 2) — MUST PASS on unfixed code
# ---------------------------------------------------------------------------


def test_preservation_find_button_bbox_no_window_bbox_unchanged() -> None:
    """Preservation: calling without window_bbox works as before.

    **Validates: Requirements 3.3**
    """
    ocr = OCRHelper()
    screenshot = np.zeros((600, 800, 3), dtype=np.uint8)
    # This call (no window_bbox) must work on both unfixed and fixed code
    result = ocr.find_button_bbox(screenshot, "安装")
    # For a blank image, result is None — that's the baseline behavior
    assert result is None  # blank image has no OCR text
