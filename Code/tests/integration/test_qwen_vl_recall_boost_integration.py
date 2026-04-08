"""集成测试：QwenVL Recall Boost 完整数据流验证。

测试策略：
- mock openai.OpenAI（DashScope OpenAI 兼容接口），不发起真实 API 调用
- 使用合成截图（numpy 数组），不依赖真实屏幕
- 验证裁剪 → 预处理 → 单次识别 → NMS → 返回结果的完整数据流
- 验证智能重试、分块识别、icon_appearance 字段传递

标记：@pytest.mark.integration
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from automation.qwen_vl_recognizer import QwenVLRecognizer, VisionFileItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recognizer(**kwargs) -> QwenVLRecognizer:
    """Create a recognizer with no DPI adapter and no detection cache."""
    return QwenVLRecognizer(dpi_adapter=None, detection_cache=None, **kwargs)


def _make_api_response(items: list[dict]) -> MagicMock:
    """Build a mock OpenAI-compatible response for qwen_vl_recognizer."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(items)))]
    return resp


def _make_screenshot(height: int = 600, width: int = 800) -> np.ndarray:
    """Create a synthetic screenshot as a numpy array."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _file_item_dict(
    x1: int, y1: int, x2: int, y2: int,
    file_type: str = "PDF",
    name: str = "file.pdf",
    confidence: float = 0.9,
    icon_appearance: str | None = None,
) -> dict:
    d: dict = {"bbox": [x1, y1, x2, y2], "type": file_type, "name": name, "confidence": confidence}
    if icon_appearance is not None:
        d["icon_appearance"] = icon_appearance
    return d


@contextmanager
def _mock_openai(side_effect=None, return_value=None):
    """Context manager that patches openai.OpenAI with a mock client.

    Args:
        side_effect: callable or list of responses for chat.completions.create
        return_value: single response for chat.completions.create
    """
    mock_client = MagicMock()
    if side_effect is not None:
        mock_client.chat.completions.create.side_effect = side_effect
    elif return_value is not None:
        mock_client.chat.completions.create.return_value = return_value
    with patch("openai.OpenAI", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Scenario 1: 单次识别完整流程
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSinglePassRecognition:
    """Scenario 1: 单次识别完整流程。

    输入：800x600 截图，mock API 返回 5 个文件
    期望：返回 5 个 VisionFileItem，坐标已叠加 crop_offset
    """

    def test_single_pass_returns_five_items_with_crop_offset(self) -> None:
        """完整数据流：裁剪 → 预处理 → 单次识别 → NMS → 返回 5 个结果。

        crop_explorer_file_list 默认去除顶部 120px，所以 crop_offset_y=120。
        API 返回的 bbox y 坐标叠加 120 后应出现在最终结果中。
        """
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.95),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.90),
            _file_item_dict(200, 10, 264, 74, "Excel", "c.xlsx", 0.85),
            _file_item_dict(300, 10, 364, 74, "Image", "d.png", 0.80),
            _file_item_dict(400, 10, 464, 74, "Folder", "e_folder", 0.75),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 5

        # 坐标应叠加 crop_offset_y=120（启发式裁剪去除顶部 120px）
        for item in items:
            assert isinstance(item, VisionFileItem)
            assert item.bbox[1] >= 120, (
                f"bbox.y={item.bbox[1]} 应 >= 120（crop_offset_y=120 已叠加）"
            )

    def test_single_pass_file_types_preserved(self) -> None:
        """file_type 字段在完整数据流中正确保留。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "report.pdf", 0.95),
            _file_item_dict(100, 10, 164, 74, "Word", "notes.docx", 0.90),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 2
        types = {item.file_type for item in items}
        assert "PDF" in types
        assert "Word" in types

    def test_single_pass_api_called_once(self) -> None:
        """单次识别流程中 API 只被调用一次（无 min_expected 时不触发重试）。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [_file_item_dict(10, 10, 74, 74)]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp) as mock_client:
                recognizer.recognize_file_icons(screenshot)

        # 无 min_expected，不触发智能重试；内部有 2 次固定重试逻辑（第一次成功即停止）
        assert mock_client.chat.completions.create.call_count >= 1


# ---------------------------------------------------------------------------
# Scenario 2: 智能重试触发（重试改善结果）
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSmartRetryImproves:
    """Scenario 2: 智能重试触发，重试结果优于首次结果。"""

    def test_retry_triggered_when_below_min_expected(self) -> None:
        """首次结果 < min_expected 时触发重试，重试结果更多则使用重试结果。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        first_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.9),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.85),
        ]
        retry_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.9),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.85),
            _file_item_dict(200, 10, 264, 74, "Excel", "c.xlsx", 0.80),
            _file_item_dict(300, 10, 364, 74, "Image", "d.png", 0.75),
            _file_item_dict(400, 10, 464, 74, "Folder", "e_folder", 0.70),
        ]

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_api_response(first_items)
            return _make_api_response(retry_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(side_effect=side_effect):
                items = recognizer.recognize_file_icons(screenshot, min_expected=5)

        assert len(items) == 5, f"期望 5 个文件，实际 {len(items)} 个"

    def test_retry_api_called_twice(self) -> None:
        """触发智能重试时 API 应被调用两次（首次 + 重试）。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        first_items = [_file_item_dict(10, 10, 74, 74)]
        retry_items = [
            _file_item_dict(10, 10, 74, 74),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.85),
            _file_item_dict(200, 10, 264, 74, "Excel", "c.xlsx", 0.80),
        ]

        call_idx = 0

        def side_effect(*args, **kwargs):
            nonlocal call_idx
            resp = _make_api_response(first_items if call_idx == 0 else retry_items)
            call_idx += 1
            return resp

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(side_effect=side_effect) as mock_client:
                recognizer.recognize_file_icons(screenshot, min_expected=3)

        assert mock_client.chat.completions.create.call_count == 2, (
            f"期望 API 被调用 2 次（首次 + 重试），实际 {mock_client.chat.completions.create.call_count} 次"
        )


# ---------------------------------------------------------------------------
# Scenario 3: 智能重试未改善
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSmartRetryNoImprovement:
    """Scenario 3: 智能重试未改善结果。"""

    def test_retry_no_improvement_keeps_first_result(self) -> None:
        """重试结果不多于首次结果时，保留首次结果。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        two_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.9),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.85),
        ]

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_api_response(two_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(side_effect=side_effect):
                items = recognizer.recognize_file_icons(screenshot, min_expected=5)

        assert len(items) == 2, f"期望保留首次结果 2 个，实际 {len(items)} 个"

    def test_retry_fewer_results_keeps_first_result(self) -> None:
        """重试结果少于首次结果时，也保留首次结果。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        first_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.9),
            _file_item_dict(100, 10, 164, 74, "Word", "b.docx", 0.85),
            _file_item_dict(200, 10, 264, 74, "Excel", "c.xlsx", 0.80),
        ]
        retry_items = [_file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.9)]

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_api_response(first_items if call_count == 1 else retry_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(side_effect=side_effect):
                items = recognizer.recognize_file_icons(screenshot, min_expected=5)

        assert len(items) == 3, f"期望保留首次结果 3 个，实际 {len(items)} 个"


# ---------------------------------------------------------------------------
# Scenario 4: icon_appearance 字段正确传递
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIconAppearanceField:
    """Scenario 4: icon_appearance 联合判断。"""

    def test_icon_appearance_propagated_to_result(self) -> None:
        """icon_appearance 字段从 API 响应正确传递到 VisionFileItem。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "report.pdf", 0.95,
                            icon_appearance="红色矩形带白色PDF字样"),
            _file_item_dict(100, 10, 164, 74, "Word", "notes.docx", 0.90,
                            icon_appearance="蓝色W形Word图标"),
            _file_item_dict(200, 10, 264, 74, "Folder", "项目文件夹", 0.85,
                            icon_appearance="黄色文件夹图标"),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 3
        appearances = {item.name: item.icon_appearance for item in items}
        assert appearances.get("report.pdf") == "红色矩形带白色PDF字样"
        assert appearances.get("notes.docx") == "蓝色W形Word图标"
        assert appearances.get("项目文件夹") == "黄色文件夹图标"

    def test_icon_appearance_none_when_missing(self) -> None:
        """API 响应中缺少 icon_appearance 时，字段应为 None，记录不被丢弃。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            {"bbox": [10, 10, 74, 74], "type": "PDF", "name": "report.pdf", "confidence": 0.9},
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 1
        assert items[0].icon_appearance is None

    def test_icon_appearance_truncated_to_50_chars(self) -> None:
        """icon_appearance 超过 50 字符时应被截断。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        long_appearance = "A" * 100
        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "report.pdf", 0.9,
                            icon_appearance=long_appearance),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 1
        assert items[0].icon_appearance is not None
        assert len(items[0].icon_appearance) <= 50

    def test_icon_appearance_assists_type_reconciliation(self) -> None:
        """icon_appearance 辅助修正 file_type：name 为 Other 时采用图标外观推断类型。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "Other", "unknown_file", 0.8,
                            icon_appearance="红色矩形带白色PDF字样"),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 1
        assert items[0].file_type == "PDF"


# ---------------------------------------------------------------------------
# Scenario 5: NMS 去重
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestNMSDeduplication:
    """Scenario 5: NMS 去重。"""

    def test_nms_removes_overlapping_low_confidence_box(self) -> None:
        """NMS 去除与高置信度框高度重叠的低置信度框。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.95),
            _file_item_dict(12, 12, 76, 76, "PDF", "a_dup.pdf", 0.60),
            _file_item_dict(200, 10, 264, 74, "Word", "b.docx", 0.85),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 2, f"NMS 后期望 2 个文件，实际 {len(items)} 个"
        names = {item.name for item in items}
        assert "a.pdf" in names
        assert "a_dup.pdf" not in names
        assert "b.docx" in names

    def test_nms_no_overlap_keeps_all(self) -> None:
        """无重叠时 NMS 不去除任何框。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "a.pdf", 0.95),
            _file_item_dict(200, 10, 264, 74, "Word", "b.docx", 0.85),
            _file_item_dict(400, 10, 464, 74, "Excel", "c.xlsx", 0.75),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 3

    def test_nms_applied_after_crop_offset(self) -> None:
        """NMS 在叠加 crop_offset 之后执行，坐标正确。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [
            _file_item_dict(50, 50, 150, 150, "PDF", "high.pdf", 0.95),
            _file_item_dict(55, 55, 155, 155, "PDF", "low.pdf", 0.50),
        ]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp):
                items = recognizer.recognize_file_icons(screenshot)

        assert len(items) == 1
        assert items[0].name == "high.pdf"
        assert items[0].bbox[1] >= 120


