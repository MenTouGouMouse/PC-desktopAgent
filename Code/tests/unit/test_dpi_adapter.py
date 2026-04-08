"""Unit tests for perception/dpi_adapter.py — DPIAdapter coordinate conversion."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from perception.dpi_adapter import DPIAdapter, MonitorInfo, _enumerate_monitors


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


# ---------------------------------------------------------------------------
# to_physical — basic math
# ---------------------------------------------------------------------------

class TestToPhysical:
    def test_scale_100_percent_identity(self) -> None:
        """scale=1.0: physical coords equal logical coords (no offset)."""
        adapter = _make_adapter(scale=1.0)
        assert adapter.to_physical(100, 200) == (100, 200)

    def test_scale_125_percent(self) -> None:
        """125% DPI: logical (100, 100) → physical (125, 125)."""
        adapter = _make_adapter(scale=1.25)
        assert adapter.to_physical(100, 100) == (125, 125)

    def test_scale_150_percent(self) -> None:
        """150% DPI: logical (200, 300) → physical (300, 450)."""
        adapter = _make_adapter(scale=1.5)
        assert adapter.to_physical(200, 300) == (300, 450)

    def test_scale_200_percent(self) -> None:
        adapter = _make_adapter(scale=2.0)
        assert adapter.to_physical(50, 75) == (100, 150)

    def test_rounding(self) -> None:
        """Result must be rounded to nearest integer."""
        adapter = _make_adapter(scale=1.25)
        # 1 * 1.25 = 1.25 → rounds to 1
        px, py = adapter.to_physical(1, 1)
        assert px == round(1 * 1.25)
        assert py == round(1 * 1.25)

    def test_zero_coords(self) -> None:
        adapter = _make_adapter(scale=1.5)
        assert adapter.to_physical(0, 0) == (0, 0)

    def test_negative_coords(self) -> None:
        """Negative logical coords are valid (e.g. secondary monitor to the left)."""
        adapter = _make_adapter(scale=1.0)
        assert adapter.to_physical(-100, -50) == (-100, -50)


# ---------------------------------------------------------------------------
# to_physical — multi-monitor offset
# ---------------------------------------------------------------------------

class TestToPhysicalMultiMonitor:
    def test_monitor_offset_added(self) -> None:
        """Global monitor offset must be added to the scaled coordinate."""
        adapter = _make_adapter(scale=1.0, left=1920, top=0)
        assert adapter.to_physical(100, 200) == (2020, 200)

    def test_monitor_offset_with_scale(self) -> None:
        """Offset is added after scaling."""
        adapter = _make_adapter(scale=1.25, left=1920, top=100)
        # logical (100, 100) → scaled (125, 125) → + offset (1920, 100) = (2045, 225)
        assert adapter.to_physical(100, 100) == (2045, 225)

    def test_fallback_to_monitor_0_on_invalid_index(self) -> None:
        """Out-of-range monitor_index falls back to monitor 0 without raising."""
        adapter = _make_adapter(scale=1.0)
        result = adapter.to_physical(10, 20, monitor_index=99)
        assert result == (10, 20)


# ---------------------------------------------------------------------------
# to_logical — basic math
# ---------------------------------------------------------------------------

class TestToLogical:
    def test_scale_100_percent_identity(self) -> None:
        adapter = _make_adapter(scale=1.0)
        assert adapter.to_logical(100, 200) == (100, 200)

    def test_scale_125_percent(self) -> None:
        adapter = _make_adapter(scale=1.25)
        assert adapter.to_logical(125, 125) == (100, 100)

    def test_scale_150_percent(self) -> None:
        adapter = _make_adapter(scale=1.5)
        assert adapter.to_logical(300, 450) == (200, 300)

    def test_zero_coords(self) -> None:
        adapter = _make_adapter(scale=2.0)
        assert adapter.to_logical(0, 0) == (0, 0)


# ---------------------------------------------------------------------------
# Round-trip: to_physical → to_logical
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.parametrize("lx,ly,scale", [
        (0, 0, 1.0),
        (100, 200, 1.0),
        (100, 100, 1.25),
        (200, 300, 1.5),
        (50, 75, 2.0),
    ])
    def test_round_trip_no_offset(self, lx: int, ly: int, scale: float) -> None:
        """to_logical(to_physical(lx, ly)) should recover the original coords."""
        adapter = _make_adapter(scale=scale)
        px, py = adapter.to_physical(lx, ly)
        recovered_lx, recovered_ly = adapter.to_logical(px, py)
        assert recovered_lx == lx
        assert recovered_ly == ly

    @pytest.mark.parametrize("lx,ly,scale,left,top", [
        (100, 200, 1.0, 1920, 0),
        (100, 100, 1.25, 1920, 100),
    ])
    def test_round_trip_with_offset(
        self, lx: int, ly: int, scale: float, left: int, top: int
    ) -> None:
        adapter = _make_adapter(scale=scale, left=left, top=top)
        px, py = adapter.to_physical(lx, ly)
        recovered_lx, recovered_ly = adapter.to_logical(px, py)
        assert recovered_lx == lx
        assert recovered_ly == ly


# ---------------------------------------------------------------------------
# DPIAdapter constructor — scale_factor override
# ---------------------------------------------------------------------------

class TestConstructorOverride:
    def test_scale_factor_override_sets_all_monitors(self) -> None:
        """Passing scale_factor= to __init__ overrides all monitor scale factors."""
        with patch("perception.dpi_adapter._enumerate_monitors") as mock_enum:
            mock_enum.return_value = [
                MonitorInfo(index=0, left=0, top=0, scale_factor=1.5),
            ]
            adapter = DPIAdapter(scale_factor=1.25)
        assert adapter.scale_factor == 1.25
        assert adapter._monitors[0].scale_factor == 1.25

    def test_no_override_uses_system_value(self) -> None:
        """Without override, scale_factor comes from the first enumerated monitor."""
        with patch("perception.dpi_adapter._enumerate_monitors") as mock_enum:
            mock_enum.return_value = [
                MonitorInfo(index=0, left=0, top=0, scale_factor=1.5),
            ]
            adapter = DPIAdapter()
        assert adapter.scale_factor == 1.5


# ---------------------------------------------------------------------------
# _enumerate_monitors — non-Windows fallback
# ---------------------------------------------------------------------------

class TestEnumerateMonitorsFallback:
    def test_non_windows_returns_default(self) -> None:
        """On non-Windows, _enumerate_monitors returns a single 1.0-scale monitor."""
        with patch.object(sys, "platform", "linux"):
            monitors = _enumerate_monitors()
        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0
        assert monitors[0].left == 0
        assert monitors[0].top == 0

    def test_ctypes_exception_returns_default(self) -> None:
        """If ctypes calls raise, fall back to single monitor with scale_factor=1.0."""
        with patch.object(sys, "platform", "win32"):
            with patch("ctypes.windll", side_effect=AttributeError("no windll")):
                monitors = _enumerate_monitors()
        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0


# ---------------------------------------------------------------------------
# monitor_count and get_monitor_info
# ---------------------------------------------------------------------------

class TestMonitorInfo:
    def test_monitor_count(self) -> None:
        adapter = _make_adapter(scale=1.0)
        assert adapter.monitor_count == 1

    def test_get_monitor_info_valid(self) -> None:
        adapter = _make_adapter(scale=1.25, left=100, top=50)
        info = adapter.get_monitor_info(0)
        assert info.scale_factor == 1.25
        assert info.left == 100
        assert info.top == 50

    def test_get_monitor_info_invalid_index_fallback(self) -> None:
        adapter = _make_adapter(scale=1.0)
        info = adapter.get_monitor_info(99)
        assert info.index == 0


# ---------------------------------------------------------------------------
# Property-Based Tests — Property 6: DPI 坐标转换数学正确性
# Feature: cv-desktop-automation-agent, Property 6: DPI 坐标转换数学正确性
# Validates: Requirements 3.2, 3.4
# ---------------------------------------------------------------------------

class TestDPIPropertyBased:
    # Feature: cv-desktop-automation-agent, Property 6: DPI 坐标转换数学正确性
    @given(
        st.integers(-10000, 10000),
        st.integers(-10000, 10000),
        st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_dpi_to_physical_math_correctness(self, lx: int, ly: int, scale: float) -> None:
        """Property 6: to_physical(lx, ly) must equal (round(lx * scale), round(ly * scale)).

        Validates: Requirements 3.2, 3.4
        """
        adapter = _make_adapter(scale=scale)
        px, py = adapter.to_physical(lx, ly)
        assert px == round(lx * scale)
        assert py == round(ly * scale)

    # Feature: cv-desktop-automation-agent, Property 6: DPI 坐标转换数学正确性 — scale=1.0 identity
    @given(
        st.integers(-10000, 10000),
        st.integers(-10000, 10000),
    )
    @settings(max_examples=100)
    def test_dpi_scale_1_identity(self, lx: int, ly: int) -> None:
        """Property 6 (Req 3.4): When scale_factor=1.0, to_physical must return (lx, ly) exactly.

        Validates: Requirement 3.4
        """
        adapter = _make_adapter(scale=1.0)
        px, py = adapter.to_physical(lx, ly)
        assert px == lx
        assert py == ly

    # Feature: cv-desktop-automation-agent, Property 6: DPI 坐标转换数学正确性 — round-trip
    @given(
        st.integers(-10000, 10000),
        st.integers(-10000, 10000),
        st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_dpi_round_trip_within_rounding_error(self, lx: int, ly: int, scale: float) -> None:
        """Property 6: to_logical(to_physical(lx, ly)) should approximately equal (lx, ly) within rounding error.

        Validates: Requirements 3.2, 3.4
        """
        adapter = _make_adapter(scale=scale)
        px, py = adapter.to_physical(lx, ly)
        recovered_lx, recovered_ly = adapter.to_logical(px, py)
        # Rounding in both directions can introduce at most 1 unit of error
        assert abs(recovered_lx - lx) <= 1
        assert abs(recovered_ly - ly) <= 1


# ---------------------------------------------------------------------------
# _enumerate_monitors — Windows ctypes path
# ---------------------------------------------------------------------------

class TestEnumerateMonitorsWindows:
    def test_windows_successful_enumeration(self) -> None:
        """在 Windows 上成功枚举显示器时，应返回正确的 MonitorInfo 列表。"""
        import ctypes

        # Simulate EnumDisplayMonitors calling the callback once with a monitor
        def fake_enum_display_monitors(hdc, clip, callback, data):
            # Build a fake RECT-like object
            class FakeRect:
                left = 0
                top = 0

            class FakePointer:
                def __init__(self):
                    self.contents = FakeRect()

            callback(12345, 0, FakePointer(), 0)
            return True

        mock_user32 = MagicMock()
        mock_user32.EnumDisplayMonitors.side_effect = fake_enum_display_monitors

        mock_shcore = MagicMock()
        # GetScaleFactorForMonitor: set device_scale to 125 (125%) via byref side effect
        def fake_get_scale(h_monitor, byref_val):
            byref_val._obj.value = 125
            return 0  # S_OK

        mock_shcore.GetScaleFactorForMonitor.side_effect = fake_get_scale

        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32
        mock_windll.shcore = mock_shcore

        with patch.object(sys, "platform", "win32"), \
             patch("ctypes.windll", mock_windll):
            monitors = _enumerate_monitors()

        assert len(monitors) == 1
        assert monitors[0].index == 0
        assert monitors[0].left == 0
        assert monitors[0].top == 0

    def test_windows_get_scale_factor_fails_hresult(self) -> None:
        """GetScaleFactorForMonitor 返回非零 HRESULT 时，应回退到 scale_factor=1.0。"""
        def fake_enum(hdc, clip, callback, data):
            class FakeRect:
                left = 100
                top = 50

            class FakePointer:
                def __init__(self):
                    self.contents = FakeRect()

            callback(99, 0, FakePointer(), 0)
            return True

        mock_user32 = MagicMock()
        mock_user32.EnumDisplayMonitors.side_effect = fake_enum

        mock_shcore = MagicMock()
        mock_shcore.GetScaleFactorForMonitor.return_value = 0x80004005  # E_FAIL

        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32
        mock_windll.shcore = mock_shcore

        with patch.object(sys, "platform", "win32"), \
             patch("ctypes.windll", mock_windll):
            monitors = _enumerate_monitors()

        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0

    def test_windows_get_scale_factor_zero_value(self) -> None:
        """GetScaleFactorForMonitor 返回 S_OK 但 value=0 时，应回退到 scale_factor=1.0。"""
        def fake_enum(hdc, clip, callback, data):
            class FakeRect:
                left = 0
                top = 0

            class FakePointer:
                def __init__(self):
                    self.contents = FakeRect()

            callback(42, 0, FakePointer(), 0)
            return True

        mock_user32 = MagicMock()
        mock_user32.EnumDisplayMonitors.side_effect = fake_enum

        mock_shcore = MagicMock()
        def fake_get_scale_zero(h_monitor, byref_val):
            byref_val._obj.value = 0
            return 0  # S_OK but value=0

        mock_shcore.GetScaleFactorForMonitor.side_effect = fake_get_scale_zero

        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32
        mock_windll.shcore = mock_shcore

        with patch.object(sys, "platform", "win32"), \
             patch("ctypes.windll", mock_windll):
            monitors = _enumerate_monitors()

        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0

    def test_windows_get_scale_factor_exception_falls_back(self) -> None:
        """GetScaleFactorForMonitor 抛出异常时，应回退到 scale_factor=1.0 并继续。"""
        def fake_enum(hdc, clip, callback, data):
            class FakeRect:
                left = 0
                top = 0

            class FakePointer:
                def __init__(self):
                    self.contents = FakeRect()

            callback(77, 0, FakePointer(), 0)
            return True

        mock_user32 = MagicMock()
        mock_user32.EnumDisplayMonitors.side_effect = fake_enum

        mock_shcore = MagicMock()
        mock_shcore.GetScaleFactorForMonitor.side_effect = OSError("DPI read failed")

        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32
        mock_windll.shcore = mock_shcore

        with patch.object(sys, "platform", "win32"), \
             patch("ctypes.windll", mock_windll):
            monitors = _enumerate_monitors()

        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0

    def test_windows_empty_monitor_list_returns_default(self) -> None:
        """EnumDisplayMonitors 未调用回调（无显示器）时，应返回默认单显示器。"""
        mock_user32 = MagicMock()
        mock_user32.EnumDisplayMonitors.return_value = True  # callback never called

        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32

        with patch.object(sys, "platform", "win32"), \
             patch("ctypes.windll", mock_windll):
            monitors = _enumerate_monitors()

        assert len(monitors) == 1
        assert monitors[0].scale_factor == 1.0
