"""
Bug Condition Exploration Tests — click-dpi-overlay-fix

These tests MUST FAIL on unfixed code — failure confirms the bugs exist.
DO NOT attempt to fix the tests or the code when they fail.

Bug 1: DPI double-scaling
  On unfixed code, software_installer.py passes physical-pixel bbox center
  directly to ActionEngine.click(), which calls DPIAdapter.to_physical()
  again, doubling the scale. pyautogui.moveTo receives (1400, 840) instead
  of the correct physical target (700, 420) when scale_factor=2.0.

Bug 2: Missing DetectionCache write
  On unfixed code, run_software_installer() never writes to DetectionCache
  after a successful locate_by_text() call, so the overlay never renders.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from automation.object_detector import DetectionCache
from perception.element_locator import ElementResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_callback(step: str, percent: int) -> None:
    pass


def _make_screenshot() -> np.ndarray:
    """Return a minimal dummy screenshot (1x1 BGR image)."""
    return np.zeros((1, 1, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Bug 1: DPI Double-Scaling
#
# Physical bbox (640, 400, 120, 40) with scale_factor=2.0:
#   center = (640 + 120//2, 400 + 40//2) = (700, 420)  — physical pixels
#
# EXPECTED (fixed): pyautogui.moveTo called with (700, 420)
#   software_installer converts physical→logical: to_logical(700,420,2.0)=(350,210)
#   ActionEngine.click(350, 210) → to_physical(350,210,2.0) = (700, 420) ✓
#
# ACTUAL (unfixed): pyautogui.moveTo called with (1400, 840)
#   software_installer passes cx=700, cy=420 directly to ActionEngine.click()
#   ActionEngine.click(700, 420) → to_physical(700,420,2.0) = (1400, 840) ✗
# ---------------------------------------------------------------------------

class TestBug1DpiDoubleScaling:
    """Bug 1: DPI double-scaling exploration test.

    EXPECTED TO FAIL on unfixed code — this is the success case for exploration.
    """

    def test_moveto_receives_physical_center_not_doubled(self) -> None:
        """**Validates: Requirements 1.1, 1.2, 1.3**

        Mock locate_by_text to return physical bbox (640, 400, 120, 40) with
        strategy="ocr" and scale_factor=2.0. Assert pyautogui.moveTo is called
        with (700, 420) — the original physical center.

        On UNFIXED code: moveTo receives (1400, 840) — FAILS (expected).
        On FIXED code: moveTo receives (700, 420) — PASSES.
        """
        from automation.software_installer import run_software_installer

        # Physical bbox from OCR: (x=640, y=400, w=120, h=40)
        # Physical center: cx = 640 + 120//2 = 700, cy = 400 + 40//2 = 420
        mock_result = ElementResult(
            name="下一步",
            bbox=(640, 400, 120, 40),
            confidence=0.9,
            strategy="ocr",
        )

        stop_event = threading.Event()
        moveto_calls: list[tuple[int, int]] = []

        def capture_moveto(x: int, y: int) -> None:
            moveto_calls.append((x, y))
            # Stop after first click so the test doesn't loop forever
            stop_event.set()

        # Build a real DPIAdapter with scale_factor=2.0 and monitor offset (0, 0)
        # so to_physical(700, 420) = (1400, 840) and to_logical(700, 420) = (350, 210).
        # We patch _enumerate_monitors to guarantee left=0, top=0 regardless of the
        # real display configuration on the test machine.
        from perception.dpi_adapter import MonitorInfo

        fixed_monitors = [MonitorInfo(index=0, left=0, top=0, scale_factor=2.0)]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer._activate_installer_window"), \
             patch("time.sleep"), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   return_value=mock_result), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=_make_screenshot()), \
             patch("perception.dpi_adapter._enumerate_monitors", return_value=fixed_monitors), \
             patch("pyautogui.moveTo", side_effect=capture_moveto), \
             patch("pyautogui.click"), \
             patch("pyautogui.size", return_value=(2560, 1600)):

            try:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_callback,
                    stop_event,
                )
            except Exception:
                pass  # We only care about what moveTo was called with

        assert len(moveto_calls) >= 1, "pyautogui.moveTo was never called"

        first_call = moveto_calls[0]
        assert first_call == (700, 420), (
            f"Bug 1 detected: pyautogui.moveTo received {first_call} instead of (700, 420). "
            f"On unfixed code, physical coords (700, 420) are passed to ActionEngine.click() "
            f"which applies to_physical(scale=2.0) again, producing (1400, 840)."
        )


# ---------------------------------------------------------------------------
# Bug 2: Missing DetectionCache Write
#
# EXPECTED (fixed): detection_cache is non-empty after a successful locate call
# ACTUAL (unfixed): detection_cache remains empty — FAILS (expected)
# ---------------------------------------------------------------------------

class TestBug2MissingDetectionCacheWrite:
    """Bug 2: Missing DetectionCache write exploration test.

    EXPECTED TO FAIL on unfixed code — this is the success case for exploration.
    """

    def test_detection_cache_written_after_successful_locate(self) -> None:
        """**Validates: Requirements 1.4, 1.5**

        Create a real DetectionCache instance. Mock locate_by_text to return a
        successful ElementResult. Run a single installer step. Assert
        detection_cache is non-empty after the call.

        On UNFIXED code: detection_cache contains 0 entries — FAILS (expected).
        On FIXED code: detection_cache contains the expected entry — PASSES.
        """
        from automation.software_installer import run_software_installer

        mock_result = ElementResult(
            name="下一步",
            bbox=(300, 200, 80, 30),
            confidence=0.85,
            strategy="ocr",
        )

        detection_cache = DetectionCache()
        stop_event = threading.Event()

        def locate_side_effect(screenshot: np.ndarray, candidate: str) -> ElementResult:
            # Stop after first successful locate so the loop exits
            stop_event.set()
            return mock_result

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer._activate_installer_window"), \
             patch("time.sleep"), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=locate_side_effect), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=_make_screenshot()), \
             patch("execution.action_engine.ActionEngine.click", return_value=True), \
             patch("pyautogui.size", return_value=(1920, 1080)):

            try:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_callback,
                    stop_event,
                    detection_cache=detection_cache,
                )
            except TypeError:
                # On unfixed code, run_software_installer doesn't accept
                # detection_cache parameter — this itself is evidence of Bug 2
                pass
            except Exception:
                pass  # We only care about the cache state

        cached_entries = detection_cache.get()
        assert len(cached_entries) > 0, (
            f"Bug 2 detected: DetectionCache contains {len(cached_entries)} entries "
            f"after a successful locate_by_text() call. "
            f"On unfixed code, run_software_installer() never writes to DetectionCache, "
            f"so the overlay never renders during an installation session."
        )
