"""
Preservation Property Tests — Smart Install Launcher Fix

These tests MUST PASS on UNFIXED code.
They establish the baseline behavior that must be preserved after the fix.

Validates: Requirements 3.1, 3.2, 3.4, 3.6
"""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from automation.software_installer import run_software_installer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_callback(step: str, percent: int) -> None:
    pass


# ---------------------------------------------------------------------------
# Property-Based Test: Preservation — standard ASCII paths use os.startfile
#
# For all pure ASCII no-space paths, run_software_installer calls os.startfile
# once and NEVER calls ShellExecuteW.
#
# This must hold on UNFIXED code (baseline) and continue to hold after the fix.
#
# Validates: Requirement 3.1
# ---------------------------------------------------------------------------

@given(st.from_regex(r'[A-Za-z]:\\[A-Za-z0-9_\\]+\.exe', fullmatch=True))
@settings(max_examples=30)
def test_ascii_path_uses_popen_not_shellexecute(path_str: str) -> None:
    """**Validates: Requirements 3.1**

    For all pure ASCII no-space paths:
    - subprocess.Popen is called (primary launch method)
    - ShellExecuteW is never called (last-resort UAC escalation is not needed)

    This is the preservation property: the fix must not change this behavior.
    """
    stop_event = threading.Event()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen, \
         patch("ctypes.windll.shell32.ShellExecuteW") as mock_shellexecute, \
         patch("time.sleep"), \
         patch("perception.screen_capturer.ScreenCapturer") as mock_capturer_cls, \
         patch("perception.element_locator.ElementLocator") as mock_locator_cls, \
         patch("execution.action_engine.ActionEngine") as mock_engine_cls:

        # Make the install steps loop exit immediately via stop_event
        stop_event.set()

        try:
            run_software_installer(path_str, _noop_callback, stop_event)
        except Exception:
            # We only care about the launch behavior, not the automation steps
            pass

        mock_popen.assert_called_once()
        mock_shellexecute.assert_not_called()


# ---------------------------------------------------------------------------
# Unit Tests: Preservation — start_smart_installer behavior
# ---------------------------------------------------------------------------

class TestStartSmartInstallerPreservation:
    """Tests that document preserved behavior in start_smart_installer."""

    def _make_api(self) -> object:
        """Create a PythonAPI instance with mocked dependencies."""
        from gui.app import PythonAPI
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        progress_manager = ProgressManager()
        queue_manager = QueueManager()
        api = PythonAPI(progress_manager, queue_manager)
        return api

    def test_cancelled_file_dialog_returns_user_cancelled_error(self) -> None:
        """**Validates: Requirement 3.2**

        When the user cancels the file dialog (returns empty/None),
        start_smart_installer returns {"success": False, "error": "用户取消了文件选择"}.
        """
        api = self._make_api()

        mock_window = MagicMock()
        # Simulate user cancelling: create_file_dialog returns empty list
        mock_window.create_file_dialog.return_value = []
        api._main_win = mock_window

        result = api.start_smart_installer()

        assert result == {"success": False, "error": "用户取消了文件选择"}

    def test_cancelled_file_dialog_none_returns_user_cancelled_error(self) -> None:
        """**Validates: Requirement 3.2**

        When the file dialog returns None (another cancel variant),
        start_smart_installer returns {"success": False, "error": "用户取消了文件选择"}.
        """
        api = self._make_api()

        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = None
        api._main_win = mock_window

        result = api.start_smart_installer()

        assert result == {"success": False, "error": "用户取消了文件选择"}

    def test_task_already_running_returns_error(self) -> None:
        """**Validates: Requirement 3.4**

        When is_running=True (a task is already running),
        start_smart_installer returns {"success": False, "error": "Task already running"}.
        """
        api = self._make_api()

        # Set the progress manager to is_running=True
        api._progress_manager.update(50, "running", "smart_installer", is_running=True)

        result = api.start_smart_installer()

        assert result == {"success": False, "error": "Task already running"}

    def test_task_already_running_does_not_open_file_dialog(self) -> None:
        """**Validates: Requirement 3.4**

        When is_running=True, no file dialog should be opened.
        """
        api = self._make_api()
        api._progress_manager.update(50, "running", "smart_installer", is_running=True)

        mock_window = MagicMock()
        api._main_win = mock_window

        api.start_smart_installer()

        mock_window.create_file_dialog.assert_not_called()


