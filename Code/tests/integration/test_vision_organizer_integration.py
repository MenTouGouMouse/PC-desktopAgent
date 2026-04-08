"""视觉文件整理器集成测试：感知层 → 执行层坐标传递验证。

测试策略：
- 用 cv2 真实绘制包含文件图标和文件名的测试图像作为 fixture
- 使用真实 VisionFileLocator、真实 ActionEngine、真实 DPIAdapter
- 只 mock pyautogui（操作真实鼠标）和 ScreenCapturer.capture_region（依赖真实屏幕）
- 验证坐标在层间传递时保持逻辑坐标，仅在 ActionEngine 内部转换为物理坐标

Requirements: 7.1, 7.2, 7.3
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from automation.vision_file_locator import FileIconResult, VisionFileLocator
from automation.vision_file_mover import VisionFileMover
from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter, MonitorInfo

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "screenshots"
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "automation" / "templates"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(scale: float, left: int = 0, top: int = 0) -> DPIAdapter:
    """Create a DPIAdapter with a single mocked monitor at the given scale/offset."""
    monitor = MonitorInfo(index=0, left=left, top=top, scale_factor=scale)
    adapter = DPIAdapter.__new__(DPIAdapter)
    adapter._monitors = [monitor]
    adapter.scale_factor = scale
    return adapter


def _make_file_listing_image(
    icon_x: int = 50,
    icon_y: int = 30,
    icon_w: int = 32,
    icon_h: int = 32,
    label: str = "doc.pdf",
    img_w: int = 400,
    img_h: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """用 cv2 绘制包含一个文件图标和文件名的测试图像。

    Returns:
        (screenshot, template) — 截图和从截图裁剪出的图标模板
    """
    # Light gray background
    img = np.ones((img_h, img_w, 3), dtype=np.uint8) * 220

    # Draw icon: solid blue rectangle
    cv2.rectangle(img, (icon_x, icon_y), (icon_x + icon_w, icon_y + icon_h), (200, 100, 50), -1)
    cv2.rectangle(img, (icon_x, icon_y), (icon_x + icon_w, icon_y + icon_h), (150, 70, 20), 1)

    # Draw filename below icon
    text_y = icon_y + icon_h + 14
    cv2.putText(
        img, label,
        (icon_x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (30, 30, 30), 1,
    )

    # Crop template from the icon region
    template = img[icon_y:icon_y + icon_h, icon_x:icon_x + icon_w].copy()

    return img, template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def file_listing_screenshot() -> tuple[np.ndarray, np.ndarray, dict]:
    """生成包含文件图标的测试截图和对应模板。

    Returns:
        (screenshot, template, icon_info) where icon_info has icon position details
    """
    icon_x, icon_y, icon_w, icon_h = 50, 30, 32, 32
    screenshot, template = _make_file_listing_image(
        icon_x=icon_x, icon_y=icon_y, icon_w=icon_w, icon_h=icon_h,
        label="doc.pdf",
    )
    icon_info = {"x": icon_x, "y": icon_y, "w": icon_w, "h": icon_h}
    return screenshot, template, icon_info


@pytest.fixture(scope="module")
def template_file(file_listing_screenshot: tuple) -> Path:
    """将模板图像保存到 automation/templates/file_icon.png 供 VisionFileLocator 使用。"""
    _, template, _ = file_listing_screenshot
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    template_path = TEMPLATES_DIR / "file_icon.png"
    success, buf = cv2.imencode(".png", template)
    assert success, "模板图像编码失败"
    template_path.write_bytes(buf.tobytes())
    return template_path


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestVisionLocatorCoordinates:
    """验证 VisionFileLocator 返回正确的逻辑坐标。

    Validates: Requirements 7.1, 7.4
    """

    def test_locator_returns_nonnegative_logical_coords_with_scale_1x(
        self,
        file_listing_screenshot: tuple,
        template_file: Path,
    ) -> None:
        """scale=1.0 时，返回的 FileIconResult.center 应为非负整数元组（逻辑坐标）。

        若 VisionFileLocator 没有正确解析模板匹配结果，返回列表为空，测试失败。
        """
        screenshot, _, icon_info = file_listing_screenshot
        adapter = _make_adapter(scale=1.0)
        locator = VisionFileLocator(
            ocr_confidence_threshold=0.0,  # accept any OCR result
            dpi_adapter=adapter,
        )

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(locator._capturer, "capture_region", return_value=screenshot),
        ):
            results = locator.get_file_icons_and_names(region=(0, 0, 400, 200))

        assert len(results) >= 1, "应至少识别到一个图标"
        for r in results:
            assert isinstance(r.center, tuple) and len(r.center) == 2
            assert r.center[0] >= 0 and r.center[1] >= 0, f"center 坐标不应为负: {r.center}"
            assert isinstance(r.bbox, tuple) and len(r.bbox) == 4
            assert all(v >= 0 for v in r.bbox), f"bbox 坐标不应为负: {r.bbox}"

    def test_locator_center_matches_icon_position_within_tolerance(
        self,
        file_listing_screenshot: tuple,
        template_file: Path,
    ) -> None:
        """返回的 center 应与图标实际绘制位置误差 ≤ 5px。

        若 VisionFileLocator 的模板匹配坐标计算有误，此测试失败。
        """
        screenshot, _, icon_info = file_listing_screenshot
        ix, iy, iw, ih = icon_info["x"], icon_info["y"], icon_info["w"], icon_info["h"]
        expected_cx = ix + iw // 2
        expected_cy = iy + ih // 2

        adapter = _make_adapter(scale=1.0)
        locator = VisionFileLocator(
            ocr_confidence_threshold=0.0,
            dpi_adapter=adapter,
        )

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(locator._capturer, "capture_region", return_value=screenshot),
        ):
            results = locator.get_file_icons_and_names(region=(0, 0, 400, 200))

        assert len(results) >= 1, "应至少识别到一个图标"
        # Find the result closest to expected position
        closest = min(results, key=lambda r: abs(r.center[0] - expected_cx) + abs(r.center[1] - expected_cy))
        assert abs(closest.center[0] - expected_cx) <= 5, (
            f"center.x={closest.center[0]} 与期望 {expected_cx} 误差超过 5px"
        )
        assert abs(closest.center[1] - expected_cy) <= 5, (
            f"center.y={closest.center[1]} 与期望 {expected_cy} 误差超过 5px"
        )

    def test_locator_with_dpi_2x_returns_half_coords(
        self,
        file_listing_screenshot: tuple,
        template_file: Path,
    ) -> None:
        """scale=2.0 时，返回的逻辑坐标应约等于 scale=1.0 时的一半。

        若 VisionFileLocator 忘记调用 DPIAdapter.to_logical()，此测试失败。
        """
        screenshot, _, icon_info = file_listing_screenshot
        ix, iy, iw, ih = icon_info["x"], icon_info["y"], icon_info["w"], icon_info["h"]

        # scale=1.0: physical == logical
        adapter_1x = _make_adapter(scale=1.0)
        locator_1x = VisionFileLocator(ocr_confidence_threshold=0.0, dpi_adapter=adapter_1x)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(locator_1x._capturer, "capture_region", return_value=screenshot),
        ):
            results_1x = locator_1x.get_file_icons_and_names(region=(0, 0, 400, 200))

        # scale=2.0: logical = physical / 2
        adapter_2x = _make_adapter(scale=2.0)
        locator_2x = VisionFileLocator(ocr_confidence_threshold=0.0, dpi_adapter=adapter_2x)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(locator_2x._capturer, "capture_region", return_value=screenshot),
        ):
            results_2x = locator_2x.get_file_icons_and_names(region=(0, 0, 400, 200))

        assert len(results_1x) >= 1 and len(results_2x) >= 1, "两种 DPI 下都应识别到图标"

        cx_1x = results_1x[0].center[0]
        cx_2x = results_2x[0].center[0]

        # With scale=2.0, logical coords should be approximately half of scale=1.0
        # Allow tolerance of 2 logical pixels for rounding
        assert abs(cx_2x - cx_1x // 2) <= 2, (
            f"scale=2.0 时 center.x={cx_2x} 应约等于 scale=1.0 时 {cx_1x} 的一半"
        )

    def test_region_out_of_bounds_raises_value_error(
        self,
        file_listing_screenshot: tuple,
    ) -> None:
        """region 超出屏幕边界时应抛出 ValueError，消息包含越界值。

        若越界检查逻辑缺失或判断方向写反，此测试失败。
        """
        screenshot, _, _ = file_listing_screenshot
        adapter = _make_adapter(scale=1.0)
        locator = VisionFileLocator(dpi_adapter=adapter)

        with patch("pyautogui.size", return_value=(1920, 1080)):
            with pytest.raises(ValueError) as exc_info:
                locator.get_file_icons_and_names(region=(0, 0, 2000, 1080))

        assert "2000" in str(exc_info.value), f"异常消息应包含越界值 2000: {exc_info.value}"

    def test_valid_region_does_not_raise(
        self,
        file_listing_screenshot: tuple,
        template_file: Path,
    ) -> None:
        """合法 region 不应抛出 ValueError（边界验证的反向测试）。

        若把 > 写成 >= 导致合法边界值也报错，此测试失败。
        """
        screenshot, _, _ = file_listing_screenshot
        adapter = _make_adapter(scale=1.0)
        locator = VisionFileLocator(ocr_confidence_threshold=0.0, dpi_adapter=adapter)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(locator._capturer, "capture_region", return_value=screenshot),
        ):
            # Should not raise
            results = locator.get_file_icons_and_names(region=(0, 0, 400, 200))

        assert isinstance(results, list)

    def test_capture_exception_propagates(
        self,
        file_listing_screenshot: tuple,
    ) -> None:
        """ScreenCapturer 抛出异常时应向上传播，不被吞掉。

        若实现中加了 except: pass，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        locator = VisionFileLocator(dpi_adapter=adapter)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch.object(
                locator._capturer, "capture_region",
                side_effect=RuntimeError("mss capture failed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="mss capture failed"):
                locator.get_file_icons_and_names(region=(0, 0, 400, 200))


@pytest.mark.integration
class TestDragCoordinateFlow:
    """验证 VisionFileLocator → ActionEngine.drag 的坐标传递。

    Validates: Requirements 7.2, 7.3
    """

    def test_drag_receives_physical_coords_from_logical_input_1x(self) -> None:
        """scale=1.0 时，ActionEngine.drag 传给 pyautogui 的坐标应等于逻辑坐标。

        若 ActionEngine.drag 忘记调用 to_physical，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)

        from_logical = (100, 80)
        to_logical = (500, 400)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
            patch("pyautogui.dragTo") as mock_drag,
        ):
            result = engine.drag(from_logical[0], from_logical[1], to_logical[0], to_logical[1])

        assert result is True
        # scale=1.0: physical == logical
        mock_move.assert_called_once_with(100, 80)
        mock_drag.assert_called_once_with(500, 400, duration=0.5, button="left")

    def test_drag_receives_physical_coords_from_logical_input_125x(self) -> None:
        """scale=1.25 时，ActionEngine.drag 传给 pyautogui 的坐标应为逻辑坐标 × 1.25。

        若 ActionEngine.drag 忘记调用 to_physical，此测试失败（坐标不匹配）。
        """
        adapter = _make_adapter(scale=1.25)
        engine = ActionEngine(dpi_adapter=adapter)

        from_logical = (100, 80)
        to_logical = (400, 320)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
            patch("pyautogui.dragTo") as mock_drag,
        ):
            result = engine.drag(from_logical[0], from_logical[1], to_logical[0], to_logical[1])

        assert result is True
        # scale=1.25: physical = round(logical * 1.25)
        mock_move.assert_called_once_with(round(100 * 1.25), round(80 * 1.25))
        mock_drag.assert_called_once_with(round(400 * 1.25), round(320 * 1.25), duration=0.5, button="left")

    def test_moveto_called_before_dragto(self) -> None:
        """moveTo 必须在 dragTo 之前被调用。

        若实现中顺序颠倒或漏掉 moveTo，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)
        call_order: list[str] = []

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo", side_effect=lambda *a, **kw: call_order.append("moveTo")),
            patch("pyautogui.dragTo", side_effect=lambda *a, **kw: call_order.append("dragTo")),
        ):
            engine.drag(100, 80, 500, 400)

        assert call_order == ["moveTo", "dragTo"], f"调用顺序错误: {call_order}"

    def test_drag_from_out_of_bounds_returns_false_no_pyautogui(self) -> None:
        """from 坐标越界时应返回 False 且不调用 pyautogui。

        若越界检查缺失，pyautogui 会被调用，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
            patch("pyautogui.dragTo") as mock_drag,
        ):
            result = engine.drag(2000, 80, 500, 400)

        assert result is False
        mock_move.assert_not_called()
        mock_drag.assert_not_called()

    def test_drag_to_out_of_bounds_returns_false_no_dragto(self) -> None:
        """to 坐标越界时应返回 False 且不调用 pyautogui.dragTo。

        若只检查 from 坐标而不检查 to 坐标，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
            patch("pyautogui.dragTo") as mock_drag,
        ):
            result = engine.drag(100, 80, 2000, 400)

        assert result is False
        mock_move.assert_not_called()
        mock_drag.assert_not_called()


