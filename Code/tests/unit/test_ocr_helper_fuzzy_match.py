"""
Bug Condition Exploration Test — Bug 3: OCR find_text_bbox 精确子串匹配无法处理轻微误识

这些测试在未修复代码上 MUST FAIL，失败即证明 bug 存在。
DO NOT fix the code when tests fail.

Expected outcome on UNFIXED code: FAILS
- "完成" not in "完 成" (exact substring match fails)
- find_text_bbox returns None instead of ElementResult

Validates: Requirements 1.5, 1.6
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Mock pytesseract before importing ocr_helper
# ---------------------------------------------------------------------------

def _ensure_pytesseract_mock():
    if "pytesseract" not in sys.modules:
        mock_pytesseract = types.ModuleType("pytesseract")
        mock_pytesseract.Output = MagicMock()
        mock_pytesseract.Output.DICT = "dict"
        mock_pytesseract.image_to_string = MagicMock(return_value="")
        mock_pytesseract.image_to_data = MagicMock(return_value={})
        mock_inner = types.ModuleType("pytesseract.pytesseract")
        mock_inner.tesseract_cmd = "tesseract"
        mock_pytesseract.pytesseract = mock_inner
        sys.modules["pytesseract"] = mock_pytesseract
        sys.modules["pytesseract.pytesseract"] = mock_inner


_ensure_pytesseract_mock()

from perception.ocr_helper import OCRHelper  # noqa: E402


@pytest.fixture
def ocr() -> OCRHelper:
    return OCRHelper()


@pytest.fixture
def black_image() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _make_tesseract_data(
    texts: list[str],
    lefts: list[int] | None = None,
    tops: list[int] | None = None,
    widths: list[int] | None = None,
    heights: list[int] | None = None,
    confs: list[int] | None = None,
) -> dict:
    n = len(texts)
    return {
        "text": texts,
        "left": lefts or [10] * n,
        "top": tops or [20] * n,
        "width": widths or [40] * n,
        "height": heights or [20] * n,
        "conf": confs or [90] * n,
    }


# ---------------------------------------------------------------------------
# Test: fuzzy match — "完 成" should match target "完成"
# ---------------------------------------------------------------------------

class TestFuzzyMatchWithSpace:
    def test_word_with_space_matches_target_without_space(self, ocr, black_image):
        """
        Bug condition: OCR returns "完 成" (with space) for target "完成".

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed code uses exact substring: "完成" in "完 成" → False
        - Returns None instead of ElementResult
        - Fixed code should strip spaces and match: "完成" in "完成" → True

        Counterexample: find_text_bbox returns None when OCR word is "完 成"
        """
        data = _make_tesseract_data(
            texts=["完 成"],
            lefts=[10], tops=[20], widths=[40], heights=[20], confs=[90],
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "完成")

        # FAILS on unfixed code: returns None because "完成" not in "完 成"
        assert result is not None, (
            "Expected find_text_bbox to return ElementResult when OCR word is '完 成' "
            "and target is '完成' (fuzzy match after stripping spaces), "
            "but got None. "
            "Bug: unfixed code uses exact substring match '完成' in '完 成' which fails."
        )

    def test_word_with_space_returns_correct_bbox(self, ocr, black_image):
        """
        When fuzzy match succeeds for "完 成" → "完成", bbox should be returned correctly.

        EXPECTED OUTCOME on UNFIXED code: FAILS (result is None, can't check bbox)
        """
        data = _make_tesseract_data(
            texts=["完 成"],
            lefts=[20], tops=[40], widths=[60], heights=[30], confs=[85],
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "完成")

        assert result is not None, (
            "Expected non-None result for fuzzy match '完 成' → '完成', but got None."
        )
        # Coordinates are halved (2x preprocessing space → original space)
        assert result.bbox == (10, 20, 30, 15), (
            f"Expected bbox (10, 20, 30, 15) but got {result.bbox!r}."
        )

    def test_word_with_space_in_middle_matches(self, ocr, black_image):
        """
        Bug condition: OCR returns "我同 意" for target "我同意".

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - "我同意" not in "我同 意" → exact match fails
        - Fixed code strips spaces: "我同意" in "我同意" → True
        """
        data = _make_tesseract_data(
            texts=["我同 意"],
            lefts=[10], tops=[20], widths=[40], heights=[20], confs=[88],
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "我同意")

        assert result is not None, (
            "Expected find_text_bbox to return ElementResult when OCR word is '我同 意' "
            "and target is '我同意', but got None. "
            "Bug: unfixed code exact match '我同意' in '我同 意' fails."
        )


# ---------------------------------------------------------------------------
# Test: edit distance fuzzy match
# ---------------------------------------------------------------------------

class TestEditDistanceFuzzyMatch:
    def test_single_char_substitution_matches(self, ocr, black_image):
        """
        Bug condition: OCR returns a word with edit distance 1 from target.

        EXPECTED OUTCOME on UNFIXED code: FAILS if exact match fails
        """
        # "完成" vs "完戌" — edit distance 1 (substitution)
        data = _make_tesseract_data(
            texts=["完戌"],
            lefts=[10], tops=[20], widths=[40], heights=[20], confs=[75],
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "完成")

        # This should match with edit distance <= 2
        assert result is not None, (
            "Expected find_text_bbox to return ElementResult for edit distance 1 match "
            "'完戌' → '完成', but got None. "
            "Bug: unfixed code only does exact substring match."
        )
