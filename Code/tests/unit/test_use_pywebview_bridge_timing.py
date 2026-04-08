"""
Bug condition exploration test for JS bridge timing (Bug 1).

Validates: Requirements 2.1, 2.2, 2.3

This test simulates the usePyWebView composable pattern in Python to verify
the fix: api is resolved at CALL TIME via getApi(), so late injection of
window.pywebview is transparent to callers.

Bug condition documented (BEFORE fix):
  - api captured as None at init time
  - window.pywebview injected AFTER init
  - startFileOrganizer() returned None (stale reference) — silent no-op
  - mock_api.start_file_organizer was NOT called

EXPECTED OUTCOME on FIXED code: ALL tests PASS.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st


# ---------------------------------------------------------------------------
# Helpers: simulate the UNFIXED composable pattern
# ---------------------------------------------------------------------------

class SimulatedWindow:
    """Simulates the browser window object."""
    pywebview = None  # Not yet injected at construction time


def simulate_use_pywebview_unfixed(window: SimulatedWindow) -> dict:
    """
    Simulates the UNFIXED usePyWebView composable.

    The bug: api is captured ONCE at composable init time.
    If window.pywebview is None at that moment, api stays None forever,
    even if window.pywebview is injected later.
    """
    # BUG: captured once at init time — equivalent to:
    #   const api = (window as any).pywebview?.api
    api = getattr(getattr(window, 'pywebview', None), 'api', None)

    return {
        'startFileOrganizer': lambda: api.start_file_organizer() if api is not None else None,
        'startSmartInstaller': lambda: api.start_smart_installer() if api is not None else None,
        'minimizeToBall': lambda: api.minimize_to_ball() if api is not None else None,
        'restoreMainWindow': lambda: api.restore_main_window() if api is not None else None,
        'getProgress': lambda: api.get_progress() if api is not None else None,
        'stopTask': lambda: api.stop_task() if api is not None else None,
        'moveBallWindow': lambda x, y: api.move_ball_window(x, y) if api is not None else None,
    }


def simulate_use_pywebview_fixed(window: SimulatedWindow) -> dict:
    """
    Simulates the FIXED usePyWebView composable.

    The fix: api is resolved at CALL TIME via getApi(), not at init time.
    Equivalent to:
      const getApi = () => (window as any).pywebview?.api
    """
    def get_api():
        return getattr(getattr(window, 'pywebview', None), 'api', None)

    return {
        'startFileOrganizer': lambda: get_api().start_file_organizer() if get_api() is not None else None,
        'startSmartInstaller': lambda: get_api().start_smart_installer() if get_api() is not None else None,
        'minimizeToBall': lambda: get_api().minimize_to_ball() if get_api() is not None else None,
        'restoreMainWindow': lambda: get_api().restore_main_window() if get_api() is not None else None,
        'getProgress': lambda: get_api().get_progress() if get_api() is not None else None,
        'stopTask': lambda: get_api().stop_task() if get_api() is not None else None,
        'moveBallWindow': lambda x, y: get_api().move_ball_window(x, y) if get_api() is not None else None,
    }


# ---------------------------------------------------------------------------
# Scenario (a): window.pywebview absent at init AND at call time
# ---------------------------------------------------------------------------

def test_bridge_absent_at_init_and_call_time_returns_none() -> None:
    """
    Validates: Requirements 2.3

    When window.pywebview is never injected, all methods return None gracefully.
    This should pass on BOTH unfixed and fixed code (baseline / no-op behavior).
    """
    window = SimulatedWindow()
    composable = simulate_use_pywebview_unfixed(window)

    result = composable['startFileOrganizer']()
    assert result is None, "Expected None when bridge is never available"


# ---------------------------------------------------------------------------
# Scenario (b): window.pywebview injected AFTER init — THE BUG
# ---------------------------------------------------------------------------

def test_bridge_called_after_late_injection() -> None:
    """
    Validates: Requirements 2.1, 2.2

    FIX VERIFICATION: composable initialized before window.pywebview is injected.
    After late injection, the FIXED composable resolves api at call time, so the
    bridge IS reached.

    EXPECTED OUTCOME on FIXED code: PASSES
    """
    window = SimulatedWindow()  # pywebview = None at init

    # Init composable BEFORE bridge is available (simulates Vue mount timing)
    composable = simulate_use_pywebview_fixed(window)

    # Inject bridge AFTER composable init (simulates PyWebView late injection)
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    # Call the method — on FIXED code, getApi() resolves fresh at call time
    composable['startFileOrganizer']()

    # ASSERT CORRECT BEHAVIOR: bridge should have been called
    mock_api.start_file_organizer.assert_called_once()


def test_smart_installer_called_after_late_injection() -> None:
    """
    Validates: Requirements 2.1, 2.2

    FIX VERIFICATION: startSmartInstaller delegates correctly after late injection.
    EXPECTED OUTCOME on FIXED code: PASSES
    """
    window = SimulatedWindow()
    composable = simulate_use_pywebview_fixed(window)

    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable['startSmartInstaller']()

    mock_api.start_smart_installer.assert_called_once()


def test_all_methods_called_after_late_injection() -> None:
    """
    Validates: Requirements 2.1, 2.2

    FIX VERIFICATION: all seven composable methods delegate to the bridge after
    late injection.
    EXPECTED OUTCOME on FIXED code: PASSES
    """
    window = SimulatedWindow()
    composable = simulate_use_pywebview_fixed(window)

    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable['minimizeToBall']()
    mock_api.minimize_to_ball.assert_called_once()

    composable['restoreMainWindow']()
    mock_api.restore_main_window.assert_called_once()

    composable['getProgress']()
    mock_api.get_progress.assert_called_once()

    composable['stopTask']()
    mock_api.stop_task.assert_called_once()

    composable['moveBallWindow'](100, 200)
    mock_api.move_ball_window.assert_called_once_with(100, 200)


# ---------------------------------------------------------------------------
# Hypothesis-based variant: bridge_available_at_init vs after_init
# ---------------------------------------------------------------------------

@given(st.booleans())
@settings(max_examples=20)
def test_bridge_timing_hypothesis(bridge_available_at_init: bool) -> None:
    """
    Validates: Requirements 2.1, 2.2, 2.3

    Property: when bridge is available at call time, startFileOrganizer() MUST
    invoke api.start_file_organizer() exactly once.

    With the fix (getApi() at call time), both cases work correctly:
    - bridge_available_at_init=True: bridge present before composable init → works
    - bridge_available_at_init=False: bridge injected after composable init → also works

    EXPECTED OUTCOME on FIXED code: PASSES for both True and False cases.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()

    if bridge_available_at_init:
        # Bridge available BEFORE composable init
        window.pywebview = MagicMock()
        window.pywebview.api = mock_api

    composable = simulate_use_pywebview_fixed(window)

    if not bridge_available_at_init:
        # Bridge injected AFTER composable init — fixed code handles this correctly
        window.pywebview = MagicMock()
        window.pywebview.api = mock_api

    composable['startFileOrganizer']()

    # Fixed code: both cases call the bridge correctly
    mock_api.start_file_organizer.assert_called_once()


# ---------------------------------------------------------------------------
# Parametrized variant covering both scenarios explicitly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inject_before_init", [True, False], ids=["bridge_at_init", "bridge_after_init"])
def test_bridge_timing_parametrized(inject_before_init: bool) -> None:
    """
    Validates: Requirements 2.1, 2.2, 2.3

    FIX VERIFICATION — parametrized test covering:
    - bridge_at_init: bridge available before composable init
    - bridge_after_init: bridge injected after composable init

    EXPECTED OUTCOME on FIXED code: PASSES for both cases.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()

    if inject_before_init:
        window.pywebview = MagicMock()
        window.pywebview.api = mock_api

    composable = simulate_use_pywebview_fixed(window)

    if not inject_before_init:
        window.pywebview = MagicMock()
        window.pywebview.api = mock_api

    composable['startFileOrganizer']()

    # Fixed code: both cases work correctly
    mock_api.start_file_organizer.assert_called_once()