@pytest.mark.integration
class TestVisionFileMoverFallback:
    """验证 VisionFileMover 的拖拽降级逻辑。

    Validates: Requirements 2.1–2.6
    """

    def test_drag_success_no_context_menu(self) -> None:
        """拖拽成功时不应触发右键菜单备选。

        若实现中无论如何都走右键菜单，此测试失败（click 会被调用）。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)
        mover = VisionFileMover(action_engine=engine)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo"),
            patch("pyautogui.dragTo"),
            patch("pyautogui.click") as mock_click,
            patch("pyautogui.rightClick") as mock_right,
        ):
            result = mover.drag_file_to_folder((100, 100), (500, 400))

        assert result is True
        mock_right.assert_not_called()

    def test_drag_failure_triggers_context_menu(self) -> None:
        """拖拽失败时应触发右键菜单备选。

        若实现中拖拽失败后直接返回 False 而不尝试备选，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)
        mover = VisionFileMover(action_engine=engine)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo", side_effect=RuntimeError("drag failed")),
            patch("pyautogui.dragTo", side_effect=RuntimeError("drag failed")),
            patch("pyautogui.rightClick") as mock_right,
            patch("pyautogui.press"),
            patch("pyautogui.doubleClick"),
            patch("pyautogui.hotkey"),
            patch("time.sleep"),
        ):
            mover.drag_file_to_folder((100, 100), (500, 400))

        # Right-click should have been attempted as fallback
        mock_right.assert_called_once()

    def test_negative_file_center_raises_value_error(self) -> None:
        """file_center 含负数坐标时应抛出 ValueError，消息包含负数值。

        若实现中漏掉负数检查，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)
        mover = VisionFileMover(action_engine=engine)

        with pytest.raises(ValueError) as exc_info:
            mover.drag_file_to_folder((-1, 100), (500, 400))

        assert "-1" in str(exc_info.value), f"异常消息应包含 -1: {exc_info.value}"

    def test_negative_folder_center_raises_value_error(self) -> None:
        """folder_center 含负数坐标时应抛出 ValueError。

        若只检查 file_center 而不检查 folder_center，此测试失败。
        """
        adapter = _make_adapter(scale=1.0)
        engine = ActionEngine(dpi_adapter=adapter)
        mover = VisionFileMover(action_engine=engine)

        with pytest.raises(ValueError) as exc_info:
            mover.drag_file_to_folder((100, 100), (500, -5))

        assert "-5" in str(exc_info.value), f"异常消息应包含 -5: {exc_info.value}"


# ---------------------------------------------------------------------------
# Qwen-VL Integration Tests (vision-file-organizer spec)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestQwenVLRecognizerParseToFileOrganizer:
    """QwenVLRecognizer 解析 → FileOrganizer 分类数据流集成测试。

    Validates: Requirements 1.2, 1.3, 5.1, 8.3
    """

    # Pre-recorded fixture simulating a Qwen-VL API response
    _FIXTURE_RESPONSE = json.dumps([
        {"bbox": [10, 20, 74, 84], "type": "PDF", "name": "report.pdf", "confidence": 0.95},
        {"bbox": [100, 20, 164, 84], "type": "Image", "name": "photo.jpg", "confidence": 0.88},
        {"bbox": [200, 20, 264, 84], "type": "Word", "name": "notes.docx", "confidence": 0.72},
    ])

    def test_parse_response_produces_correct_vision_file_items(self) -> None:
        """Real _parse_response produces VisionFileItems with correct bbox and file_type."""
        from automation.qwen_vl_recognizer import QwenVLRecognizer
        recognizer = QwenVLRecognizer(dpi_adapter=None, detection_cache=None)
        items = recognizer._parse_response(self._FIXTURE_RESPONSE)

        assert len(items) == 3
        assert items[0].name == "report.pdf"
        assert items[0].file_type == "PDF"
        assert items[0].bbox == (10, 20, 64, 64)  # (x1, y1, x2-x1, y2-y1)
        assert items[1].name == "photo.jpg"
        assert items[1].file_type == "Image"
        assert items[2].name == "notes.docx"
        assert items[2].file_type == "Word"

    def test_get_category_for_item_classifies_correctly(self) -> None:
        """Real _get_category_for_item classifies VisionFileItems correctly."""
        from automation.file_organizer import _get_category_for_item
        from automation.qwen_vl_recognizer import QwenVLRecognizer

        recognizer = QwenVLRecognizer(dpi_adapter=None, detection_cache=None)
        items = recognizer._parse_response(self._FIXTURE_RESPONSE)

        assert _get_category_for_item(Path(items[0].name), items[0].file_type) == "Documents"
        assert _get_category_for_item(Path(items[1].name), items[1].file_type) == "Images"
        assert _get_category_for_item(Path(items[2].name), items[2].file_type) == "Documents"

    def test_detection_cache_written_with_correct_fields(self) -> None:
        """DetectionCache receives BoundingBoxDict with correct label and confidence."""
        import os
        from automation.object_detector import DetectionCache
        from automation.qwen_vl_recognizer import QwenVLRecognizer

        cache = DetectionCache()
        recognizer = QwenVLRecognizer(dpi_adapter=None, detection_cache=cache)

        img = np.zeros((200, 400, 3), dtype=np.uint8)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=self._FIXTURE_RESPONSE))]
        )

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with patch("openai.OpenAI", return_value=mock_client):
                items = recognizer.recognize_file_icons(img)

        boxes = cache.get()
        assert len(boxes) == 3
        labels = [b["label"] for b in boxes]
        assert "report.pdf" in labels
        assert "photo.jpg" in labels
        confidences = [b["confidence"] for b in boxes]
        assert all(0.0 <= c <= 1.0 for c in confidences)
        assert boxes[0]["confidence"] == pytest.approx(0.95)


@pytest.mark.integration
class TestEndToEndFallbackChain:
    """端到端三级降级链集成测试。

    Validates: Requirements 3.1, 6.1
    """

    _FIXTURE_RESPONSE = json.dumps([
        {"bbox": [10, 20, 74, 84], "type": "PDF", "name": "report.pdf", "confidence": 0.95},
        {"bbox": [100, 20, 164, 84], "type": "Image", "name": "photo.jpg", "confidence": 0.88},
    ])

    def test_scenario_qwen_vl_success_all_files_use_vision_vl_path(self) -> None:
        """Scenario 1: Qwen-VL identifies all files → all moved via vision_vl path."""
        import shutil
        import tempfile
        import threading
        import automation.file_organizer as _fo_mod
        import automation.qwen_vl_recognizer as _vl_mod
        import subprocess as _subprocess_mod
        import tkinter.messagebox as _msgbox_mod
        import perception.screen_capturer as _capturer_mod
        import execution.action_engine as _engine_mod
        from automation.file_organizer import run_file_organizer

        tmpdir = tempfile.mkdtemp(prefix="e2e_test_")
        try:
            source = Path(tmpdir) / "src"
            source.mkdir()
            target = Path(tmpdir) / "dst"
            (source / "report.pdf").write_text("data")
            (source / "photo.jpg").write_text("data")

            descriptions: list[str] = []

            def callback(desc: str, pct: int) -> None:
                descriptions.append(desc)

            stop = threading.Event()

            fixture_response = self._FIXTURE_RESPONSE
            from automation.qwen_vl_recognizer import QwenVLRecognizer as _OrigRecognizer

            class _FakeRecognizer:
                def __init__(self, **kwargs): pass
                def recognize_file_icons(self, img):
                    real = object.__new__(_OrigRecognizer)
                    real._scale_ratio = 1.0
                    real._dpi_adapter = None
                    real._detection_cache = None
                    real._vision_box_enabled = False
                    return _OrigRecognizer._parse_response(real, fixture_response)

            class _FakeCapturer:
                def capture_full(self): return np.zeros((100, 100, 3), dtype=np.uint8)

            class _FakeActionEngine:
                def click(self, x, y, **kwargs): pass

            class _FakeWin:
                def child_window(self, **kwargs): raise Exception("not found")

            class _FakeApp:
                def connect(self, **kwargs): return self
                def top_window(self): return _FakeWin()

            orig_load_mode = _fo_mod._load_organize_mode
            orig_load_path = _fo_mod._load_organize_path
            orig_load_threshold = _fo_mod._load_move_confidence_threshold
            orig_popen = _subprocess_mod.Popen
            orig_askyesno = _msgbox_mod.askyesno
            orig_vl_recognizer = _vl_mod.QwenVLRecognizer
            orig_capturer = _capturer_mod.ScreenCapturer
            orig_engine = _engine_mod.ActionEngine

            try:
                _fo_mod._load_organize_mode = lambda: "vision_first"
                _fo_mod._load_organize_path = lambda: "screenshot_path"
                _fo_mod._load_move_confidence_threshold = lambda: 0.0
                _subprocess_mod.Popen = lambda *a, **kw: None
                _msgbox_mod.askyesno = lambda *a, **kw: False
                _vl_mod.QwenVLRecognizer = _FakeRecognizer
                _capturer_mod.ScreenCapturer = _FakeCapturer
                _engine_mod.ActionEngine = _FakeActionEngine

                try:
                    import pywinauto.application as _pw_app
                    orig_pw_app = _pw_app.Application
                    _pw_app.Application = _FakeApp
                except Exception:
                    orig_pw_app = None
                    _pw_app = None

                run_file_organizer(
                    source_dir=source,
                    target_dir=target,
                    progress_callback=callback,
                    stop_event=stop,
                )
            finally:
                _fo_mod._load_organize_mode = orig_load_mode
                _fo_mod._load_organize_path = orig_load_path
                _fo_mod._load_move_confidence_threshold = orig_load_threshold
                _subprocess_mod.Popen = orig_popen
                _msgbox_mod.askyesno = orig_askyesno
                _vl_mod.QwenVLRecognizer = orig_vl_recognizer
                _capturer_mod.ScreenCapturer = orig_capturer
                _engine_mod.ActionEngine = orig_engine
                if _pw_app is not None and orig_pw_app is not None:
                    _pw_app.Application = orig_pw_app

            assert (target / "Documents" / "PDF" / "report.pdf").exists()
            assert (target / "Images" / "JPG" / "photo.jpg").exists()
            assert any("[vision_vl]" in d for d in descriptions)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_scenario_qwen_vl_api_error_files_still_processed(self) -> None:
        """Scenario 2: QwenVLAPIError → all files go through vision_os/os_fallback."""
        import shutil
        import tempfile
        import threading
        import automation.file_organizer as _fo_mod
        import automation.qwen_vl_recognizer as _vl_mod
        import subprocess as _subprocess_mod
        import tkinter.messagebox as _msgbox_mod
        import perception.screen_capturer as _capturer_mod
        import execution.action_engine as _engine_mod
        from automation.file_organizer import run_file_organizer
        from automation.qwen_vl_recognizer import QwenVLAPIError

        tmpdir = tempfile.mkdtemp(prefix="e2e_test2_")
        try:
            source = Path(tmpdir) / "src"
            source.mkdir()
            target = Path(tmpdir) / "dst"
            (source / "report.pdf").write_text("data")

            descriptions: list[str] = []

            def callback(desc: str, pct: int) -> None:
                descriptions.append(desc)

            stop = threading.Event()

            class _FakeRecognizer:
                def __init__(self, **kwargs): pass
                def recognize_file_icons(self, img):
                    raise QwenVLAPIError("api fail")

            class _FakeCapturer:
                def capture_full(self): return np.zeros((100, 100, 3), dtype=np.uint8)

            class _FakeActionEngine:
                def click(self, x, y, **kwargs): pass

            class _FakeWin:
                def child_window(self, **kwargs): raise Exception("not found")

            class _FakeApp:
                def connect(self, **kwargs): return self
                def top_window(self): return _FakeWin()

            orig_load_mode = _fo_mod._load_organize_mode
            orig_load_path = _fo_mod._load_organize_path
            orig_load_threshold = _fo_mod._load_move_confidence_threshold
            orig_popen = _subprocess_mod.Popen
            orig_askyesno = _msgbox_mod.askyesno
            orig_vl_recognizer = _vl_mod.QwenVLRecognizer
            orig_capturer = _capturer_mod.ScreenCapturer
            orig_engine = _engine_mod.ActionEngine

            try:
                _fo_mod._load_organize_mode = lambda: "vision_first"
                _fo_mod._load_organize_path = lambda: "screenshot_path"
                _fo_mod._load_move_confidence_threshold = lambda: 0.0
                _subprocess_mod.Popen = lambda *a, **kw: None
                _msgbox_mod.askyesno = lambda *a, **kw: True  # user confirms os_fallback
                _vl_mod.QwenVLRecognizer = _FakeRecognizer
                _capturer_mod.ScreenCapturer = _FakeCapturer
                _engine_mod.ActionEngine = _FakeActionEngine

                try:
                    import pywinauto.application as _pw_app
                    orig_pw_app = _pw_app.Application
                    _pw_app.Application = _FakeApp
                except Exception:
                    orig_pw_app = None
                    _pw_app = None

                run_file_organizer(
                    source_dir=source,
                    target_dir=target,
                    progress_callback=callback,
                    stop_event=stop,
                )
            finally:
                _fo_mod._load_organize_mode = orig_load_mode
                _fo_mod._load_organize_path = orig_load_path
                _fo_mod._load_move_confidence_threshold = orig_load_threshold
                _subprocess_mod.Popen = orig_popen
                _msgbox_mod.askyesno = orig_askyesno
                _vl_mod.QwenVLRecognizer = orig_vl_recognizer
                _capturer_mod.ScreenCapturer = orig_capturer
                _engine_mod.ActionEngine = orig_engine
                if _pw_app is not None and orig_pw_app is not None:
                    _pw_app.Application = orig_pw_app

            assert any("report.pdf" in d or "任务完成" in d for d in descriptions)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
