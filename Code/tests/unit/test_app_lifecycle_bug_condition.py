"""
Bug condition exploration tests — floating ball lifecycle (Bug 2).

**Validates: Requirements 2.4, 2.5, 2.6, 2.7, 2.8, 2.9**

These tests are EXPECTED TO FAIL on unfixed code. Failure confirms the bugs exist.

COUNTEREXAMPLES DOCUMENTED (from running on unfixed code):
--------------------------------------------------------------------------
Test (a) test_ball_window_visible_on_startup:
  - RESULT: PASSES on current code — _on_webview_started already calls ball_win.hide().
    This sub-bug appears already addressed in the base implementation (task 5.5).
    The test is retained to guard against regression.

Test (b) test_minimize_to_ball_duplicate_window:
  - COUNTEREXAMPLE: minimize_to_ball() called when ball_win.shown=True still calls
    ball_win.show() again (no guard). On a real platform this could trigger duplicate
    window creation if the window manager re-creates the window on show().
  - FAILURE OUTPUT:
      AssertionError: Expected 'show' to not have been called. Called 1 times.
      Calls: [call()].
    Expected: show() NOT called when ball is already visible.

Test (c) test_main_window_close_orphans_ball:
  - COUNTEREXAMPLE: No on_closed callback is registered on the main window in run().
    When the main window closes, ball_win.hide() is never called and sys.exit() is
    never invoked — the floating ball remains open and the process hangs.
  - FAILURE OUTPUT:
      AssertionError: BUG CONFIRMED: no on_closed callback registered on main window.
      Closing the main window will orphan the ball and leave the process running.
      assert 0 > 0
       +  where 0 = len([])
--------------------------------------------------------------------------
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest

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


def _make_window(shown: bool = False) -> MagicMock:
    win = MagicMock()
    win.shown = shown
    return win


def _make_app() -> tuple[PyWebViewApp, MagicMock, MagicMock]:
    """Return a PyWebViewApp with mock windows already wired."""
    pm = ProgressManager()
    qm = QueueManager()
    overlay = MagicMock()
    app = PyWebViewApp(pm, qm, overlay)
    main_win = _make_window(shown=True)
    ball_win = _make_window(shown=False)
    app._main_win = main_win
    app._ball_win = ball_win
    app.api.set_windows(main_win, ball_win)
    return app, main_win, ball_win


# ---------------------------------------------------------------------------
# Test (a): Ball window hidden at startup
# Validates: Requirements 2.4, 2.7
#
# On UNFIXED code: _on_webview_started does NOT call ball_win.hide(), so the
# ball window remains visible after webview starts.
# EXPECTED: FAIL on unfixed code (ball_win.hide() never called).
# ---------------------------------------------------------------------------


class TestBallWindowVisibleOnStartup:
    """**Validates: Requirements 2.4, 2.7**"""

    def test_ball_window_visible_on_startup(self) -> None:
        """Assert ball window is NOT created at startup (lazy creation fix).

        After the fix: run() does NOT create the ball window at all — _ball_win
        remains None after run(). The ball is only created on first minimize_to_ball().
        This test verifies the fix: create_window is called exactly once (main only).
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        main_win = _make_window(shown=True)

        create_call_count = {"n": 0}

        def fake_create_window(*args, **kwargs):
            create_call_count["n"] += 1
            return main_win

        with patch("webview.create_window", side_effect=fake_create_window):
            with patch("webview.start") as mock_start:
                def fake_start(callback=None, *args, **kwargs):
                    if callback is not None:
                        callback()

                mock_start.side_effect = fake_start
                overlay.start = MagicMock()
                app.run()

        # After fix: create_window called exactly once (main window only)
        assert create_call_count["n"] == 1, (
            f"Expected create_window called once (main only), got {create_call_count['n']}. "
            "Ball window should not be created at startup."
        )
        # After fix: _ball_win is None (not created at startup)
        assert app._ball_win is None, (
            "Expected _ball_win to be None after run() — ball window should only be "
            "created lazily on first minimize_to_ball() call."
        )


