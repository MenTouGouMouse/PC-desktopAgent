"""属性测试：ActionEngine 核心行为属性验证。

覆盖属性：
- Property 9: type_text 使用 pyperclip 粘贴
- Property 10: 点击前通过 DPI_Adapter 转换坐标
- Property 11: 坐标越界时返回 False 且不执行操作

# Feature: cv-desktop-automation-agent
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter, MonitorInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(scale: float = 1.0, left: int = 0, top: int = 0) -> DPIAdapter:
    """Create a DPIAdapter with a single mocked monitor."""
    monitor = MonitorInfo(index=0, left=left, top=top, scale_factor=scale)
    adapter = DPIAdapter.__new__(DPIAdapter)
    adapter._monitors = [monitor]
    adapter.scale_factor = scale
    return adapter


def _make_engine(scale: float = 1.0) -> ActionEngine:
    """Create an ActionEngine with a deterministic DPIAdapter."""
    return ActionEngine(dpi_adapter=_make_adapter(scale=scale))


# Strategies
non_empty_text_st = st.text(min_size=1, max_size=200)

# In-bounds coordinates for a 1920×1080 screen
inbounds_x_st = st.integers(min_value=0, max_value=1919)
inbounds_y_st = st.integers(min_value=0, max_value=1079)

# Out-of-bounds coordinates: x >= 1920 or y >= 1080, or negative
outofbounds_coords_st = st.one_of(
    # x too large
    st.tuples(
        st.integers(min_value=1920, max_value=9999),
        st.integers(min_value=0, max_value=1079),
    ),
    # y too large
    st.tuples(
        st.integers(min_value=0, max_value=1919),
        st.integers(min_value=1080, max_value=9999),
    ),
    # negative x
    st.tuples(
        st.integers(min_value=-9999, max_value=-1),
        st.integers(min_value=0, max_value=1079),
    ),
    # negative y
    st.tuples(
        st.integers(min_value=0, max_value=1919),
        st.integers(min_value=-9999, max_value=-1),
    ),
)

scale_st = st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False)

click_type_st = st.sampled_from(["single", "double", "right"])


# ---------------------------------------------------------------------------
# Property 9: type_text 使用 pyperclip 粘贴
# Feature: cv-desktop-automation-agent, Property 9: type_text 使用 pyperclip 粘贴
# Validates: Requirements 6.2, 6.5
# ---------------------------------------------------------------------------

class TestProperty9TypeTextUsesClipboard:
    """对任意非空文本，type_text 必须调用 pyperclip.copy(text) 写入剪贴板，
    再通过 Ctrl+V 粘贴，而不是逐字符调用 typewrite()。
    """

    @settings(max_examples=100)
    @given(text=non_empty_text_st)
    def test_pyperclip_copy_called_with_exact_text(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 9: type_text 使用 pyperclip 粘贴
        engine = _make_engine()
        with (
            patch("pyperclip.copy") as mock_copy,
            patch("pyautogui.hotkey"),
        ):
            result = engine.type_text(text)

        assert result is True
        mock_copy.assert_called_once_with(text)

    @settings(max_examples=100)
    @given(text=non_empty_text_st)
    def test_ctrl_v_hotkey_called_after_copy(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 9: type_text 使用 pyperclip 粘贴
        engine = _make_engine()
        call_order: list[str] = []

        with (
            patch("pyperclip.copy", side_effect=lambda t: call_order.append("copy")),
            patch("pyautogui.hotkey", side_effect=lambda *a: call_order.append("hotkey")),
        ):
            engine.type_text(text)

        # copy must happen before hotkey
        assert call_order == ["copy", "hotkey"]

    @settings(max_examples=100)
    @given(text=non_empty_text_st)
    def test_typewrite_never_called(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 9: type_text 使用 pyperclip 粘贴
        engine = _make_engine()
        with (
            patch("pyperclip.copy"),
            patch("pyautogui.hotkey"),
            patch("pyautogui.typewrite") as mock_typewrite,
        ):
            engine.type_text(text)

        mock_typewrite.assert_not_called()

    @settings(max_examples=100)
    @given(text=non_empty_text_st)
    def test_hotkey_uses_ctrl_v(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 9: type_text 使用 pyperclip 粘贴
        engine = _make_engine()
        with (
            patch("pyperclip.copy"),
            patch("pyautogui.hotkey") as mock_hotkey,
        ):
            engine.type_text(text)

        mock_hotkey.assert_called_once_with("ctrl", "v")


# ---------------------------------------------------------------------------
# Property 10: 点击前通过 DPI_Adapter 转换坐标
# Feature: cv-desktop-automation-agent, Property 10: 点击前通过 DPI_Adapter 转换坐标
# Validates: Requirements 6.4
# ---------------------------------------------------------------------------

class TestProperty10ClickConvertsCoordinates:
    """对任意合法点击调用 click(lx, ly)，必须先调用 DPI_Adapter.to_physical(lx, ly)，
    再将转换后的物理坐标传给 pyautogui，而不是直接使用逻辑坐标。
    """

    @settings(max_examples=100)
    @given(
        lx=inbounds_x_st,
        ly=inbounds_y_st,
        scale=scale_st,
    )
    def test_to_physical_called_before_pyautogui(
        self, lx: int, ly: int, scale: float
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 10: 点击前通过 DPI_Adapter 转换坐标
        adapter = _make_adapter(scale=scale)
        engine = ActionEngine(dpi_adapter=adapter)
        call_order: list[str] = []

        original_to_physical = adapter.to_physical

        def spy_to_physical(x: int, y: int, monitor_index: int = 0) -> tuple[int, int]:
            call_order.append("to_physical")
            return original_to_physical(x, y, monitor_index)

        adapter.to_physical = spy_to_physical  # type: ignore[method-assign]

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo"),
            patch("time.sleep"),
            patch("pyautogui.click", side_effect=lambda *a, **kw: call_order.append("click")),
        ):
            engine.click(lx, ly)

        assert "to_physical" in call_order
        assert "click" in call_order
        assert call_order.index("to_physical") < call_order.index("click")

    @settings(max_examples=100)
    @given(
        lx=inbounds_x_st,
        ly=inbounds_y_st,
        scale=scale_st,
    )
    def test_pyautogui_receives_physical_coordinates(
        self, lx: int, ly: int, scale: float
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 10: 点击前通过 DPI_Adapter 转换坐标
        adapter = _make_adapter(scale=scale)
        engine = ActionEngine(dpi_adapter=adapter)
        expected_px = round(lx * scale)
        expected_py = round(ly * scale)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo"),
            patch("time.sleep"),
            patch("pyautogui.click") as mock_click,
        ):
            engine.click(lx, ly)

        mock_click.assert_called_once_with(expected_px, expected_py)

    @settings(max_examples=100)
    @given(
        lx=inbounds_x_st,
        ly=inbounds_y_st,
        scale=scale_st,
        click_type=click_type_st,
    )
    def test_all_click_types_use_physical_coordinates(
        self, lx: int, ly: int, scale: float, click_type: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 10: 点击前通过 DPI_Adapter 转换坐标
        adapter = _make_adapter(scale=scale)
        engine = ActionEngine(dpi_adapter=adapter)
        expected_px = round(lx * scale)
        expected_py = round(ly * scale)

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo"),
            patch("time.sleep"),
            patch("pyautogui.click") as mock_single,
            patch("pyautogui.doubleClick") as mock_double,
            patch("pyautogui.rightClick") as mock_right,
        ):
            engine.click(lx, ly, click_type=click_type)  # type: ignore[arg-type]

        if click_type == "single":
            mock_single.assert_called_once_with(expected_px, expected_py)
        elif click_type == "double":
            mock_double.assert_called_once_with(expected_px, expected_py)
        elif click_type == "right":
            mock_right.assert_called_once_with(expected_px, expected_py)


# ---------------------------------------------------------------------------
# Property 11: 坐标越界时返回 False 且不执行操作
# Feature: cv-desktop-automation-agent, Property 11: 坐标越界时返回 False 且不执行操作
# Validates: Requirements 6.6
# ---------------------------------------------------------------------------

class TestProperty11OutOfBoundsReturnsFalse:
    """对任意超出当前屏幕边界的目标坐标，click() 必须返回 False，
    且不调用任何 pyautogui 鼠标函数。
    """

    @settings(max_examples=100)
    @given(coords=outofbounds_coords_st)
    def test_out_of_bounds_returns_false(
        self, coords: tuple[int, int]
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 11: 坐标越界时返回 False 且不执行操作
        lx, ly = coords
        engine = _make_engine()

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
            patch("pyautogui.doubleClick") as mock_double,
            patch("pyautogui.rightClick") as mock_right,
        ):
            result = engine.click(lx, ly)

        assert result is False

    @settings(max_examples=100)
    @given(coords=outofbounds_coords_st)
    def test_out_of_bounds_no_pyautogui_mouse_call(
        self, coords: tuple[int, int]
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 11: 坐标越界时返回 False 且不执行操作
        lx, ly = coords
        engine = _make_engine()

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
            patch("pyautogui.doubleClick") as mock_double,
            patch("pyautogui.rightClick") as mock_right,
        ):
            engine.click(lx, ly)

        mock_click.assert_not_called()
        mock_double.assert_not_called()
        mock_right.assert_not_called()

    @settings(max_examples=100)
    @given(
        coords=outofbounds_coords_st,
        click_type=click_type_st,
    )
    def test_out_of_bounds_all_click_types_return_false(
        self, coords: tuple[int, int], click_type: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 11: 坐标越界时返回 False 且不执行操作
        lx, ly = coords
        engine = _make_engine()

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click"),
            patch("pyautogui.doubleClick"),
            patch("pyautogui.rightClick"),
        ):
            result = engine.click(lx, ly, click_type=click_type)  # type: ignore[arg-type]

        assert result is False

    @settings(max_examples=100)
    @given(
        lx=inbounds_x_st,
        ly=inbounds_y_st,
    )
    def test_in_bounds_does_not_return_false(self, lx: int, ly: int) -> None:
        """Sanity check: in-bounds coordinates must NOT return False (returns True)."""
        # Feature: cv-desktop-automation-agent, Property 11: 坐标越界时返回 False 且不执行操作
        engine = _make_engine()

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo"),
            patch("time.sleep"),
            patch("pyautogui.click"),
        ):
            result = engine.click(lx, ly)

        assert result is True
