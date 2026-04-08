"""
Preservation property tests — floating ball lifecycle (Bug 2, BEFORE fix).

**Validates: Requirements 3.2, 3.3, 3.4, 3.5**

These tests MUST PASS on UNFIXED code. They document the correct window
show/hide transition behavior that must be preserved after the lifecycle fix.

OBSERVATIONS ON UNFIXED CODE:
  - minimize_to_ball(): calls main_win.hide() then ball_win.show() ✓
  - restore_main_window(): calls ball_win.hide() then main_win.show() ✓
  Both transitions work correctly on unfixed code and must remain intact after fix.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Stub out 'webview' so tests run without pywebview installed
# ---------------------------------------------------------------------------
_webview_stub = types.ModuleType("webview")
_webview_stub.Window = MagicMock  # type: ignore[attr-defined]
_webview_stub.create_window = MagicMock()  # type: ignore[attr-defined]
_webview_stub.start = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("webview", _webview_stub)

from gui.app import PythonAPI, PyWebViewApp  # noqa: E402
from gui.progress_manager import ProgressManager  # noqa: E402
from ui.queue_manager import QueueManager  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api(main_shown: bool = True, ball_shown: bool = False) -> tuple[PythonAPI, MagicMock, MagicMock]:
    """Return a PythonAPI with mock windows wired."""
    pm = ProgressManager()
    qm = QueueManager()
    api = PythonAPI(pm, qm)

    main_win = MagicMock()
    main_win.shown = main_shown
    ball_win = MagicMock()
    ball_win.shown = ball_shown

    api.set_windows(main_win, ball_win)
    return api, main_win, ball_win


# ---------------------------------------------------------------------------
# Property: minimize_to_ball() always hides main and shows ball
# Validates: Requirements 3.2, 3.4
#
# For any initial window state, minimize_to_ball() must:
#   1. Call main_win.hide()
#   2. Call ball_win.show()
# This behavior is observed on UNFIXED code and must be preserved after fix.
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestMinimizeToBallPreservation:
    """**Validates: Requirements 3.2, 3.4**"""

    @given(
        main_shown=st.booleans(),
        ball_shown=st.booleans(),
    )
    @settings(max_examples=20)
    def test_minimize_to_ball_hides_main_and_shows_ball(
        self, main_shown: bool, ball_shown: bool
    ) -> None:
        """For any window state, minimize_to_ball() hides main and shows ball.

        Observed on UNFIXED code: minimize_to_ball() unconditionally calls
        main_win.hide() then ball_win.show(). This must be preserved after fix.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=main_shown, ball_shown=ball_shown)

        api.minimize_to_ball()

        # main window must be hidden
        main_win.hide.assert_called_once()
        # ball window must be shown
        ball_win.show.assert_called_once()

    def test_minimize_to_ball_hide_before_show_order(self) -> None:
        """minimize_to_ball() must call hide on main BEFORE show on ball.

        Validates call ordering is preserved: hide main → show ball.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=True, ball_shown=False)

        call_order: list[str] = []
        main_win.hide.side_effect = lambda: call_order.append("main_hide")
        ball_win.show.side_effect = lambda: call_order.append("ball_show")

        api.minimize_to_ball()

        assert call_order == ["main_hide", "ball_show"], (
            f"Expected ['main_hide', 'ball_show'], got {call_order}"
        )

    def test_minimize_to_ball_does_not_show_main(self) -> None:
        """minimize_to_ball() must NOT call main_win.show().

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.minimize_to_ball()
        main_win.show.assert_not_called()

    def test_minimize_to_ball_does_not_hide_ball(self) -> None:
        """minimize_to_ball() must NOT call ball_win.hide().

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.minimize_to_ball()
        ball_win.hide.assert_not_called()


# ---------------------------------------------------------------------------
# Property: restore_main_window() always hides ball and shows main
# Validates: Requirements 3.3, 3.5
#
# For any initial window state, restore_main_window() must:
#   1. Call ball_win.hide()
#   2. Call main_win.show()
# This behavior is observed on UNFIXED code and must be preserved after fix.
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestRestoreMainWindowPreservation:
    """**Validates: Requirements 3.3, 3.5**"""

    @given(
        main_shown=st.booleans(),
        ball_shown=st.booleans(),
    )
    @settings(max_examples=20)
    def test_restore_main_window_hides_ball_and_shows_main(
        self, main_shown: bool, ball_shown: bool
    ) -> None:
        """For any window state, restore_main_window() hides ball and shows main.

        Observed on UNFIXED code: restore_main_window() unconditionally calls
        ball_win.hide() then main_win.show(). This must be preserved after fix.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=main_shown, ball_shown=ball_shown)

        api.restore_main_window()

        # ball window must be hidden
        ball_win.hide.assert_called_once()
        # main window must be shown
        main_win.show.assert_called_once()

    def test_restore_main_window_hide_before_show_order(self) -> None:
        """restore_main_window() must call hide on ball BEFORE show on main.

        Validates call ordering is preserved: hide ball → show main.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=False, ball_shown=True)

        call_order: list[str] = []
        ball_win.hide.side_effect = lambda: call_order.append("ball_hide")
        main_win.show.side_effect = lambda: call_order.append("main_show")

        api.restore_main_window()

        assert call_order == ["ball_hide", "main_show"], (
            f"Expected ['ball_hide', 'main_show'], got {call_order}"
        )

    def test_restore_main_window_does_not_hide_main(self) -> None:
        """restore_main_window() must NOT call main_win.hide().

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.restore_main_window()
        main_win.hide.assert_not_called()

    def test_restore_main_window_does_not_show_ball(self) -> None:
        """restore_main_window() must NOT call ball_win.show().

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.restore_main_window()
        ball_win.show.assert_not_called()


# ---------------------------------------------------------------------------
# Property: round-trip — minimize then restore returns to original state
# Validates: Requirements 3.2, 3.3
#
# minimize_to_ball() followed by restore_main_window() must result in:
#   - main_win.hide() called once, main_win.show() called once
#   - ball_win.show() called once, ball_win.hide() called once
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestMinimizeRestoreRoundTrip:
    """**Validates: Requirements 3.2, 3.3**"""

    def test_minimize_then_restore_round_trip(self) -> None:
        """minimize_to_ball() then restore_main_window() calls each method exactly once.

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=True, ball_shown=False)

        api.minimize_to_ball()
        api.restore_main_window()

        main_win.hide.assert_called_once()
        main_win.show.assert_called_once()
        ball_win.show.assert_called_once()
        ball_win.hide.assert_called_once()

    @given(cycles=st.integers(min_value=1, max_value=5))
    @settings(max_examples=10)
    def test_multiple_minimize_restore_cycles(self, cycles: int) -> None:
        """N minimize+restore cycles result in exactly N calls to each method.

        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(main_shown=True, ball_shown=False)

        for _ in range(cycles):
            api.minimize_to_ball()
            api.restore_main_window()

        assert main_win.hide.call_count == cycles
        assert main_win.show.call_count == cycles
        assert ball_win.show.call_count == cycles
        assert ball_win.hide.call_count == cycles


# ---------------------------------------------------------------------------
# Property: graceful no-op when windows are None
# Validates: Requirements 3.2, 3.3 (robustness)
#
# If windows are not yet set, both methods must not raise exceptions.
# EXPECTED: PASS on unfixed code (both methods guard with `if ... is not None`).
# ---------------------------------------------------------------------------


class TestWindowNoneGracefulHandling:
    """**Validates: Requirements 3.2, 3.3 (robustness)**"""

    def test_minimize_to_ball_no_windows_does_not_raise(self) -> None:
        """minimize_to_ball() with no windows set must not raise.

        EXPECTED: PASS on unfixed code.
        """
        pm = ProgressManager()
        qm = QueueManager()
        api = PythonAPI(pm, qm)
        # windows not set — _main_win and _ball_win are None
        api.minimize_to_ball()  # must not raise

    def test_restore_main_window_no_windows_does_not_raise(self) -> None:
        """restore_main_window() with no windows set must not raise.

        EXPECTED: PASS on unfixed code.
        """
        pm = ProgressManager()
        qm = QueueManager()
        api = PythonAPI(pm, qm)
        # windows not set — _main_win and _ball_win are None
        api.restore_main_window()  # must not raise
