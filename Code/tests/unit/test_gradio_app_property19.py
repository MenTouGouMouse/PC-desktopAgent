"""Property-based tests for annotate_elements in ui/gradio_app.py.

# Feature: cv-desktop-automation-agent, Property 19: 元素标注在正确位置产生红色像素
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from perception.element_locator import ElementResult
from ui.gradio_app import annotate_elements

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Frame dimensions: keep small to stay fast, but large enough for a bbox.
_FRAME_H_ST = st.integers(min_value=60, max_value=300)
_FRAME_W_ST = st.integers(min_value=60, max_value=300)


@st.composite
def _frame_and_bbox_st(draw: st.DrawFn) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Generate a black BGR frame and a valid bbox that fits inside it."""
    h = draw(_FRAME_H_ST)
    w = draw(_FRAME_W_ST)
    # bbox must leave at least 1 pixel of margin on every side so the
    # rectangle border is fully inside the frame.
    x = draw(st.integers(min_value=1, max_value=w - 10))
    y = draw(st.integers(min_value=1, max_value=h - 10))
    bw = draw(st.integers(min_value=4, max_value=max(4, w - x - 2)))
    bh = draw(st.integers(min_value=4, max_value=max(4, h - y - 2)))
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    return frame, (x, y, bw, bh)


def _make_element(bbox: tuple[int, int, int, int]) -> ElementResult:
    return ElementResult(name="prop_test", bbox=bbox, confidence=0.9, strategy="test")


# ---------------------------------------------------------------------------
# Property 19: 元素标注在正确位置产生红色像素
# Validates: Requirements 11.4
# ---------------------------------------------------------------------------

# Feature: cv-desktop-automation-agent, Property 19: 元素标注在正确位置产生红色像素
@settings(max_examples=100)
@given(data=_frame_and_bbox_st())
def test_annotation_produces_red_pixels_on_bbox_border(
    data: tuple[np.ndarray, tuple[int, int, int, int]],
) -> None:
    """**Validates: Requirements 11.4**

    For any ElementResult with a valid bbox, annotate_elements must place at
    least one red pixel (BGR = (0, 0, 255)) on each of the four edges of the
    bounding box.
    """
    frame, bbox = data
    x, y, bw, bh = bbox
    elem = _make_element(bbox)
    result = annotate_elements(frame, [elem])

    red = np.array([0, 0, 255], dtype=np.uint8)

    # Top edge: row y, columns x..x+bw
    top = result[y, x : x + bw + 1]
    assert np.any(np.all(top == red, axis=1)), (
        f"bbox 顶边 (row={y}, cols={x}..{x+bw}) 应有红色像素，bbox={bbox}"
    )

    # Bottom edge: row y+bh, columns x..x+bw
    bottom = result[y + bh, x : x + bw + 1]
    assert np.any(np.all(bottom == red, axis=1)), (
        f"bbox 底边 (row={y+bh}, cols={x}..{x+bw}) 应有红色像素，bbox={bbox}"
    )

    # Left edge: col x, rows y..y+bh
    left = result[y : y + bh + 1, x]
    assert np.any(np.all(left == red, axis=1)), (
        f"bbox 左边 (col={x}, rows={y}..{y+bh}) 应有红色像素，bbox={bbox}"
    )

    # Right edge: col x+bw, rows y..y+bh
    right = result[y : y + bh + 1, x + bw]
    assert np.any(np.all(right == red, axis=1)), (
        f"bbox 右边 (col={x+bw}, rows={y}..{y+bh}) 应有红色像素，bbox={bbox}"
    )


# Feature: cv-desktop-automation-agent, Property 19: 元素标注在正确位置产生红色像素
@settings(max_examples=100)
@given(data=_frame_and_bbox_st())
def test_annotation_no_red_pixels_outside_bbox(
    data: tuple[np.ndarray, tuple[int, int, int, int]],
) -> None:
    """**Validates: Requirements 11.4**

    For any ElementResult, annotate_elements must not introduce red pixels
    outside the bounding box region.  The frame starts fully black, so any
    red pixel outside the bbox is a spurious annotation.
    """
    frame, bbox = data
    x, y, bw, bh = bbox
    elem = _make_element(bbox)
    result = annotate_elements(frame, [elem])

    red = np.array([0, 0, 255], dtype=np.uint8)

    # Build a mask of all red pixels in the result
    is_red = np.all(result == red, axis=2)  # shape (H, W)

    # Build a mask of the bbox region (with a small tolerance for the
    # rectangle thickness of 2 px used by cv2.rectangle)
    thickness = 2
    h_frame, w_frame = frame.shape[:2]
    bbox_mask = np.zeros((h_frame, w_frame), dtype=bool)
    r0 = max(0, y - thickness)
    r1 = min(h_frame, y + bh + thickness + 1)
    c0 = max(0, x - thickness)
    c1 = min(w_frame, x + bw + thickness + 1)
    bbox_mask[r0:r1, c0:c1] = True

    outside_red = is_red & ~bbox_mask
    assert not outside_red.any(), (
        f"bbox 外部不应有红色像素，bbox={bbox}，"
        f"发现 {outside_red.sum()} 个越界红色像素"
    )


# Feature: cv-desktop-automation-agent, Property 19: 元素标注在正确位置产生红色像素
@settings(max_examples=100)
@given(data=_frame_and_bbox_st())
def test_annotation_does_not_modify_original_frame(
    data: tuple[np.ndarray, tuple[int, int, int, int]],
) -> None:
    """**Validates: Requirements 11.4**

    annotate_elements must return a copy; the original frame must remain
    unchanged (all zeros) after the call.
    """
    frame, bbox = data
    original_copy = frame.copy()
    elem = _make_element(bbox)
    annotate_elements(frame, [elem])
    np.testing.assert_array_equal(
        frame,
        original_copy,
        err_msg="annotate_elements 不应修改原始 frame",
    )


# Feature: cv-desktop-automation-agent, Property 19: 元素标注在正确位置产生红色像素
@settings(max_examples=100)
@given(data=_frame_and_bbox_st())
def test_annotation_color_is_exactly_bgr_red(
    data: tuple[np.ndarray, tuple[int, int, int, int]],
) -> None:
    """**Validates: Requirements 11.4**

    Every pixel introduced by annotate_elements must be exactly BGR (0, 0, 255).
    No other color (e.g. green, blue, white) should appear on the border.
    """
    frame, bbox = data
    x, y, bw, bh = bbox
    elem = _make_element(bbox)
    result = annotate_elements(frame, [elem])

    # Diff: pixels that changed from the original (all-zero) frame
    changed_mask = np.any(result != frame, axis=2)  # shape (H, W)
    if not changed_mask.any():
        # No pixels changed — bbox may be degenerate; skip silently
        return

    changed_pixels = result[changed_mask]  # shape (N, 3)
    red = np.array([0, 0, 255], dtype=np.uint8)
    all_red = np.all(changed_pixels == red, axis=1)
    assert all_red.all(), (
        f"标注引入的所有像素必须为 BGR (0,0,255)，"
        f"发现非红色像素：{changed_pixels[~all_red][:5]}"
    )