# ---------------------------------------------------------------------------
# Unit Test: Preservation — config persistence
#
# save_default_paths then get_default_paths returns the saved values.
#
# Validates: Requirement 3.6
# ---------------------------------------------------------------------------

class TestConfigPersistence:
    """Tests that config persistence behavior is preserved."""

    def _make_api_with_temp_settings(self) -> tuple[object, Path]:
        """Create a PythonAPI instance that writes to a temp settings file."""
        from gui.app import PythonAPI
        from gui.progress_manager import ProgressManager
        from ui.queue_manager import QueueManager

        progress_manager = ProgressManager()
        queue_manager = QueueManager()
        api = PythonAPI(progress_manager, queue_manager)
        return api

    def test_save_then_get_default_paths_returns_saved_values(self) -> None:
        """**Validates: Requirement 3.6**

        After calling save_default_paths with specific values,
        get_default_paths returns those exact values.
        """
        import gui.app as app_module

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_settings = Path(tmpdir) / "user_settings.json"

            # Patch the settings path to use a temp file
            with patch.object(app_module, "_USER_SETTINGS_PATH", tmp_settings):
                api = self._make_api_with_temp_settings()

                save_result = api.save_default_paths(
                    organize_source=r"C:\Users\test\Desktop",
                    organize_target=r"D:\Organized",
                    installer_default_dir=r"E:\Downloads",
                )
                assert save_result == {"success": True}

                get_result = api.get_default_paths()

                assert get_result["organize_source"] == r"C:\Users\test\Desktop"
                assert get_result["organize_target"] == r"D:\Organized"
                assert get_result["installer_default_dir"] == r"E:\Downloads"

    def test_save_default_paths_writes_to_json_file(self) -> None:
        """**Validates: Requirement 3.6**

        save_default_paths persists values to user_settings.json on disk.
        """
        import gui.app as app_module

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_settings = Path(tmpdir) / "user_settings.json"

            with patch.object(app_module, "_USER_SETTINGS_PATH", tmp_settings):
                api = self._make_api_with_temp_settings()

                api.save_default_paths(
                    organize_source=r"C:\source",
                    organize_target=r"C:\target",
                    installer_default_dir=r"C:\installers",
                )

                assert tmp_settings.exists()
                with open(tmp_settings, encoding="utf-8") as f:
                    data = json.load(f)

                assert data["organize_source"] == r"C:\source"
                assert data["organize_target"] == r"C:\target"
                assert data["installer_default_dir"] == r"C:\installers"

    def test_get_default_paths_returns_defaults_when_no_settings_file(self) -> None:
        """**Validates: Requirement 3.6**

        When no settings file exists, get_default_paths returns default values
        (not an error).
        """
        import gui.app as app_module

        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "nonexistent.json"

            with patch.object(app_module, "_USER_SETTINGS_PATH", nonexistent):
                api = self._make_api_with_temp_settings()
                result = api.get_default_paths()

                # Should return a dict with the three keys, not an error
                assert "organize_source" in result
                assert "organize_target" in result
                assert "installer_default_dir" in result
                assert result.get("success") is not False


# ===========================================================================
# click-dpi-overlay-fix Preservation Tests
#
# These tests MUST PASS on UNFIXED code — they establish the baseline behavior
# that must be preserved after the fix.
#
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
# ===========================================================================

import numpy as np
from hypothesis import given, settings, strategies as st
from unittest.mock import MagicMock, call, patch, create_autospec

from automation.object_detector import DetectionCache
from automation.vision_box_drawer import BoundingBoxDict
from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter, MonitorInfo
from perception.element_locator import ElementResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dpi_adapter(scale: float = 1.0, left: int = 0, top: int = 0) -> DPIAdapter:
    """Create a DPIAdapter with a single mocked monitor."""
    monitor = MonitorInfo(index=0, left=left, top=top, scale_factor=scale)
    adapter = DPIAdapter.__new__(DPIAdapter)
    adapter._monitors = [monitor]
    adapter.scale_factor = scale
    return adapter


def _make_screenshot() -> np.ndarray:
    return np.zeros((1, 1, 3), dtype=np.uint8)


def _noop_cb(step: str, percent: int) -> None:
    pass


