"""
Bug Condition Exploration Test — Bug 5a: ActionEngine.click 缺少前置 moveTo

这些测试在未修复代码上 MUST FAIL，失败即证明 bug 存在。
DO NOT fix the code when tests fail.

Expected outcome on UNFIXED code: FAILS
- pyautogui.moveTo is NOT called before pyautogui.click
- Fixed code should call moveTo before click

Validates: Requirements 1.9
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter


@pytest.fixture
def adapter_1x() -> DPIAdapter:
    return DPIAdapter(scale_factor=1.0)


@pytest.fixture
def engine(adapter_1x: DPIAdapter) -> ActionEngine:
    return ActionEngine(dpi_adapter=adapter_1x)


# ---------------------------------------------------------------------------
# Bug condition: moveTo not called before click
# ---------------------------------------------------------------------------

class TestClickMoveToBugCondition:
    def test_moveto_called_before_click(self, engine: ActionEngine):
        """
        Bug condition: ActionEngine.click() does NOT call pyautogui.moveTo before click.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed code calls pyautogui.click(px, py) directly without moveTo
        - Fixed code should call moveTo(px, py) first, then click(px, py)

        Counterexample: moveTo is never called (call_count=0)
        """
        call_order: list[str] = []

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo", side_effect=lambda *a, **kw: call_order.append("moveTo")), \
             patch("pyautogui.click", side_effect=lambda *a, **kw: call_order.append("click")), \
             patch("time.sleep"):
            engine.click(100, 100)

        # FAILS on unfixed code: moveTo is never called
        assert "moveTo" in call_order, (
            f"Expected pyautogui.moveTo to be called before pyautogui.click, "
            f"but call_order was: {call_order!r}. "
            f"Bug: unfixed code calls pyautogui.click directly without moveTo."
        )

        # moveTo must come BEFORE click
        assert call_order.index("moveTo") < call_order.index("click"), (
            f"Expected moveTo to be called BEFORE click, "
            f"but call_order was: {call_order!r}."
        )

    def test_moveto_called_with_physical_coordinates(self, engine: ActionEngine):
        """
        moveTo should be called with the same physical coordinates as click.

        EXPECTED OUTCOME on UNFIXED code: FAILS (moveTo not called at all)
        """
        moveto_args: list[tuple] = []
        click_args: list[tuple] = []

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo", side_effect=lambda *a, **kw: moveto_args.append(a)), \
             patch("pyautogui.click", side_effect=lambda *a, **kw: click_args.append(a)), \
             patch("time.sleep"):
            engine.click(100, 100)

        assert len(moveto_args) >= 1, (
            f"Expected pyautogui.moveTo to be called at least once, "
            f"but it was not called. "
            f"Bug: unfixed code skips moveTo entirely."
        )
        # moveTo and click should use the same physical coordinates
        assert moveto_args[0] == click_args[0], (
            f"Expected moveTo and click to use same coordinates, "
            f"but moveTo got {moveto_args[0]!r} and click got {click_args[0]!r}."
        )

    def test_moveto_called_for_double_click(self, engine: ActionEngine):
        """
        moveTo should also be called before doubleClick.

        EXPECTED OUTCOME on UNFIXED code: FAILS (moveTo not called)
        """
        call_order: list[str] = []

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo", side_effect=lambda *a, **kw: call_order.append("moveTo")), \
             patch("pyautogui.doubleClick", side_effect=lambda *a, **kw: call_order.append("doubleClick")), \
             patch("time.sleep"):
            engine.click(100, 100, click_type="double")

        assert "moveTo" in call_order, (
            f"Expected moveTo before doubleClick, but call_order was: {call_order!r}."
        )
        assert call_order.index("moveTo") < call_order.index("doubleClick"), (
            f"Expected moveTo BEFORE doubleClick, but got: {call_order!r}."
        )

    def test_moveto_called_for_right_click(self, engine: ActionEngine):
        """
        moveTo should also be called before rightClick.

        EXPECTED OUTCOME on UNFIXED code: FAILS (moveTo not called)
        """
        call_order: list[str] = []

        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo", side_effect=lambda *a, **kw: call_order.append("moveTo")), \
             patch("pyautogui.rightClick", side_effect=lambda *a, **kw: call_order.append("rightClick")), \
             patch("time.sleep"):
            engine.click(100, 100, click_type="right")

        assert "moveTo" in call_order, (
            f"Expected moveTo before rightClick, but call_order was: {call_order!r}."
        )
        assert call_order.index("moveTo") < call_order.index("rightClick"), (
            f"Expected moveTo BEFORE rightClick, but got: {call_order!r}."
        )


# ---------------------------------------------------------------------------
# Preservation: out-of-bounds still returns False (should pass on unfixed code too)
# ---------------------------------------------------------------------------

class TestClickOutOfBoundsPreservation:
    def test_out_of_bounds_returns_false_no_moveto(self, engine: ActionEngine):
        """
        Preservation: out-of-bounds coordinates should return False without calling moveTo or click.
        This should pass on both fixed and unfixed code (Requirements 3.4).
        """
        with patch("pyautogui.size", return_value=(1920, 1080)), \
             patch("pyautogui.moveTo") as mock_moveto, \
             patch("pyautogui.click") as mock_click:
            result = engine.click(9999, 9999)

        assert result is False
        mock_moveto.assert_not_called()
        mock_click.assert_not_called()
