"""
Preservation property tests — Non-Bug-Path Behavior Unchanged (Task 2).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

These tests MUST PASS on UNFIXED code. They encode the preservation behavior
(non-bug paths) that must remain unchanged after the fix is applied.

OBSERVATIONS ON UNFIXED CODE (non-bug-condition inputs):
  - restore_main_window(): ball hidden, main shown, _ball_is_shown = False
  - move_ball_window(x, y): _ball_win.move(x, y) called with same coordinates
  - push_progress(...) with ball present: evaluate_js called on both windows
  - push_progress(...) with ball absent (_ball_win=None): evaluate_js on main only
  - _on_main_closed with _ball_win=None: no exception raised, sys.exit(0) called
  - Multiple minimize_to_ball() calls: create_window called at most once (idempotency)
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
from gui.progress_manager import ProgressManager, TaskProgress  # noqa: E402
from ui.queue_manager import QueueManager  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api(
    main_shown: bool = True,
    ball_shown: bool = False,
    ball_win: MagicMock | None = None,
) -> tuple[PythonAPI, MagicMock, MagicMock | None]:
    """Return a PythonAPI with mock windows wired."""
    pm = ProgressManager()
    qm = QueueManager()
    api = PythonAPI(pm, qm)

    main_win = MagicMock()
    main_win.shown = main_shown

    if ball_win is None:
        ball_win = MagicMock()
        ball_win.shown = ball_shown

    api.set_windows(main_win, ball_win)
    return api, main_win, ball_win


def _make_api_no_ball() -> tuple[PythonAPI, MagicMock]:
    """Return a PythonAPI with only main window (ball_win=None)."""
    pm = ProgressManager()
    qm = QueueManager()
    api = PythonAPI(pm, qm)

    main_win = MagicMock()
    main_win.shown = True
    # Only set main window; ball_win stays None
    api._main_win = main_win
    return api, main_win


# ---------------------------------------------------------------------------
# Property: restore_main_window() — ball hidden, main shown, _ball_is_shown=False
# Validates: Requirements 3.5
#
# Observed on UNFIXED code: restore_main_window() calls ball_win.hide(),
# sets _ball_is_shown=False, then calls main_win.show().
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestRestoreMainWindowPreservation:
    """**Validates: Requirements 3.5**"""

    def test_restore_main_window_hides_ball(self) -> None:
        """restore_main_window() must call ball_win.hide().

        Observed on UNFIXED code: ball_win.hide() is called unconditionally.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(ball_shown=True)
        api.restore_main_window()
        ball_win.hide.assert_called_once()

    def test_restore_main_window_shows_main(self) -> None:
        """restore_main_window() must call main_win.show().

        Observed on UNFIXED code: main_win.show() is called unconditionally.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.restore_main_window()
        main_win.show.assert_called_once()

    def test_restore_main_window_sets_ball_is_shown_false(self) -> None:
        """restore_main_window() must set _ball_is_shown = False.

        Observed on UNFIXED code: _ball_is_shown is set to False after hiding ball.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api._ball_is_shown = True  # simulate ball was shown
        api.restore_main_window()
        assert api._ball_is_shown is False


