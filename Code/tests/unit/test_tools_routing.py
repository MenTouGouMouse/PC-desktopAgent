"""属性测试：decision/tools.py - 工具路由正确性（Property 8）。

验证 DesktopToolkit 对四个工具（detect_gui_elements、click、type_text、open_application）
的路由行为：对任意合法参数，工具方法必须将调用路由至对应的底层实现（ActionEngine 或
ElementLocator），且传入的参数与工具方法接收到的参数完全一致。

# Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
# Validates: Requirements 5.5
"""
from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decision.tools import DesktopToolkit
from perception.element_locator import ElementResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Printable text that is safe for JSON serialisation
_text_st = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=100,
)

# Coordinate strategies (wide range, including negatives and large values)
_coord_st = st.integers(min_value=-9999, max_value=9999)

# click_type strategy
_click_type_st = st.sampled_from(["single", "double", "right"])

# App name strategy
_app_st = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=80,
)

# Region strategy: optional list of 4 integers
_region_st: st.SearchStrategy[list[int] | None] = st.one_of(
    st.none(),
    st.lists(st.integers(min_value=0, max_value=3840), min_size=4, max_size=4),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_toolkit(
    locator: MagicMock | None = None,
    action: MagicMock | None = None,
) -> tuple[DesktopToolkit, MagicMock, MagicMock, MagicMock]:
    """Create a DesktopToolkit with fully mocked dependencies.

    Returns:
        Tuple of (toolkit, mock_locator, mock_action, mock_capturer).
    """
    mock_locator = locator if locator is not None else MagicMock()
    mock_action = action if action is not None else MagicMock()
    mock_capturer = MagicMock()
    mock_capturer.capture_full.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_capturer.capture_region.return_value = np.zeros((50, 50, 3), dtype=np.uint8)

    toolkit = DesktopToolkit(
        locator=mock_locator,
        action_engine=mock_action,
        screen_capturer=mock_capturer,
    )
    return toolkit, mock_locator, mock_action, mock_capturer


# ---------------------------------------------------------------------------
# Property 8a: detect_gui_elements → ElementLocator.locate_by_text
# Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class TestProperty8DetectGuiElementsRouting:
    """对任意合法的 detect_gui_elements 调用，DesktopToolkit 必须将其路由至
    ElementLocator.locate_by_text，且传入的 description 参数与 LLM 提供的一致。
    """

    @settings(max_examples=100)
    @given(description=_text_st, region=_region_st)
    def test_routes_to_locator_locate_by_text(
        self, description: str, region: list[int] | None
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, mock_locator, _, _ = _make_toolkit()
        mock_locator.locate_by_text.return_value = ElementResult(
            name=description,
            bbox=(0, 0, 10, 10),
            confidence=0.9,
            strategy="ocr",
        )

        args: dict[str, Any] = {"description": description}
        if region is not None:
            args["region"] = region

        toolkit.detect_gui_elements(json.dumps(args))

        mock_locator.locate_by_text.assert_called_once()

    @settings(max_examples=100)
    @given(description=_text_st)
    def test_description_arg_matches_exactly(self, description: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, mock_locator, _, _ = _make_toolkit()
        mock_locator.locate_by_text.return_value = ElementResult(
            name=description,
            bbox=(0, 0, 10, 10),
            confidence=0.9,
            strategy="ocr",
        )

        toolkit.detect_gui_elements(json.dumps({"description": description}))

        call_args = mock_locator.locate_by_text.call_args
        # First positional arg (after self) is the screenshot; second is description
        assert call_args is not None
        # locate_by_text(screenshot, description) — description is the second positional arg
        positional_args = call_args.args
        assert len(positional_args) >= 2
        assert positional_args[1] == description


# ---------------------------------------------------------------------------
# Property 8b: click → ActionEngine.click
# Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class TestProperty8ClickRouting:
    """对任意合法的 click 调用，DesktopToolkit 必须将其路由至 ActionEngine.click，
    且传入的 x、y、click_type 参数与 LLM 提供的一致。
    """

    @settings(max_examples=100)
    @given(x=_coord_st, y=_coord_st, click_type=_click_type_st)
    def test_routes_to_action_engine_click(
        self, x: int, y: int, click_type: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.click.return_value = True

        toolkit.click(json.dumps({"x": x, "y": y, "click_type": click_type}))

        mock_action.click.assert_called_once()

    @settings(max_examples=100)
    @given(x=_coord_st, y=_coord_st, click_type=_click_type_st)
    def test_click_args_match_exactly(
        self, x: int, y: int, click_type: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.click.return_value = True

        toolkit.click(json.dumps({"x": x, "y": y, "click_type": click_type}))

        mock_action.click.assert_called_once_with(x, y, click_type)

    @settings(max_examples=100)
    @given(x=_coord_st, y=_coord_st)
    def test_click_default_click_type_is_single(self, x: int, y: int) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.click.return_value = True

        # Omit click_type — should default to "single"
        toolkit.click(json.dumps({"x": x, "y": y}))

        mock_action.click.assert_called_once_with(x, y, "single")


# ---------------------------------------------------------------------------
# Property 8c: type_text → ActionEngine.type_text
# Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class TestProperty8TypeTextRouting:
    """对任意合法的 type_text 调用，DesktopToolkit 必须将其路由至
    ActionEngine.type_text，且传入的 text 参数与 LLM 提供的一致。
    """

    @settings(max_examples=100)
    @given(text=_text_st)
    def test_routes_to_action_engine_type_text(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.type_text.return_value = True

        toolkit.type_text(json.dumps({"text": text}))

        mock_action.type_text.assert_called_once()

    @settings(max_examples=100)
    @given(text=_text_st)
    def test_type_text_arg_matches_exactly(self, text: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.type_text.return_value = True

        toolkit.type_text(json.dumps({"text": text}))

        mock_action.type_text.assert_called_once_with(text)


# ---------------------------------------------------------------------------
# Property 8d: open_application → ActionEngine.open_application
# Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class TestProperty8OpenApplicationRouting:
    """对任意合法的 open_application 调用，DesktopToolkit 必须将其路由至
    ActionEngine.open_application，且传入的 app 参数与 LLM 提供的一致。
    """

    @settings(max_examples=100)
    @given(app=_app_st)
    def test_routes_to_action_engine_open_application(self, app: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.open_application.return_value = True

        toolkit.open_application(json.dumps({"app": app}))

        mock_action.open_application.assert_called_once()

    @settings(max_examples=100)
    @given(app=_app_st)
    def test_open_application_arg_matches_exactly(self, app: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 8: 工具路由正确性
        # Validates: Requirements 5.5
        toolkit, _, mock_action, _ = _make_toolkit()
        mock_action.open_application.return_value = True

        toolkit.open_application(json.dumps({"app": app}))

        mock_action.open_application.assert_called_once_with(app)
