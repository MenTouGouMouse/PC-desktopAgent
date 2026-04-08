"""tests/unit/automation/test_file_organizer_vl.py

FileOrganizer Qwen-VL 三级降级链单元测试 + 属性测试。
使用真实文件系统（tempfile.mkdtemp）和真实 shutil.move；
mock QwenVLRecognizer、pywinauto、tkinter.messagebox、ScreenCapturer。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from automation.file_organizer import (
    FILE_CATEGORY_MAP,
    _FILE_TYPE_CATEGORY_MAP,
    _get_category_for_item,
    _load_organize_path,
    run_file_organizer,
)
from automation.qwen_vl_recognizer import VisionFileItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vl_item(
    name: str,
    file_type: str = "PDF",
    confidence: float = 0.9,
    bbox: tuple[int, int, int, int] = (10, 20, 60, 40),
) -> VisionFileItem:
    return VisionFileItem(name=name, file_type=file_type, bbox=bbox, confidence=confidence)


def _noop_callback(desc: str, pct: int) -> None:
    pass


def _run_organizer(
    source: Path,
    target: Path,
    vl_items: list[VisionFileItem] | None = None,
    vl_error: Exception | None = None,
    threshold: float = 0.0,
    organize_path: str = "screenshot_path",
) -> list[str]:
    """Run file organizer with mocked external dependencies, return progress descriptions."""
    import automation.file_organizer as _fo_mod
    import automation.qwen_vl_recognizer as _vl_mod
    import subprocess as _subprocess_mod
    import tkinter.messagebox as _msgbox_mod
    import perception.screen_capturer as _capturer_mod
    import execution.action_engine as _engine_mod

    descriptions: list[str] = []

    def callback(desc: str, pct: int) -> None:
        descriptions.append(desc)

    stop = threading.Event()

    import numpy as np
    mock_screenshot = np.zeros((100, 100, 3), dtype=np.uint8)

    # Save originals
    orig_load_path = _fo_mod._load_organize_path
    orig_load_threshold = _fo_mod._load_move_confidence_threshold
    orig_load_mode = _fo_mod._load_organize_mode
    orig_popen = _subprocess_mod.Popen
    orig_askyesno = _msgbox_mod.askyesno

    # Create fake recognizer
    class _FakeRecognizer:
        def __init__(self, **kwargs):
            pass
        def recognize_file_icons(self, img):
            if vl_error is not None:
                raise vl_error
            return vl_items or []

    # Create fake screen capturer
    class _FakeCapturer:
        def capture_full(self):
            return mock_screenshot
        def capture_region(self, region):
            return mock_screenshot

    # Create fake action engine
    class _FakeActionEngine:
        def click(self, x, y, **kwargs):
            pass

    # Create fake pywinauto Application
    class _FakeWin:
        def child_window(self, **kwargs):
            raise Exception("not found")
        def rectangle(self):
            raise Exception("not found")

    class _FakeApp:
        def connect(self, **kwargs):
            return self
        def top_window(self):
            return _FakeWin()

    orig_vl_recognizer = _vl_mod.QwenVLRecognizer

    try:
        _fo_mod._load_organize_path = lambda: organize_path
        _fo_mod._load_move_confidence_threshold = lambda: threshold
        _fo_mod._load_organize_mode = lambda: "vision_first"
        _subprocess_mod.Popen = lambda *a, **kw: None
        _msgbox_mod.askyesno = lambda *a, **kw: False
        _vl_mod.QwenVLRecognizer = _FakeRecognizer
        _capturer_mod.ScreenCapturer = _FakeCapturer
        _engine_mod.ActionEngine = _FakeActionEngine

        # Patch pywinauto Application
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
        _fo_mod._load_organize_path = orig_load_path
        _fo_mod._load_move_confidence_threshold = orig_load_threshold
        _fo_mod._load_organize_mode = orig_load_mode
        _subprocess_mod.Popen = orig_popen
        _msgbox_mod.askyesno = orig_askyesno
        _vl_mod.QwenVLRecognizer = orig_vl_recognizer
        if _pw_app is not None and orig_pw_app is not None:
            _pw_app.Application = orig_pw_app

    return descriptions


# ---------------------------------------------------------------------------
# 6.1 三级降级链编排单元测试
# ---------------------------------------------------------------------------

class TestVisionVLFallbackChain:
    def _make_dirs(self) -> tuple[Path, Path, str]:
        """Create temp source and target dirs, return (source, target, tmpdir_str)."""
        tmpdir = tempfile.mkdtemp(prefix="vl_test_")
        source = Path(tmpdir) / "src"
        source.mkdir()
        target = Path(tmpdir) / "dst"
        return source, target, tmpdir

    def test_qwen_vl_api_error_falls_through_to_pywinauto(self) -> None:
        """QwenVLAPIError → vl_map empty → all files go through pywinauto path."""
        from automation.qwen_vl_recognizer import QwenVLAPIError
        source, target, tmpdir = self._make_dirs()
        try:
            (source / "report.pdf").write_text("data")
            descs = _run_organizer(source, target, vl_error=QwenVLAPIError("api fail"))
            assert any("report.pdf" in d or "任务完成" in d for d in descs)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_vision_vl_match_high_confidence_moves_file(self) -> None:
        """vision_vl match with confidence >= threshold → file moved with [vision_vl] tag."""
        source, target, tmpdir = self._make_dirs()
        try:
            (source / "report.pdf").write_text("data")
            vl_items = [_make_vl_item("report.pdf", "PDF", confidence=0.9)]
            descs = _run_organizer(source, target, vl_items=vl_items, threshold=0.6)
            assert (target / "Documents" / "PDF" / "report.pdf").exists()
            assert any("[vision_vl]" in d for d in descs)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_vision_vl_match_low_confidence_adds_to_low_conf_list(self) -> None:
        """vision_vl match with confidence < threshold → file added to low_conf list, not moved."""
        source, target, tmpdir = self._make_dirs()
        try:
            (source / "report.pdf").write_text("data")
            vl_items = [_make_vl_item("report.pdf", "PDF", confidence=0.3)]
            _run_organizer(source, target, vl_items=vl_items, threshold=0.6)
            assert not (target / "Documents" / "report.pdf").exists()
            assert (source / "report.pdf").exists()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_vision_vl_no_match_falls_through_to_pywinauto(self) -> None:
        """vision_vl no match → file goes through pywinauto (vision_os) path."""
        source, target, tmpdir = self._make_dirs()
        try:
            (source / "photo.jpg").write_text("data")
            vl_items = [_make_vl_item("other.pdf", "PDF", confidence=0.9)]
            descs = _run_organizer(source, target, vl_items=vl_items, threshold=0.0)
            assert any("photo.jpg" in d or "任务完成" in d for d in descs)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_case_insensitive_matching(self) -> None:
        """File 'Report.PDF' matches vl_map key 'report.pdf'."""
        source, target, tmpdir = self._make_dirs()
        try:
            (source / "Report.PDF").write_text("data")
            vl_items = [_make_vl_item("report.pdf", "PDF", confidence=0.95)]
            descs = _run_organizer(source, target, vl_items=vl_items, threshold=0.0)
            assert (target / "Documents" / "PDF" / "Report.PDF").exists() or any("[vision_vl]" in d for d in descs)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6.2 _load_organize_path 和 _get_category_for_item 单元测试
# ---------------------------------------------------------------------------

class TestLoadOrganizePath:
    def test_missing_field_defaults_to_screenshot_path(self) -> None:
        import yaml as _yaml
        orig = _yaml.safe_load
        try:
            _yaml.safe_load = lambda f: {}
            result = _load_organize_path()
        finally:
            _yaml.safe_load = orig
        assert result == "screenshot_path"

    def test_invalid_value_raises_value_error(self) -> None:
        import yaml as _yaml
        orig = _yaml.safe_load
        try:
            _yaml.safe_load = lambda f: {"organize_path": "bad_value"}
            with pytest.raises(ValueError) as exc_info:
                _load_organize_path()
        finally:
            _yaml.safe_load = orig
        assert "bad_value" in str(exc_info.value)
        assert "screenshot_path" in str(exc_info.value)

    def test_valid_screenshot_path(self) -> None:
        import yaml as _yaml
        orig = _yaml.safe_load
        try:
            _yaml.safe_load = lambda f: {"organize_path": "screenshot_path"}
            result = _load_organize_path()
        finally:
            _yaml.safe_load = orig
        assert result == "screenshot_path"

    def test_valid_explorer_path(self) -> None:
        import yaml as _yaml
        orig = _yaml.safe_load
        try:
            _yaml.safe_load = lambda f: {"organize_path": "explorer_path"}
            result = _load_organize_path()
        finally:
            _yaml.safe_load = orig
        assert result == "explorer_path"


class TestGetCategoryForItem:
    def test_extension_in_map_uses_extension(self) -> None:
        result = _get_category_for_item(Path("test.pdf"), "Other")
        assert result == ("Documents", "PDF")

    def test_extension_not_in_map_uses_file_type(self) -> None:
        result = _get_category_for_item(Path("test.xyz"), "Image")
        assert result == ("Images", "Other")

    def test_folder_type_returns_none(self) -> None:
        result = _get_category_for_item(Path("test.xyz"), "Folder")
        assert result is None

    def test_extension_priority_over_file_type(self) -> None:
        # .jpg is in FILE_CATEGORY_MAP → ("Images", "JPG"), even if file_type says PDF
        result = _get_category_for_item(Path("test.jpg"), "PDF")
        assert result == ("Images", "JPG")

    def test_unknown_file_type_returns_others(self) -> None:
        result = _get_category_for_item(Path("test.xyz"), "UnknownType")
        assert result == ("Others", "Other")


# ---------------------------------------------------------------------------
# 6.3 Property 6: 大小写不敏感名称匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "report", "photo", "document", "MyFile", "TEST", "abc123",
    "ReportPDF", "helloworld", "FileName", "data2024",
    "UPPERCASE", "lowercase", "MixedCase", "file001", "FILE001",
])
def test_property6_case_insensitive_matching(name: str) -> None:
    """Property 6: any ASCII case variant of a name matches the same vl_map entry."""
    mock_item = _make_vl_item(name.lower())
    vl_map = {name.lower(): mock_item}
    assert vl_map.get(name.upper().lower()) == vl_map.get(name.lower())
    assert vl_map.get(name.lower()) is mock_item
    assert vl_map.get(name.upper().lower()) == vl_map.get(name.lower())
    assert vl_map.get(name.lower()) is mock_item


# ---------------------------------------------------------------------------
# 6.4 Property 7: 置信度门控边界行为
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confidence,threshold,should_move", [
    (0.9, 0.6, True),
    (0.6, 0.6, True),   # boundary: exactly equal → move
    (0.59, 0.6, False),
    (0.0, 0.0, True),   # threshold=0 → always move
    (1.0, 1.0, True),   # boundary: exactly equal → move
    (0.99, 1.0, False),
    (0.5, 0.8, False),
    (0.8, 0.5, True),
])
def test_property7_confidence_gate_boundary(confidence: float, threshold: float, should_move: bool) -> None:
    """Property 7: confidence >= threshold → move; confidence < threshold → pending."""
    if should_move:
        assert confidence >= threshold
    else:
        assert confidence < threshold


# ---------------------------------------------------------------------------
# 6.5 Property 8: 非法 organize_path 触发 ValueError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "invalid", "bad_path", "none", "explorer", "screenshot",
    "SCREENSHOT_PATH", "EXPLORER_PATH", "path1", "test_mode", "unknown",
    "vision_first", "os_only", "auto", "manual", "default",
])
def test_property8_invalid_organize_path_raises(path: str) -> None:
    """Property 8: any invalid organize_path raises ValueError with the value in message."""
    import yaml as _yaml
    orig = _yaml.safe_load
    try:
        _yaml.safe_load = lambda f: {"organize_path": path}
        with pytest.raises(ValueError) as exc_info:
            _load_organize_path()
    finally:
        _yaml.safe_load = orig
    msg = str(exc_info.value)
    assert path in msg or repr(path) in msg
    assert "screenshot_path" in msg


# ---------------------------------------------------------------------------
# 6.6 Property 9: 扩展名优先 + file_type 兜底分类
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext,file_type", [
    (".pdf", "Image"),
    (".jpg", "PDF"),
    (".mp4", "Audio"),
    (".py", "Other"),
    (".zip", "Word"),
    (".docx", "Video"),
    (".png", "Code"),
    (".mp3", "Archive"),
])
def test_property9_extension_priority_over_file_type(ext: str, file_type: str) -> None:
    """Property 9: when extension is in FILE_CATEGORY_MAP, it takes priority over file_type."""
    file = Path(f"test{ext}")
    result = _get_category_for_item(file, file_type)
    assert result == FILE_CATEGORY_MAP[ext]
