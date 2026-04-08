"""tests/unit/test_vision_box_drawer.py

属性测试 + 单元测试：automation/vision_box_drawer.py

Tasks 2.2–2.6 of the vision-overlay spec.
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from automation.vision_box_drawer import BoundingBoxDict, draw_boxes_on_image

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def random_image(draw: st.DrawFn) -> np.ndarray:
    """生成随机 BGR uint8 图像（10×10 到 200×200）。"""
    h = draw(st.integers(min_value=10, max_value=200))
    w = draw(st.integers(min_value=10, max_value=200))
    # 使用固定种子的 numpy 随机数，让 Hypothesis 可以重现
    data = draw(
        st.binary(min_size=h * w * 3, max_size=h * w * 3)
    )
    arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3).copy()
    return arr


@st.composite
def random_bbox_dict(draw: st.DrawFn, max_coord: int = 300) -> BoundingBoxDict:
    """生成随机 BoundingBoxDict，坐标可越界。"""
    x1 = draw(st.integers(min_value=-10, max_value=max_coord))
    y1 = draw(st.integers(min_value=-10, max_value=max_coord))
    x2 = draw(st.integers(min_value=x1, max_value=max_coord + 50))
    y2 = draw(st.integers(min_value=y1, max_value=max_coord + 50))
    label = draw(st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=1, max_size=20))
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    return BoundingBoxDict(bbox=[x1, y1, x2, y2], label=label, confidence=confidence)


# ---------------------------------------------------------------------------
# Task 2.2 — Property 1: 空 boxes 时输出与输入内容相同
# Validates: Requirements 1.5
# ---------------------------------------------------------------------------

@given(image=random_image())
@settings(max_examples=100)
def test_empty_boxes_returns_identical_copy(image: np.ndarray) -> None:
    """**Validates: Requirements 1.5**

    空 boxes 时 draw_boxes_on_image 必须返回与输入像素完全相同的副本，
    且返回值不是原对象（不修改原图）。
    """
    result = draw_boxes_on_image(image, [])
    assert result is not image, "必须返回副本，不能返回原图对象"
    assert np.array_equal(result, image), "空 boxes 时输出像素必须与输入完全相同"


# ---------------------------------------------------------------------------
# Task 2.3 — Property 2: 输出图像尺寸与输入相同
# Validates: Requirements 1.1, 1.6
# ---------------------------------------------------------------------------

@given(
    image=random_image(),
    boxes=st.lists(random_bbox_dict(), max_size=10),
)
@settings(max_examples=100)
def test_output_shape_equals_input_shape(image: np.ndarray, boxes: list[BoundingBoxDict]) -> None:
    """**Validates: Requirements 1.1, 1.6**

    无论 boxes 列表内容如何（含越界 bbox），输出图像的 shape 必须与输入相同。
    """
    result = draw_boxes_on_image(image, boxes)
    assert result.shape == image.shape, (
        f"输出 shape {result.shape} 与输入 shape {image.shape} 不一致"
    )


# ---------------------------------------------------------------------------
# Task 2.4 — Property 3: 置信度决定颜色选择
# Validates: Requirements 1.2, 1.3
# ---------------------------------------------------------------------------

@st.composite
def image_at_least_50x50(draw: st.DrawFn) -> np.ndarray:
    """生成尺寸 ≥ 50×50 的纯黑图像，确保颜色采样可预测。"""
    h = draw(st.integers(min_value=50, max_value=150))
    w = draw(st.integers(min_value=50, max_value=150))
    return np.zeros((h, w, 3), dtype=np.uint8)


@given(
    image=image_at_least_50x50(),
    x1=st.integers(min_value=5, max_value=30),
    y1=st.integers(min_value=5, max_value=30),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_color_selection_by_confidence(
    image: np.ndarray,
    x1: int,
    y1: int,
    confidence: float,
) -> None:
    """**Validates: Requirements 1.2, 1.3**

    在纯黑图像上绘制，矩形框顶边像素颜色由置信度三档决定：
    - confidence >= 0.8 → 绿色 BGR (0, 255, 0)
    - 0.6 <= confidence < 0.8 → 黄色 BGR (0, 255, 255)
    - confidence <  0.6 → 红色 BGR (0, 0, 255)
      （confidence_threshold=0.0 表示全部显示，不过滤）

    注：使用纯黑底图以消除半透明标签背景混合的干扰；
    采样点选在矩形框顶边中间，避开标签背景区域。
    """
    h, w = image.shape[:2]
    # 确保 bbox 完全在图像内部，且有足够宽度供采样
    x2 = min(x1 + 20, w - 2)
    y2 = min(y1 + 20, h - 2)

    # 若图像太小导致 bbox 退化，跳过（assume）
    if x2 <= x1 or y2 <= y1:
        return

    box: BoundingBoxDict = BoundingBoxDict(bbox=[x1, y1, x2, y2], label="obj", confidence=confidence)
    # confidence_threshold=0.0 确保所有框都被绘制，不因过滤而跳过
    result = draw_boxes_on_image(image, [box], confidence_threshold=0.0)

    # 采样矩形框顶边中间像素（远离左上角，避开标签背景）
    sample_x = (x1 + x2) // 2
    sample_y = y1
    pixel = tuple(int(v) for v in result[sample_y, sample_x])

    if confidence >= 0.8:
        assert pixel == (0, 255, 0), (
            f"confidence={confidence:.4f} >= 0.8，期望绿色 (0,255,0)，实际 {pixel}"
        )
    elif confidence >= 0.6:
        assert pixel == (0, 255, 255), (
            f"confidence={confidence:.4f} in [0.6,0.8)，期望黄色 (0,255,255)，实际 {pixel}"
        )
    else:
        assert pixel == (0, 0, 255), (
            f"confidence={confidence:.4f} < 0.6，期望红色 (0,0,255)，实际 {pixel}"
        )


# ---------------------------------------------------------------------------
# Task 2.5 — Property 9: show_confidence=False 时标签不含置信度数值
# Validates: Requirements 7.4
# ---------------------------------------------------------------------------

@given(
    confidence=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_show_confidence_flag_affects_output(confidence: float) -> None:
    """**Validates: Requirements 7.4**

    对同一 box 分别以 show_confidence=True 和 False 调用，
    两者绘制结果必须不同（show_confidence 参数确实影响了绘制）。
    """
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 80, 80], label="btn", confidence=confidence)

    result_with = draw_boxes_on_image(image, [box], show_confidence=True)
    result_without = draw_boxes_on_image(image, [box], show_confidence=False)

    assert not np.array_equal(result_with, result_without), (
        f"show_confidence=True 与 False 的绘制结果相同，"
        f"说明 show_confidence 参数未生效（confidence={confidence:.4f}）"
    )


# ---------------------------------------------------------------------------
# Task 2.6 — Example-based 单元测试
# Requirements: 1.1, 1.5, 1.6, 7.4
# ---------------------------------------------------------------------------

def test_draw_boxes_returns_copy_not_original() -> None:
    """验证返回副本而非原图，且原图未被修改。"""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    original_copy = image.copy()
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 50, 50], label="file", confidence=0.8)

    result = draw_boxes_on_image(image, [box])

    assert result is not image, "必须返回副本，不能是原图对象"
    assert np.array_equal(original_copy, image), "原图不应被修改"


def test_out_of_bounds_bbox_does_not_raise() -> None:
    """越界 bbox 不应抛出异常，且输出 shape 不变。"""
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[-5, -5, 200, 200], label="oob", confidence=0.9)

    result = draw_boxes_on_image(image, [box])  # 不应抛出异常

    assert result.shape == (50, 50, 3), f"越界 bbox 后 shape 变为 {result.shape}"


def test_show_confidence_false_label_has_no_confidence() -> None:
    """show_confidence=False 与 True 的绘制结果必须不同。"""
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 80, 80], label="btn", confidence=0.75)

    result_with = draw_boxes_on_image(image, [box], show_confidence=True)
    result_without = draw_boxes_on_image(image, [box], show_confidence=False)

    assert not np.array_equal(result_with, result_without), (
        "show_confidence=True 与 False 的结果相同，说明参数未生效"
    )


def test_high_confidence_color_is_green() -> None:
    """confidence=0.9 时，纯黑图像上矩形框顶边中间像素应为绿色。"""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 60, 60], label="icon", confidence=0.9)

    result = draw_boxes_on_image(image, [box], confidence_threshold=0.0)

    # 采样顶边中间像素
    sample_x = (10 + 60) // 2
    sample_y = 10
    pixel = tuple(int(v) for v in result[sample_y, sample_x])
    assert pixel == (0, 255, 0), f"高置信度(0.9)期望绿色 (0,255,0)，实际 {pixel}"


def test_mid_confidence_color_is_yellow() -> None:
    """confidence=0.7 时，纯黑图像上矩形框顶边中间像素应为黄色。"""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 60, 60], label="icon", confidence=0.7)

    result = draw_boxes_on_image(image, [box], confidence_threshold=0.0)

    sample_x = (10 + 60) // 2
    sample_y = 10
    pixel = tuple(int(v) for v in result[sample_y, sample_x])
    assert pixel == (0, 255, 255), f"中置信度(0.7)期望黄色 (0,255,255)，实际 {pixel}"


def test_low_confidence_color_is_red() -> None:
    """confidence=0.1 时，纯黑图像上矩形框顶边中间像素应为红色。"""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 60, 60], label="btn", confidence=0.1)

    result = draw_boxes_on_image(image, [box], confidence_threshold=0.0)

    sample_x = (10 + 60) // 2
    sample_y = 10
    pixel = tuple(int(v) for v in result[sample_y, sample_x])
    assert pixel == (0, 0, 255), f"低置信度(0.1)期望红色 (0,0,255)，实际 {pixel}"


def test_confidence_threshold_filters_low_confidence_box() -> None:
    """confidence < threshold 时，框应被过滤，图像保持全黑。"""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    box: BoundingBoxDict = BoundingBoxDict(bbox=[10, 10, 60, 60], label="btn", confidence=0.1)

    result = draw_boxes_on_image(image, [box], confidence_threshold=0.5)

    # 低于阈值的框被过滤，图像应保持全黑
    assert np.array_equal(result, image), "低于 threshold 的框应被过滤，图像应保持不变"