# ---------------------------------------------------------------------------
# Preservation Test 1 — scale_factor=1.0 no-op
#
# With scale_factor=1.0, to_logical(cx, cy) == (cx, cy) — the conversion is
# a no-op. pyautogui.moveTo must receive the bbox center unchanged.
#
# Validates: Requirements 3.1, 3.4
# ---------------------------------------------------------------------------

class TestPreservation1ScaleFactor1NoOp:
    """Preservation: scale_factor=1.0 means physical == logical, no coordinate drift.

    **Validates: Requirements 3.1, 3.4**
    """

    def test_moveto_receives_bbox_center_when_scale_is_one(self) -> None:
        """With scale_factor=1.0, pyautogui.moveTo receives the exact bbox center.

        Mock locate_by_text returning ElementResult(bbox=(300, 200, 80, 30)).
        Center: cx = 300 + 80//2 = 340, cy = 200 + 30//2 = 215.
        With scale=1.0, to_physical(340, 215) == (340, 215) — no drift.

        **Validates: Requirements 3.1, 3.4**
        """
        import threading
        from automation.software_installer import run_software_installer

        mock_result = ElementResult(
            name="下一步",
            bbox=(300, 200, 80, 30),
            confidence=0.9,
            strategy="ocr",
        )

        stop_event = threading.Event()
        moveto_calls: list[tuple[int, int]] = []

        def capture_moveto(x: int, y: int) -> None:
            moveto_calls.append((x, y))
            stop_event.set()

        # scale_factor=1.0: to_physical(x, y) == (x, y)
        dpi_adapter = _make_dpi_adapter(scale=1.0)

        scale1_adapter = _make_dpi_adapter(scale=1.0)

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer._activate_installer_window"), \
             patch("time.sleep"), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   return_value=mock_result), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=_make_screenshot()), \
             patch("perception.dpi_adapter.DPIAdapter",
                   return_value=scale1_adapter), \
             patch("execution.action_engine.ActionEngine.__init__",
                   lambda self, dpi_adapter=None: (
                       setattr(self, "_dpi", _make_dpi_adapter(scale=1.0)) or None
                   )), \
             patch("pyautogui.moveTo", side_effect=capture_moveto), \
             patch("pyautogui.click"), \
             patch("pyautogui.size", return_value=(1920, 1080)):

            try:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_cb,
                    stop_event,
                )
            except Exception:
                pass

        assert len(moveto_calls) >= 1, "pyautogui.moveTo was never called"
        # With scale=1.0, center (340, 215) must reach moveTo unchanged
        first_call = moveto_calls[0]
        assert first_call == (340, 215), (
            f"scale_factor=1.0 preservation broken: moveTo received {first_call}, "
            f"expected (340, 215). The fix must not drift coordinates when scale=1.0."
        )

    @given(
        x=st.integers(min_value=0, max_value=1800),
        y=st.integers(min_value=0, max_value=900),
    )
    @settings(max_examples=100)
    def test_to_logical_with_scale_one_is_identity(self, x: int, y: int) -> None:
        """Property: for all (x, y), to_logical(x, y, scale=1.0) == (x, y).

        This is the mathematical foundation of the scale=1.0 preservation:
        the to_logical call in the fixed code is a no-op when scale=1.0.

        **Validates: Requirements 3.1, 3.4**
        """
        adapter = _make_dpi_adapter(scale=1.0)
        lx, ly = adapter.to_logical(x, y)
        assert (lx, ly) == (x, y), (
            f"to_logical({x}, {y}, scale=1.0) returned ({lx}, {ly}), expected ({x}, {y}). "
            f"scale=1.0 must be a no-op."
        )


# ---------------------------------------------------------------------------
# Preservation Test 2 — file organizer cache behavior unchanged
#
# file_organizer.py is NOT modified by the fix. Its DetectionCache.update()
# call sequence must remain identical.
#
# Validates: Requirement 3.3
# ---------------------------------------------------------------------------