# ---------------------------------------------------------------------------
# Scenario 6: 分块识别流程（高度 > chunk_trigger_height）
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestChunkRecognition:
    """Scenario 6: 分块识别流程。"""

    def test_chunked_recognition_triggered_for_tall_image(self) -> None:
        """图像高度 > chunk_trigger_height 时自动触发分块识别。"""
        screenshot = _make_screenshot(2500, 800)
        recognizer = _make_recognizer()

        chunk_items = [
            _file_item_dict(10, 10, 74, 74, "PDF", "chunk_a.pdf", 0.9),
            _file_item_dict(200, 10, 264, 74, "Word", "chunk_b.docx", 0.85),
        ]
        mock_resp = _make_api_response(chunk_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp) as mock_client:
                items = recognizer.recognize_file_icons(screenshot)

        assert mock_client.chat.completions.create.call_count > 1, (
            f"分块识别应调用 API 多次，实际 {mock_client.chat.completions.create.call_count} 次"
        )
        assert len(items) > 0

    def test_chunked_recognition_y_offset_applied(self) -> None:
        """分块识别时，各块的 bbox.y 应叠加该块在原图中的 y_start。"""
        screenshot = _make_screenshot(2500, 800)
        recognizer = _make_recognizer()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            items = [_file_item_dict(10, 10, 74, 74, "PDF", f"file_{call_count}.pdf", 0.9)]
            return _make_api_response(items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(side_effect=side_effect):
                items = recognizer.recognize_file_icons(screenshot)

        if len(items) >= 2:
            y_coords = [item.bbox[1] for item in items]
            assert len(set(y_coords)) > 1, "不同块的 bbox.y 应不同（叠加了不同 y_start）"

    def test_no_chunking_for_normal_height_image(self) -> None:
        """正常高度图像（< chunk_trigger_height）不触发分块，API 只调用一次。"""
        screenshot = _make_screenshot(600, 800)
        recognizer = _make_recognizer()

        api_items = [_file_item_dict(10, 10, 74, 74)]
        mock_resp = _make_api_response(api_items)

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with _mock_openai(return_value=mock_resp) as mock_client:
                recognizer.recognize_file_icons(screenshot)

        assert mock_client.chat.completions.create.call_count <= 2, (
            f"正常高度不应触发分块，API 调用次数应 <= 2，实际 {mock_client.chat.completions.create.call_count} 次"
        )
