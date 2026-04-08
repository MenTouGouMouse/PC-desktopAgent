"""Unit and property-based tests for perception/screen_capturer.py.

Tests cover:
- capture_full: full-screen capture returns BGR numpy array
- capture_region: region capture returns correct shape
- get_monitor_info: returns monitor list
- Property 1: region capture returns correct-sized numpy array
- Property 2: invalid monitor index raises an exception
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from perception.screen_capturer import MonitorNotFoundError, ScreenCapturer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MONITORS = [
    {"left": 0, "top": 0, "width": 1920, "height": 1080},  # virtual combined
    {"left": 0, "top": 0, "width": 1920, "height": 1080},  # real monitor 0
]


def _make_mock_mss(grab_array: np.ndarray) -> MagicMock:
    """Build a mock mss context manager whose grab() returns the given array."""
    mock_screenshot = MagicMock()
    mock_screenshot.__array__ = MagicMock(return_value=grab_array)

    mock_instance = MagicMock()
    mock_instance.monitors = _MONITORS
    mock_instance.grab.return_value = mock_screenshot
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)
    return mock_instance


# ---------------------------------------------------------------------------
# Basic unit tests — capture_full
# ---------------------------------------------------------------------------

class TestCaptureFullUnit:
    def test_returns_ndarray(self) -> None:
        """capture_full must return a numpy ndarray."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            result = ScreenCapturer().capture_full(monitor_index=0)
        assert isinstance(result, np.ndarray)

    def test_bgra_sliced_to_bgr(self) -> None:
        """capture_full must strip the alpha channel, returning shape (H, W, 3)."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            result = ScreenCapturer().capture_full(monitor_index=0)
        assert result.shape == (1080, 1920, 3)

    def test_invalid_monitor_raises(self) -> None:
        """capture_full with out-of-range monitor_index must raise MonitorNotFoundError."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(MonitorNotFoundError):
                ScreenCapturer().capture_full(monitor_index=5)

    def test_negative_monitor_raises(self) -> None:
        """capture_full with negative monitor_index must raise MonitorNotFoundError."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(MonitorNotFoundError):
                ScreenCapturer().capture_full(monitor_index=-1)


# ---------------------------------------------------------------------------
# Basic unit tests — capture_region
# ---------------------------------------------------------------------------

class TestCaptureRegionUnit:
    def test_returns_ndarray(self) -> None:
        """capture_region must return a numpy ndarray."""
        bgra = np.zeros((100, 200, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            result = ScreenCapturer().capture_region(0, 0, 200, 100)
        assert isinstance(result, np.ndarray)

    def test_bgra_sliced_to_bgr(self) -> None:
        """capture_region must strip alpha, returning shape (height, width, 3)."""
        bgra = np.zeros((100, 200, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            result = ScreenCapturer().capture_region(0, 0, 200, 100)
        assert result.shape == (100, 200, 3)

    def test_grab_called_with_correct_region(self) -> None:
        """capture_region must pass the correct region dict to sct.grab."""
        bgra = np.zeros((50, 80, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            ScreenCapturer().capture_region(10, 20, 80, 50, monitor_index=0)
        call_args = mock_instance.grab.call_args[0][0]
        assert call_args["left"] == 10   # monitor left(0) + x(10)
        assert call_args["top"] == 20    # monitor top(0) + y(20)
        assert call_args["width"] == 80
        assert call_args["height"] == 50

    def test_invalid_monitor_raises(self) -> None:
        """capture_region with invalid monitor_index must raise MonitorNotFoundError."""
        bgra = np.zeros((50, 80, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(MonitorNotFoundError):
                ScreenCapturer().capture_region(0, 0, 80, 50, monitor_index=99)


# ---------------------------------------------------------------------------
# Basic unit tests — get_monitor_info
# ---------------------------------------------------------------------------

class TestGetMonitorInfoUnit:
    def test_returns_list(self) -> None:
        """get_monitor_info must return a list."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            info = ScreenCapturer().get_monitor_info()
        assert isinstance(info, list)

    def test_excludes_virtual_monitor(self) -> None:
        """get_monitor_info must exclude mss monitors[0] (virtual combined screen)."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        # _MONITORS has 1 virtual + 1 real → expect 1 entry
        with patch("mss.mss", return_value=mock_instance):
            info = ScreenCapturer().get_monitor_info()
        assert len(info) == 1

    def test_monitor_info_has_required_keys(self) -> None:
        """Each monitor info dict must contain index, left, top, width, height."""
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)
        with patch("mss.mss", return_value=mock_instance):
            info = ScreenCapturer().get_monitor_info()
        for entry in info:
            for key in ("index", "left", "top", "width", "height"):
                assert key in entry


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

class TestScreenCapturerProperties:
    # Feature: cv-desktop-automation-agent, Property 1: 区域截图返回正确尺寸的 numpy 数组
    @given(
        width=st.integers(min_value=1, max_value=500),
        height=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=100)
    def test_capture_region_returns_correct_shape(self, width: int, height: int) -> None:
        """Property 1: capture_region(x, y, width, height) must return np.ndarray with shape (height, width, 3).

        For any valid (width, height), the returned array must be exactly (height, width, 3).
        Validates: Requirements 1.1, 1.4, 1.6
        """
        # Build a BGRA array of the exact requested dimensions
        bgra = np.zeros((height, width, 4), dtype=np.uint8)

        mock_screenshot = MagicMock()
        mock_screenshot.__array__ = MagicMock(return_value=bgra)

        mock_instance = MagicMock()
        mock_instance.monitors = _MONITORS
        mock_instance.grab.return_value = mock_screenshot
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)

        with patch("mss.mss", return_value=mock_instance):
            result = ScreenCapturer().capture_region(0, 0, width, height, monitor_index=0)

        assert isinstance(result, np.ndarray), "capture_region must return np.ndarray"
        assert result.shape == (height, width, 3), (
            f"Expected shape ({height}, {width}, 3), got {result.shape}"
        )

    # Feature: cv-desktop-automation-agent, Property 2: 无效显示器索引抛出异常
    @given(monitor_index=st.integers(min_value=1, max_value=100))
    @settings(max_examples=100)
    def test_capture_region_invalid_monitor_index_raises(self, monitor_index: int) -> None:
        """Property 2 (out-of-range): capture_region with index >= num_real_monitors must raise an exception.

        The mock has exactly 1 real monitor (monitors[1]), so any monitor_index >= 1 is invalid.
        The exception must contain an error description (not silently fail or return empty array).
        Validates: Requirements 1.5
        """
        bgra = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)

        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(Exception) as exc_info:
                ScreenCapturer().capture_region(0, 0, 100, 100, monitor_index=monitor_index)

        # The exception must carry a meaningful description (not be empty)
        assert str(exc_info.value), "Exception message must not be empty"

    # Feature: cv-desktop-automation-agent, Property 2: 无效显示器索引抛出异常 (negative)
    @given(monitor_index=st.integers(min_value=-1000, max_value=-1))
    @settings(max_examples=100)
    def test_capture_region_negative_monitor_index_raises(self, monitor_index: int) -> None:
        """Property 2 (negative): capture_region with negative monitor_index must raise an exception.

        Negative indices are always invalid regardless of monitor count.
        Validates: Requirements 1.5
        """
        bgra = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)

        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(Exception) as exc_info:
                ScreenCapturer().capture_region(0, 0, 100, 100, monitor_index=monitor_index)

        assert str(exc_info.value), "Exception message must not be empty"

    # Feature: cv-desktop-automation-agent, Property 2: 无效显示器索引抛出异常 (capture_full)
    @given(monitor_index=st.integers(min_value=1, max_value=100))
    @settings(max_examples=100)
    def test_capture_full_invalid_monitor_index_raises(self, monitor_index: int) -> None:
        """Property 2: capture_full with index >= num_real_monitors must raise an exception.

        Validates: Requirements 1.5
        """
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_instance = _make_mock_mss(bgra)

        with patch("mss.mss", return_value=mock_instance):
            with pytest.raises(Exception) as exc_info:
                ScreenCapturer().capture_full(monitor_index=monitor_index)

        assert str(exc_info.value), "Exception message must not be empty"
