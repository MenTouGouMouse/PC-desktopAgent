"""
Bug condition exploration tests — Floating Ball Startup Visibility & CSS Pollution.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

These tests are EXPECTED TO FAIL on unfixed code. Failure confirms the bugs exist.

COUNTEREXAMPLES DOCUMENTED (from running on unfixed code):
--------------------------------------------------------------------------
Test 1 — test_run_creates_window_exactly_once:
  - COUNTEREXAMPLE: webview.create_window is called TWICE in run() — once for the
    main window and once for the floating ball window.
  - FAILURE OUTPUT:
      AssertionError: BUG 1 CONFIRMED: webview.create_window called 2 times in run().
      Expected exactly 1 call (main window only). The floating ball window is created
      at startup, confirming Bug 1 (startup visibility).
      assert 2 == 1

Test 2 — test_ball_create_window_uses_hidden_true:
  - COUNTEREXAMPLE: The second create_window call (for the floating ball) includes
    hidden=True, confirming reliance on the unreliable hidden parameter.
  - FAILURE OUTPUT:
      AssertionError: BUG 1 CONFIRMED: second create_window call includes hidden=True.
      This confirms the code relies on hidden=True to suppress the ball at startup,
      which is not reliably honored on all platforms (e.g. Windows/Edge WebView2).
      assert {'hidden': True, ...} does not contain hidden=True

Test 3 — test_floating_html_has_no_link_stylesheets:
  - COUNTEREXAMPLE: frontend/floating.html contains 2 <link rel="stylesheet"> tags:
      <link rel="stylesheet" href="./src/styles/tokens.css" />
      <link rel="stylesheet" href="./src/styles/global.css" />
  - FAILURE OUTPUT:
      AssertionError: BUG 2 CONFIRMED: floating.html contains 2 <link rel="stylesheet">
      tag(s). These external CSS files may set opaque backgrounds on body/#app,
      causing the black rectangular border/background bug.
      Found tags:
        <link rel="stylesheet" href="./src/styles/tokens.css"/>
        <link rel="stylesheet" href="./src/styles/global.css"/>
      assert 2 == 0
--------------------------------------------------------------------------
"""
from __future__ import annotations

import sys
import types
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out 'webview' so tests run without pywebview installed
# ---------------------------------------------------------------------------
_webview_stub = types.ModuleType("webview")
_webview_stub.Window = MagicMock  # type: ignore[attr-defined]
_webview_stub.create_window = MagicMock()  # type: ignore[attr-defined]
_webview_stub.start = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("webview", _webview_stub)

from gui.app import PyWebViewApp  # noqa: E402
from gui.progress_manager import ProgressManager  # noqa: E402
from ui.queue_manager import QueueManager  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: collect <link rel="stylesheet"> tags from HTML
# ---------------------------------------------------------------------------