# ---------------------------------------------------------------------------
# Test (b): minimize_to_ball() called twice — no duplicate window
# Validates: Requirements 2.8
#
# On UNFIXED code: minimize_to_ball() has no guard — it calls ball_win.show()
# unconditionally even when the ball is already shown. On platforms where
# show() re-creates the window, this produces a duplicate.
# EXPECTED: FAIL on unfixed code (show() called even when ball already shown).
# ---------------------------------------------------------------------------


class TestMinimizeToBallDuplicateWindow:
    """**Validates: Requirements 2.8**"""

    def test_minimize_to_ball_duplicate_window(self) -> None:
        """Assert minimize_to_ball() creates ball window only once (lazy creation).

        After the fix: first call creates the ball window via webview.create_window.
        Second call reuses the existing window via show(). create_window is called
        exactly once across multiple minimize_to_ball() calls.
        """
        pm = ProgressManager()
        qm = QueueManager()
        api = PythonAPI(pm, qm)

        main_win = _make_window(shown=True)
        api._main_win = main_win
        # _ball_win starts as None (lazy creation)

        mock_ball_win = _make_window(shown=False)
        create_call_count = {"n": 0}

        def fake_create_window(*args, **kwargs):
            create_call_count["n"] += 1
            return mock_ball_win

        with patch("webview.create_window", side_effect=fake_create_window):
            # First call: should create the ball window
            api.minimize_to_ball()
            assert create_call_count["n"] == 1, "First minimize_to_ball() should create ball window"

            # Second call: should reuse existing window, NOT create a new one
            api.minimize_to_ball()
            assert create_call_count["n"] == 1, (
                f"Second minimize_to_ball() should NOT call create_window again. "
                f"create_window was called {create_call_count['n']} times."
            )


# ---------------------------------------------------------------------------
# Test (c): Closing main window orphans ball
# Validates: Requirements 2.9
#
# On UNFIXED code: no on_closed callback is registered on the main window.
# When the main window closes, ball_win.hide() and sys.exit() are never called.
# EXPECTED: FAIL on unfixed code (no on_closed callback registered).
# ---------------------------------------------------------------------------


class TestMainWindowCloseOrphansBall:
    """**Validates: Requirements 2.9**"""

    def test_main_window_close_orphans_ball(self) -> None:
        """Assert ball_win.hide() and sys.exit() are called when main window closes.

        After the fix: run() registers an on_closed callback via events.closed +=.
        When the main window closes, ball_win.hide() and sys.exit(0) are called.
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        main_win = _make_window(shown=True)
        ball_win = _make_window(shown=False)

        # Capture the closed event handler registered via events.closed +=
        captured_closed_handlers: list = []
        main_win.events = MagicMock()
        main_win.events.closed.__iadd__ = lambda self_ev, handler: captured_closed_handlers.append(handler) or self_ev

        def fake_create_window(*args, **kwargs):
            return main_win

        with patch("webview.create_window", side_effect=fake_create_window):
            with patch("webview.start", side_effect=lambda *a, **kw: None):
                overlay.start = MagicMock()
                app.run()

        # ASSERTION 1: a closed event handler must have been registered
        assert len(captured_closed_handlers) > 0, (
            "BUG CONFIRMED: no closed event handler registered on main window. "
            "Closing the main window will orphan the ball and leave the process running."
        )

        # ASSERTION 2: invoking the closed handler must call sys.exit(0)
        # Set up ball_win on the app to test hide() is called
        app._ball_win = ball_win
        on_closed_cb = captured_closed_handlers[0]

        with patch("sys.exit") as mock_exit:
            on_closed_cb()

        ball_win.hide.assert_called_once()
        mock_exit.assert_called_once_with(0)
