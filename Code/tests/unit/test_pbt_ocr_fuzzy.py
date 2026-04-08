"""
Preservation Property Test — OCR 精确匹配路径在未修复代码上正常工作

这些测试在未修复代码上 MUST PASS — 记录基线行为，修复后必须保持。

Validates: Requirements 3.3
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from perception.ocr_helper import OCRHelper


def _make_screenshot() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _make_ocr_data(word: str, conf: int = 90) -> dict:
    """Build a pytesseract image_to_data dict with a single word."""
    return {
        "text": [word],
        "conf": [conf],
        "left": [10],
        "top": [20],
        "width": [40],
        "height": [20],
    }


class TestOCRExactMatchPreservationProperty:
    """Property: when target text appears exactly in an OCR word, find_text_bbox returns non-None."""

    @given(st.sampled_from(["完成", "我同意", "下一步", "安装", "取消"]))
    @settings(max_examples=20)
    def test_exact_match_returns_element_result(self, target: str) -> None:
        """
        **Validates: Requirements 3.3**

        Property: when the OCR word exactly equals the target text,
        find_text_bbox returns a non-None ElementResult.

        This is the exact-match path that works on UNFIXED code.
        """
        ocr_helper = OCRHelper()
        screenshot = _make_screenshot()
        ocr_data = _make_ocr_data(target, conf=90)

        with patch("perception.ocr_helper._preprocess", return_value=screenshot), \
             patch("pytesseract.image_to_data", return_value=ocr_data):
            result = ocr_helper.find_text_bbox(screenshot, target)

        assert result is not None, (
            f"Expected find_text_bbox to return ElementResult when OCR word '{target}' "
            f"exactly matches target '{target}', but got None."
        )
        assert result.name == target or target in result.name, (
            f"Expected result.name to contain '{target}', got '{result.name!r}'."
        )

    @given(st.sampled_from(["完成", "我同意", "下一步", "安装", "取消"]))
    @settings(max_examples=20)
    def test_exact_match_result_has_valid_bbox(self, target: str) -> None:
        """
        **Validates: Requirements 3.3**

        Property: exact-match result has a valid bbox with positive dimensions.
        """
        ocr_helper = OCRHelper()
        screenshot = _make_screenshot()
        ocr_data = _make_ocr_data(target, conf=85)

        with patch("perception.ocr_helper._preprocess", return_value=screenshot), \
             patch("pytesseract.image_to_data", return_value=ocr_data):
            result = ocr_helper.find_text_bbox(screenshot, target)

        assert result is not None
        x, y, w, h = result.bbox
        assert w > 0, f"Expected bbox width > 0, got {w}"
        assert h > 0, f"Expected bbox height > 0, got {h}"

    def test_exact_match_substring_also_works(self) -> None:
        """
        **Validates: Requirements 3.3**

        Baseline: target as substring of OCR word also matches (existing behavior).
        e.g. target="完成" found in OCR word "完成安装".
        """
        ocr_helper = OCRHelper()
        screenshot = _make_screenshot()
        # OCR word contains target as substring
        ocr_data = _make_ocr_data("完成安装", conf=80)

        with patch("perception.ocr_helper._preprocess", return_value=screenshot), \
             patch("pytesseract.image_to_data", return_value=ocr_data):
            result = ocr_helper.find_text_bbox(screenshot, "完成")

        assert result is not None, (
            "Expected find_text_bbox to return ElementResult when target '完成' "
            "is a substring of OCR word '完成安装', but got None."
        )