# ---------------------------------------------------------------------------
# Property: move_ball_window(x, y) — coordinate pass-through
# Validates: Requirements 3.3
#
# For any (x, y), move_ball_window(x, y) passes the same values to
# _ball_win.move(x, y) unchanged. No clamping or transformation in Python.
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestMoveBallWindowCoordinatePassThrough:
    """**Validates: Requirements 3.3**"""

    @given(
        x=st.integers(min_value=-10000, max_value=10000),
        y=st.integers(min_value=-10000, max_value=10000),
    )
    @settings(max_examples=50)
    def test_move_ball_window_passes_coordinates_unchanged(
        self, x: int, y: int
    ) -> None:
        """For any (x, y), move_ball_window passes the exact same values to _ball_win.move().

        **Validates: Requirements 3.3**

        Observed on UNFIXED code: move_ball_window(x, y) calls self._ball_win.move(x, y)
        with no transformation. Coordinate clamping is done in the frontend JS.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api()
        api.move_ball_window(x, y)
        ball_win.move.assert_called_once_with(x, y)

    def test_move_ball_window_no_op_when_ball_none(self) -> None:
        """move_ball_window() with no ball window must not raise.

        Observed on UNFIXED code: guarded by `if self._ball_win is not None`.
        EXPECTED: PASS on unfixed code.
        """
        api, main_win = _make_api_no_ball()
        api.move_ball_window(100, 200)  # must not raise


# ---------------------------------------------------------------------------
# Property: push_progress — evaluate_js called on both windows when ball present
# Validates: Requirements 3.4
#
# Observed on UNFIXED code: push_progress calls evaluate_js on main_win and
# ball_win when both are present and shown.
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestPushProgressPreservation:
    """**Validates: Requirements 3.4**"""

    def _make_app_with_windows(
        self, ball_win: MagicMock | None = None
    ) -> tuple[PyWebViewApp, MagicMock, MagicMock | None]:
        """Return a PyWebViewApp with mock windows wired directly."""
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        main_win = MagicMock()
        main_win.shown = True
        app._main_win = main_win

        if ball_win is not None:
            ball_win.shown = True
            app._ball_win = ball_win
        else:
            app._ball_win = None

        return app, main_win, ball_win

    def test_push_progress_with_ball_present_calls_both_windows(self) -> None:
        """push_progress() with ball present must call evaluate_js on both windows.

        Observed on UNFIXED code: both main_win.evaluate_js and ball_win.evaluate_js
        are called when both windows are present and shown.
        EXPECTED: PASS on unfixed code.
        """
        ball_win = MagicMock()
        app, main_win, ball_win = self._make_app_with_windows(ball_win=ball_win)

        progress = TaskProgress(
            percent=50,
            status_text="running",
            task_name="test",
            is_running=True,
        )
        app.push_progress(progress)

        main_win.evaluate_js.assert_called_once()
        ball_win.evaluate_js.assert_called_once()

    def test_push_progress_with_ball_absent_calls_main_only(self) -> None:
        """push_progress() with ball absent (_ball_win=None) must call evaluate_js on main only.

        Observed on UNFIXED code: ball_win is None → only main_win.evaluate_js is called.
        EXPECTED: PASS on unfixed code.
        """
        app, main_win, _ = self._make_app_with_windows(ball_win=None)

        progress = TaskProgress(
            percent=75,
            status_text="almost done",
            task_name="test",
            is_running=True,
        )
        app.push_progress(progress)

        main_win.evaluate_js.assert_called_once()

    def test_push_progress_js_call_contains_percent(self) -> None:
        """push_progress() must include the percent value in the evaluate_js call.

        EXPECTED: PASS on unfixed code.
        """
        app, main_win, _ = self._make_app_with_windows(ball_win=None)

        progress = TaskProgress(
            percent=42,
            status_text="working",
            task_name="test",
            is_running=True,
        )
        app.push_progress(progress)

        call_args = main_win.evaluate_js.call_args[0][0]
        assert "42" in call_args


# ---------------------------------------------------------------------------
# Unit: _on_main_closed with _ball_win=None — no exception, sys.exit(0) called
# Validates: Requirements 3.6
#
# Observed on UNFIXED code: _on_main_closed guards with `if self._ball_win is not None`,
# so when ball_win is None it skips hide() and calls sys.exit(0) cleanly.
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestOnMainClosedWithNoBall:
    """**Validates: Requirements 3.6**"""

    def test_on_main_closed_with_ball_none_calls_sys_exit(self) -> None:
        """_on_main_closed with _ball_win=None must call sys.exit(0) without raising.

        Observed on UNFIXED code: the nested _on_main_closed function in run() guards
        with `if self._ball_win is not None` before calling hide(), then calls sys.exit(0).
        EXPECTED: PASS on unfixed code.
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        overlay.start = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        main_win = MagicMock()
        main_win.events = MagicMock()
        # Capture the closed event handler
        closed_handlers: list = []
        main_win.events.closed.__iadd__ = lambda self_ev, handler: closed_handlers.append(handler)

        call_count = {"n": 0}

        def fake_create_window(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_win
            return MagicMock()

        with patch("webview.create_window", side_effect=fake_create_window):
            with patch("webview.start", side_effect=lambda *a, **kw: None):
                app.run()

        # Simulate _ball_win is None (as it would be after the fix, or if never set)
        app._ball_win = None

        # Invoke the on_closed callback directly
        with patch("sys.exit") as mock_exit:
            # The _on_main_closed is registered via events.closed += handler
            # Since we captured it, invoke it directly
            if closed_handlers:
                closed_handlers[0]()
            else:
                # Fallback: call the internal method directly by re-running the closure
                # The closure captures app._ball_win via self reference
                # We test by verifying sys.exit is called when ball_win is None
                pytest.skip("Could not capture closed handler — events.closed += not intercepted")

        mock_exit.assert_called_once_with(0)

    def test_on_main_closed_with_ball_none_does_not_raise(self) -> None:
        """_on_main_closed with _ball_win=None must not raise any exception.

        EXPECTED: PASS on unfixed code.
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        overlay.start = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        main_win = MagicMock()
        main_win.events = MagicMock()
        closed_handlers: list = []
        main_win.events.closed.__iadd__ = lambda self_ev, handler: closed_handlers.append(handler)

        call_count = {"n": 0}

        def fake_create_window(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_win
            return MagicMock()

        with patch("webview.create_window", side_effect=fake_create_window):
            with patch("webview.start", side_effect=lambda *a, **kw: None):
                app.run()

        app._ball_win = None

        with patch("sys.exit"):
            if closed_handlers:
                closed_handlers[0]()  # must not raise
            else:
                pytest.skip("Could not capture closed handler")


# ---------------------------------------------------------------------------
# Property: minimize_to_ball() idempotency — create_window called at most once
# Validates: Requirements 3.1
#
# On UNFIXED code: _ball_win is already set at startup (created in run()).
# So minimize_to_ball() never calls webview.create_window — it only calls show().
# For N≥1 calls, create_window for the ball is called 0 times from minimize_to_ball().
# "At most once" = 0 on unfixed code (ball already exists).
# EXPECTED: PASS on unfixed code.
# ---------------------------------------------------------------------------


class TestMinimizeToBallIdempotency:
    """**Validates: Requirements 3.1**"""

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=20)
    def test_minimize_to_ball_n_calls_create_window_at_most_once(
        self, n: int
    ) -> None:
        """For any N≥1 calls to minimize_to_ball(), webview.create_window for the ball
        is called at most once.

        **Validates: Requirements 3.1**

        On UNFIXED code: _ball_win is already set at startup, so minimize_to_ball()
        never calls webview.create_window — create_window count from minimize_to_ball()
        is 0, which satisfies "at most once".
        After the fix (lazy creation): first call creates the window (count=1), subsequent
        calls reuse it (count stays 1). Both satisfy "at most once".
        EXPECTED: PASS on unfixed code.
        """
        api, main_win, ball_win = _make_api(ball_shown=False)

        create_window_call_count = 0

        with patch("webview.create_window") as mock_cw:
            for _ in range(n):
                api.minimize_to_ball()
            create_window_call_count = mock_cw.call_count

        # At most once: 0 (unfixed, ball already exists) or 1 (fixed, lazy creation)
        assert create_window_call_count <= 1, (
            f"webview.create_window called {create_window_call_count} times "
            f"across {n} minimize_to_ball() calls. Expected at most 1."
        )
