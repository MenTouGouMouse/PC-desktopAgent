"""tests/unit/test_object_detector.py

属性测试：automation/object_detector.detect_objects_for_display

Tasks 4.4 and 4.5 of the vision-overlay spec.
调用真实的 detect_objects_for_display，只 mock 外部 I/O（_run_detection）。
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from automation.object_detector import detect_objects_for_display


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def random_screenshot(draw: st.DrawFn) -> np.ndarray:
    """生成随机 BGR uint8 截图（100×100 到 400×400）。"""
    h = draw(st.integers(min_value=100, max_value=400))
    w = draw(st.integers(min_value=100, max_value=400))
    # 使用 numpy 随机生成，避免 Hypothesis binary 策略产生过大基础样本
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    return arr


# ---------------------------------------------------------------------------
# Task 4.4 — Property 4: 检测结果结构不变式
# Validates: Requirements 2.1
# ---------------------------------------------------------------------------


@given(screenshot=random_screenshot())
@settings(max_examples=50, suppress_health_check=[HealthCheck.large_base_example])
def test_detection_result_structure(screenshot: np.ndarray) -> None:
    """**Validates: Requirements 2.1**

    对任意截图调用 detect_objects_for_display，返回列表中每个元素必须满足：
    - bbox: 长度为 4 的整数列表
    - label: 非空字符串
    - confidence: float，范围 [0.0, 1.0]
    """
    results = detect_objects_for_display(screenshot)

    assert isinstance(results, list), "返回值必须是列表"
    for item in results:
        assert isinstance(item["bbox"], list), f"bbox 必须是列表，实际: {type(item['bbox'])}"
        assert len(item["bbox"]) == 4, f"bbox 长度必须为 4，实际: {len(item['bbox'])}"
        assert all(isinstance(v, int) for v in item["bbox"]), (
            f"bbox 所有元素必须是 int，实际: {item['bbox']}"
        )
        assert isinstance(item["label"], str), f"label 必须是字符串，实际: {type(item['label'])}"
        assert len(item["label"]) > 0, "label 不能为空字符串"
        assert isinstance(item["confidence"], float), (
            f"confidence 必须是 float，实际: {type(item['confidence'])}"
        )
        assert 0.0 <= item["confidence"] <= 1.0, (
            f"confidence 必须在 [0.0, 1.0]，实际: {item['confidence']}"
        )


# ---------------------------------------------------------------------------
# Task 4.5 — Property 5: 检测异常时安全返回空列表
# Validates: Requirements 2.3
# ---------------------------------------------------------------------------


def test_detection_exception_returns_empty_list() -> None:
    """**Validates: Requirements 2.3**

    当 _run_detection 抛出异常时，detect_objects_for_display 必须：
    - 返回空列表 []
    - 不向调用方传播异常
    """
    screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
    with patch("automation.object_detector._run_detection", side_effect=RuntimeError("boom")):
        result = detect_objects_for_display(screenshot)
    assert result == [], f"异常时应返回 []，实际: {result}"