class TestPreservation2FileOrganizerCacheBehavior:
    """Preservation: file_organizer.py DetectionCache write pattern is unchanged.

    **Validates: Requirement 3.3**
    """

    def test_detection_cache_update_called_with_bounding_box_dict(self) -> None:
        """run_file_organizer writes BoundingBoxDict entries to detection_cache.

        Mock pywinauto to return a known rectangle for a file item.
        Assert detection_cache.update() is called with the expected bbox data.
        This behavior must be unchanged after the fix (file_organizer.py is not modified).

        **Validates: Requirement 3.3**
        """
        import threading
        from automation.file_organizer import run_file_organizer

        detection_cache = DetectionCache()
        stop_event = threading.Event()
        update_calls: list[list[BoundingBoxDict]] = []

        original_update = detection_cache.update

        def spy_update(boxes: list[BoundingBoxDict]) -> None:
            update_calls.append(list(boxes))
            original_update(boxes)

        detection_cache.update = spy_update  # type: ignore[method-assign]

        import tempfile, os
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as tgt_dir:

            # Create a test file
            test_file = Path(src_dir) / "test_document.pdf"
            test_file.write_bytes(b"fake pdf content")

            # Mock pywinauto Application to return a fake rectangle
            mock_rect = MagicMock()
            mock_rect.left = 100
            mock_rect.top = 200
            mock_rect.right = 300
            mock_rect.bottom = 250

            mock_file_item = MagicMock()
            mock_file_item.rectangle.return_value = mock_rect

            mock_win = MagicMock()
            mock_win.child_window.return_value = mock_file_item

            mock_app = MagicMock()
            mock_app.top_window.return_value = mock_win

            # Patch settings to use vision_first mode
            with patch("automation.file_organizer._load_organize_mode",
                       return_value="vision_first"), \
                 patch("automation.file_organizer._load_organize_path",
                       return_value="screenshot_path"), \
                 patch("automation.file_organizer._load_move_confidence_threshold",
                       return_value=0.0), \
                 patch("automation.qwen_vl_recognizer.QwenVLRecognizer") as mock_recognizer_cls, \
                 patch("pywinauto.application.Application") as mock_app_cls, \
                 patch("subprocess.Popen"), \
                 patch("time.sleep"), \
                 patch("execution.action_engine.ActionEngine"), \
                 patch("perception.dpi_adapter.DPIAdapter",
                       return_value=_make_dpi_adapter(scale=1.0)):

                # QwenVLRecognizer returns empty (no VL matches, falls through to pywinauto)
                mock_recognizer = MagicMock()
                mock_recognizer.recognize_file_icons.return_value = []
                mock_recognizer_cls.return_value = mock_recognizer

                # pywinauto connects and returns our mock window
                mock_app_instance = MagicMock()
                mock_app_instance.top_window.return_value = mock_win
                mock_app_cls.return_value.connect.return_value = mock_app_instance
                mock_app_cls.return_value.return_value = mock_app_instance

                try:
                    run_file_organizer(
                        source_dir=src_dir,
                        target_dir=tgt_dir,
                        progress_callback=_noop_cb,
                        stop_event=stop_event,
                        detection_cache=detection_cache,
                    )
                except Exception:
                    pass  # We only care about cache update calls

        # detection_cache.update() must have been called at least once
        # (either with bbox data or with clear — both are valid cache writes)
        # The key assertion: the file organizer DOES write to detection_cache
        # This behavior must be preserved after the fix.
        assert len(update_calls) > 0, (
            "file_organizer.py must call detection_cache.update() during vision_first mode. "
            "This behavior must be preserved after the fix."
        )

    def test_file_organizer_cache_update_contains_file_label(self) -> None:
        """detection_cache.update() is called with the file's name as label.

        **Validates: Requirement 3.3**
        """
        import threading
        from automation.file_organizer import run_file_organizer

        detection_cache = DetectionCache()
        stop_event = threading.Event()
        update_calls: list[list[BoundingBoxDict]] = []

        original_update = detection_cache.update

        def spy_update(boxes: list[BoundingBoxDict]) -> None:
            update_calls.append(list(boxes))
            original_update(boxes)

        detection_cache.update = spy_update  # type: ignore[method-assign]

        import tempfile
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as tgt_dir:

            test_file = Path(src_dir) / "my_report.pdf"
            test_file.write_bytes(b"fake pdf")

            mock_rect = MagicMock()
            mock_rect.left = 50
            mock_rect.top = 100
            mock_rect.right = 200
            mock_rect.bottom = 150

            mock_file_item = MagicMock()
            mock_file_item.rectangle.return_value = mock_rect

            mock_win = MagicMock()
            mock_win.child_window.return_value = mock_file_item

            with patch("automation.file_organizer._load_organize_mode",
                       return_value="vision_first"), \
                 patch("automation.file_organizer._load_organize_path",
                       return_value="screenshot_path"), \
                 patch("automation.file_organizer._load_move_confidence_threshold",
                       return_value=0.0), \
                 patch("automation.qwen_vl_recognizer.QwenVLRecognizer") as mock_recognizer_cls, \
                 patch("pywinauto.application.Application") as mock_app_cls, \
                 patch("subprocess.Popen"), \
                 patch("time.sleep"), \
                 patch("execution.action_engine.ActionEngine"), \
                 patch("perception.dpi_adapter.DPIAdapter",
                       return_value=_make_dpi_adapter(scale=1.0)):

                mock_recognizer = MagicMock()
                mock_recognizer.recognize_file_icons.return_value = []
                mock_recognizer_cls.return_value = mock_recognizer

                mock_app_instance = MagicMock()
                mock_app_instance.top_window.return_value = mock_win
                mock_app_cls.return_value.connect.return_value = mock_app_instance

                try:
                    run_file_organizer(
                        source_dir=src_dir,
                        target_dir=tgt_dir,
                        progress_callback=_noop_cb,
                        stop_event=stop_event,
                        detection_cache=detection_cache,
                    )
                except Exception:
                    pass

        # Find any update call that contains the file label
        all_boxes = [box for call_boxes in update_calls for box in call_boxes]
        labels_seen = [box.get("label", "") for box in all_boxes]
        assert any("my_report.pdf" in lbl for lbl in labels_seen), (
            f"Expected detection_cache.update() to be called with label containing "
            f"'my_report.pdf'. Labels seen: {labels_seen}. "
            f"file_organizer.py cache write pattern must be preserved."
        )