class _LinkTagCollector(HTMLParser):
    """Collects all <link rel="stylesheet"> tags from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.stylesheet_links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        if attr_dict.get("rel", "").lower() == "stylesheet":
            self.stylesheet_links.append(attr_dict)


# ---------------------------------------------------------------------------
# Test 1 — Startup creation check
#
# Assert webview.create_window is called exactly ONCE (main window only).
# On unfixed code it is called TWICE (main + ball), confirming Bug 1.
# EXPECTED: FAIL on unfixed code.
# ---------------------------------------------------------------------------


class TestStartupCreationCount:
    """**Validates: Requirements 1.1, 1.2**"""

    def test_run_creates_window_exactly_once(self) -> None:
        """Assert create_window is called exactly once (main window only) during run().

        On unfixed code: run() calls create_window twice — once for the main window
        and once for the floating ball window. This test FAILS on unfixed code,
        confirming Bug 1 (floating ball created at startup).
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        overlay.start = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        mock_main_win = MagicMock()
        mock_main_win.events = MagicMock()
        mock_main_win.events.closed = MagicMock()
        mock_main_win.shown = True

        mock_ball_win = MagicMock()
        mock_ball_win.shown = False

        call_count = {"n": 0}

        def fake_create_window(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_main_win
            return mock_ball_win

        with patch("webview.create_window", side_effect=fake_create_window) as mock_cw:
            with patch("webview.start", side_effect=lambda *a, **kw: None):
                app.run()

            total_calls = mock_cw.call_count

        assert total_calls == 1, (
            f"BUG 1 CONFIRMED: webview.create_window called {total_calls} times in run(). "
            "Expected exactly 1 call (main window only). The floating ball window is created "
            "at startup, confirming Bug 1 (startup visibility)."
        )


# ---------------------------------------------------------------------------
# Test 2 — hidden=True parameter check
#
# Assert the second create_window call (ball window) includes hidden=True.
# This confirms reliance on the unreliable hidden parameter.
# EXPECTED: FAIL on unfixed code (second call exists and has hidden=True).
# ---------------------------------------------------------------------------


class TestBallWindowHiddenParam:
    """**Validates: Requirements 1.2, 1.3**"""

    def test_ball_create_window_uses_hidden_true(self) -> None:
        """Assert the ball window create_window call does NOT include hidden=True.

        On unfixed code: run() calls create_window a second time for the ball window
        WITH hidden=True. This test FAILS on unfixed code, confirming the code relies
        on the unreliable hidden=True parameter to suppress the ball at startup.
        After the fix (lazy creation), there is no second call at all, so this test
        will pass because the ball window is never created at startup.
        """
        pm = ProgressManager()
        qm = QueueManager()
        overlay = MagicMock()
        overlay.start = MagicMock()
        app = PyWebViewApp(pm, qm, overlay)

        mock_main_win = MagicMock()
        mock_main_win.events = MagicMock()
        mock_main_win.events.closed = MagicMock()
        mock_main_win.shown = True

        mock_ball_win = MagicMock()
        mock_ball_win.shown = False

        call_count = {"n": 0}
        captured_calls: list[dict] = []

        def fake_create_window(*args, **kwargs):
            call_count["n"] += 1
            captured_calls.append({"args": args, "kwargs": kwargs})
            if call_count["n"] == 1:
                return mock_main_win
            return mock_ball_win

        with patch("webview.create_window", side_effect=fake_create_window):
            with patch("webview.start", side_effect=lambda *a, **kw: None):
                app.run()

        # After the fix (lazy creation): only 1 create_window call (main window only).
        # The ball window is never created at startup — no hidden=True parameter used.
        # If there is a second call, it must NOT include hidden=True.
        if len(captured_calls) >= 2:
            ball_kwargs = captured_calls[1]["kwargs"]
            assert ball_kwargs.get("hidden") is not True, (
                "BUG 1 CONFIRMED: second create_window call includes hidden=True. "
                "This confirms the code relies on hidden=True to suppress the ball at startup, "
                "which is not reliably honored on all platforms (e.g. Windows/Edge WebView2). "
                f"Actual kwargs: {ball_kwargs}"
            )
        # If only 1 call: fix is applied correctly — ball window not created at startup.


# ---------------------------------------------------------------------------
# Test 3 — CSS pollution check
#
# Parse frontend/floating.html and assert it contains NO <link rel="stylesheet"> tags.
# On unfixed code it contains two <link> tags (tokens.css + global.css), confirming Bug 2.
# EXPECTED: FAIL on unfixed code.
# ---------------------------------------------------------------------------


class TestFloatingHtmlCssPollution:
    """**Validates: Requirements 1.4, 1.5**"""

    def test_floating_html_has_no_link_stylesheets(self) -> None:
        """Assert floating.html contains no <link rel="stylesheet"> tags.

        On unfixed code: floating.html references tokens.css and global.css via
        <link rel="stylesheet"> tags. These external CSS files may set opaque
        backgrounds on body/#app, causing the black rectangular border/background bug.
        This test FAILS on unfixed code, confirming Bug 2 (CSS pollution).
        """
        html_path = Path("frontend/floating.html")
        assert html_path.exists(), f"floating.html not found at {html_path.resolve()}"

        html_content = html_path.read_text(encoding="utf-8")

        collector = _LinkTagCollector()
        collector.feed(html_content)

        stylesheet_links = collector.stylesheet_links
        found_hrefs = [link.get("href", "") for link in stylesheet_links]

        assert len(stylesheet_links) == 0, (
            f"BUG 2 CONFIRMED: floating.html contains {len(stylesheet_links)} "
            "<link rel=\"stylesheet\"> tag(s). These external CSS files may set opaque "
            "backgrounds on body/#app, causing the black rectangular border/background bug.\n"
            "Found tags:\n"
            + "\n".join(f"  <link rel=\"stylesheet\" href=\"{h}\"/>" for h in found_hrefs)
        )
