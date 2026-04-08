"""单元测试：decision/tools.py - DesktopToolkit 工具集。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from decision.tools import TOOLS, DesktopToolkit
from perception.element_locator import ElementNotFoundError, ElementResult


@pytest.fixture()
def mock_locator() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_action() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_capturer() -> MagicMock:
    capturer = MagicMock()
    capturer.capture_full.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    capturer.capture_region.return_value = np.zeros((50, 50, 3), dtype=np.uint8)
    return capturer


@pytest.fixture()
def toolkit(mock_locator, mock_action, mock_capturer) -> DesktopToolkit:
    return DesktopToolkit(
        locator=mock_locator,
        action_engine=mock_action,
        screen_capturer=mock_capturer,
    )


# ---------------------------------------------------------------------------
# TOOLS 常量
# ---------------------------------------------------------------------------


def test_tools_constant_has_four_entries():
    assert len(TOOLS) == 4


def test_tools_constant_names():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == {"detect_gui_elements", "click", "type_text", "open_application"}


def test_tools_constant_detect_required_params():
    schema = next(t for t in TOOLS if t["function"]["name"] == "detect_gui_elements")
    assert "description" in schema["function"]["parameters"]["required"]


def test_tools_constant_click_required_params():
    schema = next(t for t in TOOLS if t["function"]["name"] == "click")
    assert set(schema["function"]["parameters"]["required"]) == {"x", "y"}


def test_tools_constant_type_text_required_params():
    schema = next(t for t in TOOLS if t["function"]["name"] == "type_text")
    assert "text" in schema["function"]["parameters"]["required"]


def test_tools_constant_open_application_required_params():
    schema = next(t for t in TOOLS if t["function"]["name"] == "open_application")
    assert "app" in schema["function"]["parameters"]["required"]


# ---------------------------------------------------------------------------
# DesktopToolkit.get_tools()
# ---------------------------------------------------------------------------


def test_get_tools_returns_four_tools(toolkit):
    tools = toolkit.get_tools()
    assert len(tools) == 4


def test_get_tools_names(toolkit):
    names = {t.name for t in toolkit.get_tools()}
    assert names == {"detect_gui_elements", "click", "type_text", "open_application"}


# ---------------------------------------------------------------------------
# detect_gui_elements
# ---------------------------------------------------------------------------


def test_detect_gui_elements_success(toolkit, mock_locator, mock_capturer):
    mock_locator.locate_by_text.return_value = ElementResult(
        name="安装按钮",
        bbox=(10, 20, 100, 40),
        confidence=0.95,
        strategy="aliyun_vision",
    )
    result_str = toolkit.detect_gui_elements(json.dumps({"description": "安装按钮"}))
    result = json.loads(result_str)

    assert result["name"] == "安装按钮"
    assert result["bbox"] == [10, 20, 100, 40]
    assert result["confidence"] == pytest.approx(0.95)
    assert result["strategy"] == "aliyun_vision"
    assert "center" in result
    mock_capturer.capture_full.assert_called_once()


def test_detect_gui_elements_with_region(toolkit, mock_locator, mock_capturer):
    mock_locator.locate_by_text.return_value = ElementResult(
        name="确定", bbox=(5, 5, 50, 20), confidence=0.8, strategy="ocr"
    )
    result_str = toolkit.detect_gui_elements(
        json.dumps({"description": "确定", "region": [0, 0, 200, 100]})
    )
    result = json.loads(result_str)
    assert result["name"] == "确定"
    mock_capturer.capture_region.assert_called_once_with(0, 0, 200, 100)


def test_detect_gui_elements_not_found(toolkit, mock_locator):
    mock_locator.locate_by_text.side_effect = ElementNotFoundError("未找到", ["aliyun_vision"])
    result_str = toolkit.detect_gui_elements(json.dumps({"description": "不存在的按钮"}))
    result = json.loads(result_str)
    assert "error" in result


def test_detect_gui_elements_missing_description(toolkit):
    result_str = toolkit.detect_gui_elements(json.dumps({}))
    result = json.loads(result_str)
    assert "error" in result


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------


def test_click_success(toolkit, mock_action):
    mock_action.click.return_value = True
    result = toolkit.click(json.dumps({"x": 100, "y": 200}))
    assert "100" in result and "200" in result
    mock_action.click.assert_called_once_with(100, 200, "single")


def test_click_with_double_type(toolkit, mock_action):
    mock_action.click.return_value = True
    toolkit.click(json.dumps({"x": 50, "y": 60, "click_type": "double"}))
    mock_action.click.assert_called_once_with(50, 60, "double")


def test_click_out_of_bounds(toolkit, mock_action):
    mock_action.click.return_value = False
    result = toolkit.click(json.dumps({"x": 9999, "y": 9999}))
    assert "失败" in result or "边界" in result


def test_click_missing_x(toolkit):
    result = toolkit.click(json.dumps({"y": 100}))
    assert "缺少" in result or "error" in result.lower() or "x" in result


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------


def test_type_text_success(toolkit, mock_action):
    mock_action.type_text.return_value = True
    result = toolkit.type_text(json.dumps({"text": "你好世界"}))
    assert "输入" in result
    mock_action.type_text.assert_called_once_with("你好世界")


def test_type_text_missing_text(toolkit):
    result = toolkit.type_text(json.dumps({}))
    assert "缺少" in result or "error" in result.lower() or "text" in result


def test_type_text_failure(toolkit, mock_action):
    mock_action.type_text.return_value = False
    result = toolkit.type_text(json.dumps({"text": "hello"}))
    assert "失败" in result


# ---------------------------------------------------------------------------
# open_application
# ---------------------------------------------------------------------------


def test_open_application_success(toolkit, mock_action):
    mock_action.open_application.return_value = True
    result = toolkit.open_application(json.dumps({"app": "notepad.exe"}))
    assert "notepad.exe" in result
    mock_action.open_application.assert_called_once_with("notepad.exe")


def test_open_application_missing_app(toolkit):
    result = toolkit.open_application(json.dumps({}))
    assert "缺少" in result or "error" in result.lower() or "app" in result


def test_open_application_failure(toolkit, mock_action):
    mock_action.open_application.side_effect = RuntimeError("启动失败")
    result = toolkit.open_application(json.dumps({"app": "nonexistent.exe"}))
    assert "失败" in result or "error" in result.lower()


# ---------------------------------------------------------------------------
# DesktopToolkit 默认构造（无参数）
# ---------------------------------------------------------------------------


def test_desktop_toolkit_default_construction():
    """验证无参数时能自动创建依赖实例（不调用真实 API）。"""
    with (
        patch("decision.tools.ElementLocator") as mock_el,
        patch("decision.tools.ActionEngine") as mock_ae,
        patch("decision.tools.ScreenCapturer") as mock_sc,
    ):
        toolkit = DesktopToolkit()
        mock_el.assert_called_once()
        mock_ae.assert_called_once()
        mock_sc.assert_called_once()
