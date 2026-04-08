"""ActionEngine 单元测试。

测试 click、type_text、open_application、move_to 方法的核心行为，
包括坐标越界检测、DPI 转换、pyperclip 粘贴输入等关键场景。
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from execution.action_engine import ActionEngine, CoordinateOutOfBoundsError
from perception.dpi_adapter import DPIAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter_1x() -> DPIAdapter:
    """缩放比例 1.0 的 DPIAdapter（逻辑坐标 == 物理坐标）。"""
    return DPIAdapter(scale_factor=1.0)


@pytest.fixture
def adapter_125() -> DPIAdapter:
    """缩放比例 1.25 的 DPIAdapter。"""
    return DPIAdapter(scale_factor=1.25)


@pytest.fixture
def engine(adapter_1x: DPIAdapter) -> ActionEngine:
    """使用 1x DPI 的 ActionEngine 实例。"""
    return ActionEngine(dpi_adapter=adapter_1x)


# ---------------------------------------------------------------------------
# click — 正常路径
# ---------------------------------------------------------------------------

class TestClick:
    def test_single_click_calls_pyautogui_click(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(100, 200)
        assert result is True
        mock_click.assert_called_once_with(100, 200)

    def test_double_click_calls_double_click(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.doubleClick") as mock_dbl,
        ):
            result = engine.click(100, 200, click_type="double")
        assert result is True
        mock_dbl.assert_called_once_with(100, 200)

    def test_right_click_calls_right_click(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.rightClick") as mock_right,
        ):
            result = engine.click(100, 200, click_type="right")
        assert result is True
        mock_right.assert_called_once_with(100, 200)

    def test_dpi_125_converts_coordinates(self, adapter_125: DPIAdapter) -> None:
        """125% DPI 时物理坐标应为逻辑坐标 × 1.25。"""
        engine = ActionEngine(dpi_adapter=adapter_125)
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            engine.click(100, 80)
        mock_click.assert_called_once_with(125, 100)

    def test_click_uses_to_physical_before_pyautogui(self, adapter_1x: DPIAdapter) -> None:
        """确认 to_physical 在 pyautogui.click 之前被调用。"""
        engine = ActionEngine(dpi_adapter=adapter_1x)
        call_order: list[str] = []

        original_to_physical = adapter_1x.to_physical

        def spy_to_physical(lx: int, ly: int, monitor_index: int = 0) -> tuple[int, int]:
            call_order.append("to_physical")
            return original_to_physical(lx, ly, monitor_index)

        adapter_1x.to_physical = spy_to_physical  # type: ignore[method-assign]

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click", side_effect=lambda *a, **kw: call_order.append("click")),
        ):
            engine.click(50, 50)

        assert call_order == ["to_physical", "click"]

    # -- 越界 --

    def test_out_of_bounds_x_returns_false(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(2000, 100)
        assert result is False
        mock_click.assert_not_called()

    def test_out_of_bounds_y_returns_false(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(100, 1200)
        assert result is False
        mock_click.assert_not_called()

    def test_negative_x_returns_false(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(-1, 100)
        assert result is False
        mock_click.assert_not_called()

    def test_negative_y_returns_false(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(100, -1)
        assert result is False
        mock_click.assert_not_called()

    def test_boundary_coordinates_are_valid(self, engine: ActionEngine) -> None:
        """边界坐标（0,0）应合法。"""
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(0, 0)
        assert result is True
        mock_click.assert_called_once()

    def test_unknown_click_type_returns_false(self, engine: ActionEngine) -> None:
        """未知 click_type 应返回 False，不执行任何鼠标操作。"""
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            result = engine.click(100, 200, click_type="middle")  # type: ignore[arg-type]
        assert result is False
        mock_click.assert_not_called()


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------

class TestTypeText:
    def test_uses_pyperclip_copy(self, engine: ActionEngine) -> None:
        with (
            patch("pyperclip.copy") as mock_copy,
            patch("pyautogui.hotkey"),
        ):
            result = engine.type_text("hello")
        assert result is True
        mock_copy.assert_called_once_with("hello")

    def test_uses_ctrl_v_hotkey(self, engine: ActionEngine) -> None:
        with (
            patch("pyperclip.copy"),
            patch("pyautogui.hotkey") as mock_hotkey,
        ):
            engine.type_text("hello")
        mock_hotkey.assert_called_once_with("ctrl", "v")

    def test_does_not_use_typewrite(self, engine: ActionEngine) -> None:
        with (
            patch("pyperclip.copy"),
            patch("pyautogui.hotkey"),
            patch("pyautogui.typewrite") as mock_typewrite,
        ):
            engine.type_text("hello")
        mock_typewrite.assert_not_called()

    def test_chinese_text(self, engine: ActionEngine) -> None:
        with (
            patch("pyperclip.copy") as mock_copy,
            patch("pyautogui.hotkey"),
        ):
            engine.type_text("你好世界")
        mock_copy.assert_called_once_with("你好世界")

    def test_empty_string(self, engine: ActionEngine) -> None:
        """空字符串时应直接返回 True，不调用 pyperclip.copy（实现跳过空文本）。"""
        with (
            patch("pyperclip.copy") as mock_copy,
            patch("pyautogui.hotkey"),
        ):
            result = engine.type_text("")
        assert result is True
        mock_copy.assert_not_called()


# ---------------------------------------------------------------------------
# move_to
# ---------------------------------------------------------------------------

class TestMoveTo:
    def test_move_to_calls_pyautogui_moveto(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
        ):
            result = engine.move_to(300, 400)
        assert result is True
        mock_move.assert_called_once_with(300, 400)

    def test_move_to_out_of_bounds_returns_false(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
        ):
            result = engine.move_to(9999, 9999)
        assert result is False
        mock_move.assert_not_called()

    def test_move_to_dpi_converts_coordinates(self, adapter_125: DPIAdapter) -> None:
        engine = ActionEngine(dpi_adapter=adapter_125)
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo") as mock_move,
        ):
            engine.move_to(100, 80)
        mock_move.assert_called_once_with(125, 100)


# ---------------------------------------------------------------------------
# open_application
# ---------------------------------------------------------------------------

class TestOpenApplication:
    def test_open_application_uses_subprocess(self, engine: ActionEngine) -> None:
        """正常路径：subprocess.Popen 成功启动应用。"""
        with patch("subprocess.Popen") as mock_popen:
            result = engine.open_application("notepad.exe")
        assert result is True
        mock_popen.assert_called_once_with("notepad.exe", shell=True)

    def test_open_application_empty_name_returns_false(self, engine: ActionEngine) -> None:
        """空名称应返回 False，不调用 subprocess。"""
        with patch("subprocess.Popen") as mock_popen:
            result = engine.open_application("")
        assert result is False
        mock_popen.assert_not_called()

    def test_open_application_subprocess_fails_falls_back_to_pywinauto(self, engine: ActionEngine) -> None:
        """subprocess 失败时降级到 pywinauto Application(backend='uia')。"""
        mock_app = MagicMock()
        with (
            patch("subprocess.Popen", side_effect=OSError("not found")),
            patch("pywinauto.Application", return_value=mock_app) as mock_cls,
        ):
            result = engine.open_application("notepad.exe")
        assert result is True
        mock_cls.assert_called_once_with(backend="uia")
        mock_app.start.assert_called_once_with("notepad.exe")

    def test_open_application_both_fail_raises(self, engine: ActionEngine) -> None:
        """subprocess 和 pywinauto 都失败时应抛出异常（由 with_retry 处理）。"""
        mock_app = MagicMock()
        mock_app.start.side_effect = RuntimeError("pywinauto failed")
        with (
            patch("subprocess.Popen", side_effect=OSError("not found")),
            patch("pywinauto.Application", return_value=mock_app),
            patch("tenacity.nap.time.sleep"),
        ):
            from execution.retry_handler import RetryExhaustedError
            with pytest.raises(RetryExhaustedError):
                engine.open_application("bad_app.exe")


# ---------------------------------------------------------------------------
# key_press — new tests to cover lines 197-207
# ---------------------------------------------------------------------------

class TestKeyPress:
    def test_key_press_calls_pyautogui_press(self, engine: ActionEngine) -> None:
        with patch("pyautogui.press") as mock_press:
            result = engine.key_press("enter")
        assert result is True
        mock_press.assert_called_once_with("enter")

    def test_key_press_empty_key_returns_false(self, engine: ActionEngine) -> None:
        with patch("pyautogui.press") as mock_press:
            result = engine.key_press("")
        assert result is False
        mock_press.assert_not_called()

    def test_key_press_raises_on_exception(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.press", side_effect=RuntimeError("press failed")),
            patch("tenacity.nap.time.sleep"),
        ):
            from execution.retry_handler import RetryExhaustedError
            with pytest.raises(RetryExhaustedError):
                engine.key_press("tab")


# ---------------------------------------------------------------------------
# Exception paths — cover lines 114-116, 140-142, 234-236
# ---------------------------------------------------------------------------

class TestExceptionPaths:
    def test_click_raises_on_pyautogui_exception(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click", side_effect=RuntimeError("click failed")),
            patch("tenacity.nap.time.sleep"),
        ):
            from execution.retry_handler import RetryExhaustedError
            with pytest.raises(RetryExhaustedError):
                engine.click(100, 200)

    def test_type_text_raises_on_pyperclip_exception(self, engine: ActionEngine) -> None:
        with (
            patch("pyperclip.copy", side_effect=RuntimeError("clipboard failed")),
            patch("tenacity.nap.time.sleep"),
        ):
            from execution.retry_handler import RetryExhaustedError
            with pytest.raises(RetryExhaustedError):
                engine.type_text("hello")

    def test_move_to_raises_on_pyautogui_exception(self, engine: ActionEngine) -> None:
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.moveTo", side_effect=RuntimeError("move failed")),
            patch("tenacity.nap.time.sleep"),
        ):
            from execution.retry_handler import RetryExhaustedError
            with pytest.raises(RetryExhaustedError):
                engine.move_to(100, 200)
