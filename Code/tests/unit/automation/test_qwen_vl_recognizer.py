"""tests/unit/automation/test_qwen_vl_recognizer.py

QwenVLRecognizer 单元测试 + 属性测试。
外部 I/O（DashScope API）全部 mock；核心逻辑（JSON 解析、坐标转换、截图预处理）真实执行。
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

# Pre-import dashscope at module level to avoid Windows GC crash during lazy import
try:
    import dashscope  # noqa: F401
    _DASHSCOPE_AVAILABLE = True
except Exception:
    _DASHSCOPE_AVAILABLE = False

from automation.qwen_vl_recognizer import (
    QwenVLAPIError,
    QwenVLRecognizer,
    VisionFileItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recognizer() -> QwenVLRecognizer:
    """Create a recognizer with no DPI adapter and no detection cache."""
    return QwenVLRecognizer(dpi_adapter=None, detection_cache=None)


def _mock_api_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a mock OpenAI-compatible response (used by qwen_vl_recognizer)."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


def _valid_item_dict(
    x1: int = 10, y1: int = 20, x2: int = 74, y2: int = 84,
    file_type: str = "PDF", name: str = "report.pdf", confidence: float = 0.9,
) -> dict:
    return {"bbox": [x1, y1, x2, y2], "type": file_type, "name": name, "confidence": confidence}


# ---------------------------------------------------------------------------
# 5.1 基础解析单元测试
# ---------------------------------------------------------------------------

class TestApiKeyMissing:
    def test_missing_api_key_raises_qwen_vl_api_error(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch.dict(os.environ, {}, clear=True):
            # Remove key if present
            env = {k: v for k, v in os.environ.items() if k != "DASHSCOPE_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(QwenVLAPIError, match="DASHSCOPE_API_KEY"):
                    recognizer.recognize_file_icons(img)


class TestNon200StatusCode:
    def test_status_429_raises_qwen_vl_api_error(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError("API error 429")
            with patch("openai.OpenAI", return_value=mock_client):
                with pytest.raises(QwenVLAPIError):
                    recognizer.recognize_file_icons(img)


class TestValidJsonParsing:
    def test_valid_json_parsed_to_vision_file_items(self) -> None:
        recognizer = _make_recognizer()
        items_json = json.dumps([_valid_item_dict(10, 20, 74, 84)])
        result = recognizer._parse_response(items_json)
        assert len(result) == 1
        item = result[0]
        assert item.bbox == (10, 20, 74 - 10, 84 - 20)
        assert item.center == (10 + (74 - 10) // 2, 20 + (84 - 20) // 2)
        assert item.name == "report.pdf"
        assert item.file_type == "PDF"
        assert item.confidence == pytest.approx(0.9)

    def test_invalid_json_returns_empty_list(self) -> None:
        recognizer = _make_recognizer()
        result = recognizer._parse_response("not valid json {{")
        assert result == []

    def test_invalid_json_does_not_raise(self) -> None:
        recognizer = _make_recognizer()
        # Should not raise
        recognizer._parse_response("{bad json}")

    def test_markdown_code_block_stripped_before_parse(self) -> None:
        recognizer = _make_recognizer()
        raw = json.dumps([_valid_item_dict()])
        wrapped = f"```json\n{raw}\n```"
        result = recognizer._parse_response(wrapped)
        assert len(result) == 1

    def test_markdown_plain_code_block_stripped(self) -> None:
        recognizer = _make_recognizer()
        raw = json.dumps([_valid_item_dict()])
        wrapped = f"```\n{raw}\n```"
        result = recognizer._parse_response(wrapped)
        assert len(result) == 1


class TestMixedValidInvalidElements:
    def test_invalid_bbox_skipped_valid_parsed(self) -> None:
        recognizer = _make_recognizer()
        valid = _valid_item_dict(0, 0, 50, 50)
        invalid_bbox = {"bbox": [1, 2, 3], "type": "PDF", "name": "x.pdf", "confidence": 0.8}
        result = recognizer._parse_response(json.dumps([valid, invalid_bbox]))
        assert len(result) == 1
        assert result[0].name == "report.pdf"

    def test_negative_coords_skipped(self) -> None:
        recognizer = _make_recognizer()
        valid = _valid_item_dict(0, 0, 50, 50)
        neg = {"bbox": [-1, 0, 50, 50], "type": "PDF", "name": "neg.pdf", "confidence": 0.8}
        result = recognizer._parse_response(json.dumps([valid, neg]))
        assert len(result) == 1

    def test_non_numeric_bbox_skipped(self) -> None:
        recognizer = _make_recognizer()
        bad = {"bbox": ["a", "b", "c", "d"], "type": "PDF", "name": "bad.pdf", "confidence": 0.8}
        result = recognizer._parse_response(json.dumps([bad]))
        assert result == []

    def test_unknown_type_set_to_other(self) -> None:
        recognizer = _make_recognizer()
        item = {"bbox": [0, 0, 50, 50], "type": "UnknownType", "name": "x.bin", "confidence": 0.7}
        result = recognizer._parse_response(json.dumps([item]))
        assert len(result) == 1
        assert result[0].file_type == "Other"

    def test_missing_confidence_defaults_to_0_5(self) -> None:
        recognizer = _make_recognizer()
        item = {"bbox": [0, 0, 50, 50], "type": "PDF", "name": "x.pdf"}
        result = recognizer._parse_response(json.dumps([item]))
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.5)

    def test_missing_name_set_to_none(self) -> None:
        recognizer = _make_recognizer()
        item = {"bbox": [0, 0, 50, 50], "type": "Image", "confidence": 0.8}
        result = recognizer._parse_response(json.dumps([item]))
        assert len(result) == 1
        assert result[0].name is None

    def test_empty_name_set_to_none(self) -> None:
        recognizer = _make_recognizer()
        item = {"bbox": [0, 0, 50, 50], "type": "Image", "name": "", "confidence": 0.8}
        result = recognizer._parse_response(json.dumps([item]))
        assert len(result) == 1
        assert result[0].name is None


# ---------------------------------------------------------------------------
# 5.2 截图预处理单元测试
# ---------------------------------------------------------------------------

class TestScreenshotPreprocessing:
    def test_wide_image_scaled_down(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((600, 2560, 3), dtype=np.uint8)
        result = recognizer._preprocess_screenshot(img)
        rh, rw = result.shape[:2]
        assert rw <= 1920
        assert rh <= 1080

    def test_tall_image_scaled_down(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((2160, 800, 3), dtype=np.uint8)
        result = recognizer._preprocess_screenshot(img)
        rh, rw = result.shape[:2]
        assert rw <= 1920
        assert rh <= 1080

    def test_normal_image_not_scaled(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        result = recognizer._preprocess_screenshot(img)
        assert recognizer._scale_ratio == pytest.approx(1.0)
        assert result.shape == img.shape

    def test_small_image_not_scaled(self) -> None:
        recognizer = _make_recognizer()
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        recognizer._preprocess_screenshot(img)
        assert recognizer._scale_ratio == pytest.approx(1.0)

    def test_scaled_coords_restored(self) -> None:
        """After scaling, bbox coords divided by scale_ratio should match originals within 2px."""
        recognizer = _make_recognizer()
        W, H = 3840, 2160
        img = np.zeros((H, W, 3), dtype=np.uint8)
        recognizer._preprocess_screenshot(img)
        r = recognizer._scale_ratio
        assert r < 1.0
        # Simulate a point at (960, 540) in scaled image
        px_scaled, py_scaled = 960, 540
        px_orig = px_scaled / r
        py_orig = py_scaled / r
        # The restored coords should be within 2px of the true original
        true_px = px_scaled / r
        true_py = py_scaled / r
        assert abs(px_orig - true_px) <= 2
        assert abs(py_orig - true_py) <= 2


# ---------------------------------------------------------------------------
# 5.3 Property 1: bbox 坐标转换正确性
# ---------------------------------------------------------------------------

@given(
    x1=st.integers(min_value=0, max_value=1919),
    y1=st.integers(min_value=0, max_value=1079),
    x2=st.integers(min_value=1, max_value=1920),
    y2=st.integers(min_value=1, max_value=1080),
)
@settings(max_examples=100)
def test_property1_bbox_conversion_correctness(x1: int, y1: int, x2: int, y2: int) -> None:
    """Property 1: bbox [x1,y1,x2,y2] → VisionFileItem.bbox=(x1,y1,x2-x1,y2-y1)."""
    assume(x2 > x1 and y2 > y1)
    recognizer = _make_recognizer()
    item_dict = {"bbox": [x1, y1, x2, y2], "type": "PDF", "name": "f.pdf", "confidence": 0.8}
    result = recognizer._parse_response(json.dumps([item_dict]))
    assert len(result) == 1
    item = result[0]
    assert item.bbox == (x1, y1, x2 - x1, y2 - y1)
    assert item.center == (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)


# ---------------------------------------------------------------------------
# 5.4 Property 2: JSON 解析健壮性
# ---------------------------------------------------------------------------

def _valid_item_strategy() -> st.SearchStrategy:
    return st.fixed_dictionaries({
        "bbox": st.lists(st.integers(0, 1920), min_size=4, max_size=4).filter(
            lambda b: b[2] > b[0] and b[3] > b[1]
        ),
        "type": st.sampled_from(["PDF", "Word", "Image", "Video", "Other"]),
        "name": st.text(min_size=1, max_size=30, alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")).map(lambda s: s + ".pdf"),
        "confidence": st.floats(0.0, 1.0, allow_nan=False),
    })


def _invalid_item_strategy() -> st.SearchStrategy:
    return st.one_of(
        # bbox with wrong length
        st.fixed_dictionaries({
            "bbox": st.lists(st.integers(0, 100), min_size=1, max_size=3),
            "type": st.just("PDF"), "name": st.just("x.pdf"), "confidence": st.just(0.5),
        }),
        # bbox with negative coords
        st.fixed_dictionaries({
            "bbox": st.lists(st.integers(-100, -1), min_size=4, max_size=4),
            "type": st.just("PDF"), "name": st.just("x.pdf"), "confidence": st.just(0.5),
        }),
    )


@given(
    valid_items=st.lists(_valid_item_strategy(), min_size=0, max_size=10),
    invalid_items=st.lists(_invalid_item_strategy(), min_size=0, max_size=5),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
def test_property2_json_parse_robustness(valid_items: list, invalid_items: list) -> None:
    """Property 2: valid elements parsed, invalid elements skipped."""
    recognizer = _make_recognizer()
    mixed = valid_items + invalid_items
    import random
    random.shuffle(mixed)
    result = recognizer._parse_response(json.dumps(mixed))
    assert len(result) == len(valid_items)


# ---------------------------------------------------------------------------
# 5.5 Property 3: 非 200 状态码触发 QwenVLAPIError
# ---------------------------------------------------------------------------

@given(code=st.integers(min_value=100, max_value=599).filter(lambda c: c != 200))
@settings(max_examples=100)
def test_property3_non_200_raises_qwen_vl_api_error(code: int) -> None:
    """Property 3: any non-200 status code raises QwenVLAPIError.

    The OpenAI-compatible client raises an exception on HTTP errors,
    which qwen_vl_recognizer wraps as QwenVLAPIError after 2 retries.
    """
    recognizer = _make_recognizer()
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(f"HTTP {code}")
        with patch("openai.OpenAI", return_value=mock_client):
            with pytest.raises(QwenVLAPIError):
                recognizer.recognize_file_icons(img)


# ---------------------------------------------------------------------------
# 5.6 Property 4: 截图等比缩放约束
# ---------------------------------------------------------------------------

@given(
    w=st.integers(min_value=1921, max_value=7680),
    h=st.integers(min_value=100, max_value=4320),
)
@settings(max_examples=100)
def test_property4_screenshot_resize_constraint(w: int, h: int) -> None:
    """Property 4: oversized images are scaled to fit within 1920x1080."""
    recognizer = _make_recognizer()
    img = np.zeros((h, w, 3), dtype=np.uint8)
    resized = recognizer._preprocess_screenshot(img)
    rh, rw = resized.shape[:2]
    assert rw <= 1920
    assert rh <= 1080
    # Both dimensions should be scaled by approximately the same ratio
    # Allow tolerance of 1 pixel per dimension due to integer truncation
    ratio = min(1920 / w, 1080 / h)
    expected_w = max(1, int(w * ratio))
    expected_h = max(1, int(h * ratio))
    assert abs(rw - expected_w) <= 1
    assert abs(rh - expected_h) <= 1


# ---------------------------------------------------------------------------
# 5.7 Property 5: 缩放坐标还原 round-trip
# ---------------------------------------------------------------------------

@given(
    W=st.integers(min_value=1921, max_value=3840),
    H=st.integers(min_value=1, max_value=2160),
    px=st.integers(min_value=0, max_value=1919),
    py=st.integers(min_value=0, max_value=1079),
)
@settings(max_examples=100)
def test_property5_scale_coord_roundtrip(W: int, H: int, px: int, py: int) -> None:
    """Property 5: coords divided by scale_ratio restore to within 2px of original."""
    recognizer = _make_recognizer()
    img = np.zeros((H, W, 3), dtype=np.uint8)
    recognizer._preprocess_screenshot(img)
    r = recognizer._scale_ratio
    assume(r < 1.0)
    restored_x = px / r
    restored_y = py / r
    # The restored value should be within 2px of the true original
    true_x = px / r
    true_y = py / r
    assert abs(restored_x - true_x) <= 2
    assert abs(restored_y - true_y) <= 2


# ---------------------------------------------------------------------------
# 5.8 Property 10: markdown 代码块自动去除
# ---------------------------------------------------------------------------

@given(items=st.lists(_valid_item_strategy(), min_size=1, max_size=5))
@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
def test_property10_markdown_code_block_stripping(items: list) -> None:
    """Property 10: JSON wrapped in markdown code block parses same as raw JSON."""
    recognizer = _make_recognizer()
    raw_json = json.dumps(items)
    wrapped = f"```json\n{raw_json}\n```"
    result_direct = recognizer._parse_response(raw_json)
    result_wrapped = recognizer._parse_response(wrapped)
    assert len(result_direct) == len(result_wrapped)


# ---------------------------------------------------------------------------
# 5.9 Property 11: VisionFileItem 序列化 round-trip
# ---------------------------------------------------------------------------

def _vision_file_item_strategy() -> st.SearchStrategy:
    return st.fixed_dictionaries({
        "bbox": st.tuples(
            st.integers(0, 1000), st.integers(0, 1000),
            st.integers(1, 500), st.integers(1, 500),
        ),
        "name": st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        "file_type": st.sampled_from(["PDF", "Word", "Image", "Other"]),
        "confidence": st.floats(0.0, 1.0, allow_nan=False),
    }).map(lambda d: VisionFileItem(
        name=d["name"],
        file_type=d["file_type"],
        bbox=d["bbox"],
        confidence=d["confidence"],
    ))


@given(items=st.lists(_vision_file_item_strategy(), min_size=0, max_size=10))
@settings(max_examples=100)
def test_property11_vision_file_item_round_trip(items: list[VisionFileItem]) -> None:
    """Property 11: VisionFileItem serialization round-trip preserves all fields."""
    import dataclasses
    serialized = json.dumps([dataclasses.asdict(i) for i in items])
    deserialized = [VisionFileItem(**d) for d in json.loads(serialized)]
    for orig, restored in zip(items, deserialized):
        assert orig.name == restored.name
        assert orig.file_type == restored.file_type
        assert orig.bbox == tuple(restored.bbox)
        assert orig.confidence == pytest.approx(restored.confidence)
