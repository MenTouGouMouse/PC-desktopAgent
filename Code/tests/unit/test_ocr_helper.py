"""单元测试：perception/ocr_helper.py — OCRHelper 文本提取与区域定位。

覆盖场景：
- extract_text 正常返回识别文本
- extract_text pytesseract 异常时返回空字符串
- find_text_bbox 找到目标文本时返回 ElementResult
- find_text_bbox 未找到目标文本时返回 None
- find_text_bbox 空 target 时返回 None
- find_text_bbox pytesseract 异常时返回 None
- 预处理流程：调用 cv2.resize（2x 放大）
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Mock pytesseract before importing ocr_helper (may not be installed)
# ---------------------------------------------------------------------------
_mock_pytesseract = types.ModuleType("pytesseract")
_mock_pytesseract.Output = MagicMock()
_mock_pytesseract.Output.DICT = "dict"
_mock_pytesseract.image_to_string = MagicMock(return_value="")
_mock_pytesseract.image_to_data = MagicMock(return_value={})
# ocr_helper._configure_tesseract() accesses pytesseract.pytesseract.tesseract_cmd
_mock_pytesseract_inner = types.ModuleType("pytesseract.pytesseract")
_mock_pytesseract_inner.tesseract_cmd = "tesseract"
_mock_pytesseract.pytesseract = _mock_pytesseract_inner
sys.modules.setdefault("pytesseract", _mock_pytesseract)
sys.modules.setdefault("pytesseract.pytesseract", _mock_pytesseract_inner)

from perception.ocr_helper import OCRHelper, ElementResult  # noqa: E402


@pytest.fixture
def ocr() -> OCRHelper:
    return OCRHelper()


@pytest.fixture
def black_image() -> np.ndarray:
    """100×100 黑色 BGR 图像。"""
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_returns_recognized_text(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """pytesseract 正常返回时，extract_text 应返回识别文本。"""
        with patch("pytesseract.image_to_string", return_value="安装 Install"):
            result = ocr.extract_text(black_image)
        assert result == "安装 Install"

    def test_returns_empty_string_on_exception(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """pytesseract 抛出异常时，extract_text 应返回空字符串，不向上传播。"""
        with patch("pytesseract.image_to_string", side_effect=RuntimeError("tesseract not found")):
            result = ocr.extract_text(black_image)
        assert result == ""

    def test_calls_cv2_resize_before_ocr(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """OCR 必须先调用 cv2.resize 做 2x 放大预处理，再调用 pytesseract。"""
        with patch("cv2.resize", wraps=__import__("cv2").resize) as mock_resize, \
             patch("pytesseract.image_to_string", return_value="text"):
            ocr.extract_text(black_image)
        mock_resize.assert_called_once()
        _, kwargs = mock_resize.call_args
        # fx=2, fy=2 放大
        assert mock_resize.call_args[1].get("fx", mock_resize.call_args[0][2] if len(mock_resize.call_args[0]) > 2 else None) == 2 or \
               any(a == 2 for a in mock_resize.call_args[0])


# ---------------------------------------------------------------------------
# find_text_bbox
# ---------------------------------------------------------------------------

def _make_tesseract_data(
    texts: list[str],
    lefts: list[int] | None = None,
    tops: list[int] | None = None,
    widths: list[int] | None = None,
    heights: list[int] | None = None,
    confs: list[int] | None = None,
) -> dict:
    """构造 pytesseract.image_to_data 返回的字典格式。"""
    n = len(texts)
    return {
        "text": texts,
        "left": lefts or [10] * n,
        "top": tops or [20] * n,
        "width": widths or [40] * n,
        "height": heights or [20] * n,
        "conf": confs or [90] * n,
    }


class TestFindTextBbox:
    def test_finds_exact_match(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """目标文本精确匹配时，应返回正确的 ElementResult。"""
        data = _make_tesseract_data(
            texts=["安装"],
            lefts=[20], tops=[40], widths=[60], heights=[30], confs=[85],
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "安装")

        assert result is not None
        assert isinstance(result, ElementResult)
        assert result.strategy == "ocr"
        # 坐标应除以 2（从 2x 预处理空间还原到原始空间）
        assert result.bbox == (10, 20, 30, 15)
        assert abs(result.confidence - 0.85) < 1e-6

    def test_finds_partial_match_case_insensitive(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """目标文本大小写不敏感的部分匹配也应返回结果。"""
        data = _make_tesseract_data(texts=["Install"])
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "install")
        assert result is not None

    def test_returns_none_when_not_found(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """目标文本不在 OCR 结果中时，应返回 None。"""
        data = _make_tesseract_data(texts=["其他文字", "无关内容"])
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "安装")
        assert result is None

    def test_returns_none_for_empty_target(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """空 target 字符串时，应直接返回 None。"""
        result = ocr.find_text_bbox(black_image, "")
        assert result is None

    def test_returns_none_on_pytesseract_exception(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """pytesseract 抛出异常时，应返回 None，不向上传播。"""
        with patch("pytesseract.image_to_data", side_effect=RuntimeError("tesseract error")):
            result = ocr.find_text_bbox(black_image, "安装")
        assert result is None

    def test_skips_empty_words(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """OCR 结果中的空字符串词条应被跳过。"""
        data = _make_tesseract_data(texts=["", "  ", "安装"])
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "安装")
        assert result is not None

    def test_negative_confidence_treated_as_zero(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """pytesseract 返回 conf=-1 时，置信度应为 0.0。"""
        data = _make_tesseract_data(texts=["安装"], confs=[-1])
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "安装")
        assert result is not None
        assert result.confidence == 0.0

    def test_bbox_minimum_size_one(self, ocr: OCRHelper, black_image: np.ndarray) -> None:
        """宽高为 0 时，bbox 的 w/h 应至少为 1。"""
        data = _make_tesseract_data(
            texts=["安装"], lefts=[0], tops=[0], widths=[0], heights=[0], confs=[80]
        )
        with patch("pytesseract.image_to_data", return_value=data):
            result = ocr.find_text_bbox(black_image, "安装")
        assert result is not None
        _, _, w, h = result.bbox
        assert w >= 1
        assert h >= 1