# ---------------------------------------------------------------------------
# Preservation Test 3 — ActionEngine single to_physical call
#
# ActionEngine.click() must call DPIAdapter.to_physical() exactly once.
# The fix is in software_installer.py (the caller), not in ActionEngine.
# This contract must remain unchanged.
#
# Validates: Requirement 3.2
# ---------------------------------------------------------------------------

class TestPreservation3ActionEngineSingleToPhysicalCall:
    """Preservation: ActionEngine.click() calls to_physical() exactly once.

    **Validates: Requirement 3.2**
    """

    def test_to_physical_called_exactly_once_on_click(self) -> None:
        """ActionEngine.click(100, 200) calls DPIAdapter.to_physical exactly once.

        **Validates: Requirement 3.2**
        """
        adapter = _make_dpi_adapter(scale=1.5)
        engine = ActionEngine(dpi_adapter=adapter)

        to_physical_call_count = [0]
        original_to_physical = adapter.to_physical

        def counting_to_physical(x: int, y: int, monitor_index: int = 0) -> tuple[int, int]:
            to_physical_call_count[0] += 1
            return original_to_physical(x, y, monitor_index)

        adapter.to_physical = counting_to_physical  # type: ignore[method-assign]

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo"), \
             patch("pyautogui.click"), \
             patch("time.sleep"):
            engine.click(100, 200)

        assert to_physical_call_count[0] == 1, (
            f"ActionEngine.click() must call to_physical() exactly once, "
            f"but it was called {to_physical_call_count[0]} time(s). "
            f"The fix must not change this contract."
        )

    @given(
        lx=st.integers(min_value=0, max_value=1800),
        ly=st.integers(min_value=0, max_value=900),
        scale=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_to_physical_called_exactly_once_for_any_coords(
        self, lx: int, ly: int, scale: float
    ) -> None:
        """Property: for any (lx, ly, scale), ActionEngine.click() calls to_physical exactly once.

        **Validates: Requirement 3.2**
        """
        adapter = _make_dpi_adapter(scale=scale)
        engine = ActionEngine(dpi_adapter=adapter)

        to_physical_call_count = [0]
        original_to_physical = adapter.to_physical

        def counting_to_physical(x: int, y: int, monitor_index: int = 0) -> tuple[int, int]:
            to_physical_call_count[0] += 1
            return original_to_physical(x, y, monitor_index)

        adapter.to_physical = counting_to_physical  # type: ignore[method-assign]

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo"), \
             patch("pyautogui.click"), \
             patch("time.sleep"):
            engine.click(lx, ly)

        assert to_physical_call_count[0] == 1, (
            f"ActionEngine.click({lx}, {ly}, scale={scale}) called to_physical "
            f"{to_physical_call_count[0]} time(s), expected exactly 1."
        )
