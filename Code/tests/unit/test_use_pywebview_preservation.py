"""
Preservation property tests for JS bridge timing (Bug 1, BEFORE fix).

Task 15 — Property 2: Preservation

Validates: Requirements 3.1, 3.6

These tests document the CORRECT behaviors that must be preserved after the fix.
They are written against the UNFIXED composable pattern and MUST PASS on unfixed code.

Preserved behaviors:
  1. When window.pywebview.api IS available at call time, each composable method
     delegates to the correct underlying Python API method.
  2. When window.pywebview is absent at call time, all methods return None
     gracefully without raising any exception.

EXPECTED OUTCOME on UNFIXED code: ALL tests PASS.
EXPECTED OUTCOME on FIXED code: ALL tests MUST STILL PASS (regression prevention).
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st


# ---------------------------------------------------------------------------
# Helpers: reuse the same simulation helpers as the exploration test
# ---------------------------------------------------------------------------

class SimulatedWindow:
    """Simulates the browser window object."""
    pywebview = None


def simulate_use_pywebview_unfixed(window: SimulatedWindow) -> dict:
    """
    Simulates the UNFIXED usePyWebView composable.
    api is captured ONCE at composable init time.
    """
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


# ---------------------------------------------------------------------------
# Preservation 1: bridge available at call time → correct delegation
# (Requirement 3.1)
# ---------------------------------------------------------------------------

def test_preservation_start_file_organizer_delegates_when_bridge_ready() -> None:
    """
    Preservation: when bridge is available at composable init time,
    startFileOrganizer() calls api.start_file_organizer() exactly once.

    MUST PASS on unfixed code (no bug when bridge is ready at init).
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['startFileOrganizer']()

    mock_api.start_file_organizer.assert_called_once()


def test_preservation_start_smart_installer_delegates_when_bridge_ready() -> None:
    """
    Preservation: startSmartInstaller() calls api.start_smart_installer() exactly once.
    MUST PASS on unfixed code.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['startSmartInstaller']()

    mock_api.start_smart_installer.assert_called_once()


def test_preservation_minimize_to_ball_delegates_when_bridge_ready() -> None:
    """Preservation: minimizeToBall() calls api.minimize_to_ball() exactly once."""
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['minimizeToBall']()

    mock_api.minimize_to_ball.assert_called_once()


def test_preservation_restore_main_window_delegates_when_bridge_ready() -> None:
    """Preservation: restoreMainWindow() calls api.restore_main_window() exactly once."""
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['restoreMainWindow']()

    mock_api.restore_main_window.assert_called_once()


def test_preservation_get_progress_delegates_when_bridge_ready() -> None:
    """Preservation: getProgress() calls api.get_progress() exactly once."""
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['getProgress']()

    mock_api.get_progress.assert_called_once()


def test_preservation_stop_task_delegates_when_bridge_ready() -> None:
    """Preservation: stopTask() calls api.stop_task() exactly once."""
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['stopTask']()

    mock_api.stop_task.assert_called_once()


def test_preservation_move_ball_window_delegates_with_correct_args() -> None:
    """
    Preservation: moveBallWindow(x, y) calls api.move_ball_window(x, y)
    with the exact same coordinates.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['moveBallWindow'](320, 480)

    mock_api.move_ball_window.assert_called_once_with(320, 480)


# ---------------------------------------------------------------------------
# Preservation 2: bridge absent at call time → graceful None, no exception
# (Requirement 3.6)
# ---------------------------------------------------------------------------

def test_preservation_absent_bridge_start_file_organizer_returns_none() -> None:
    """
    Preservation: when window.pywebview is absent, startFileOrganizer()
    returns None without raising any exception.
    """
    window = SimulatedWindow()  # pywebview = None
    composable = simulate_use_pywebview_unfixed(window)

    result = composable['startFileOrganizer']()
    assert result is None


def test_preservation_absent_bridge_start_smart_installer_returns_none() -> None:
    """Preservation: startSmartInstaller() returns None when bridge absent."""
    window = SimulatedWindow()
    composable = simulate_use_pywebview_unfixed(window)

    result = composable['startSmartInstaller']()
    assert result is None


def test_preservation_absent_bridge_all_methods_return_none_no_throw() -> None:
    """
    Preservation: ALL seven composable methods return None gracefully
    when window.pywebview is absent — no AttributeError, no TypeError.
    """
    window = SimulatedWindow()
    composable = simulate_use_pywebview_unfixed(window)

    assert composable['startFileOrganizer']() is None
    assert composable['startSmartInstaller']() is None
    assert composable['minimizeToBall']() is None
    assert composable['restoreMainWindow']() is None
    assert composable['getProgress']() is None
    assert composable['stopTask']() is None
    assert composable['moveBallWindow'](0, 0) is None


# ---------------------------------------------------------------------------
# Property-based: bridge available at init → all methods delegate correctly
# (Requirement 3.1)
# ---------------------------------------------------------------------------

METHOD_NAMES = [
    'startFileOrganizer',
    'startSmartInstaller',
    'minimizeToBall',
    'restoreMainWindow',
    'getProgress',
    'stopTask',
]

API_METHOD_MAP = {
    'startFileOrganizer': 'start_file_organizer',
    'startSmartInstaller': 'start_smart_installer',
    'minimizeToBall': 'minimize_to_ball',
    'restoreMainWindow': 'restore_main_window',
    'getProgress': 'get_progress',
    'stopTask': 'stop_task',
}


@given(st.sampled_from(METHOD_NAMES))
@settings(max_examples=30)
def test_preservation_pbt_bridge_ready_delegates_to_correct_api_method(method_name: str) -> None:
    """
    Property: for any composable method, when the bridge is available at init time,
    calling that method invokes the corresponding Python API method exactly once.

    MUST PASS on unfixed code (bridge available at init = no bug).
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable[method_name]()

    expected_api_method = API_METHOD_MAP[method_name]
    getattr(mock_api, expected_api_method).assert_called_once()


@given(st.integers(min_value=-10000, max_value=10000), st.integers(min_value=-10000, max_value=10000))
@settings(max_examples=30)
def test_preservation_pbt_move_ball_window_passes_coords_unchanged(x: int, y: int) -> None:
    """
    Property: moveBallWindow(x, y) passes x and y to api.move_ball_window unchanged,
    for any integer coordinate values.

    MUST PASS on unfixed code.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable['moveBallWindow'](x, y)

    mock_api.move_ball_window.assert_called_once_with(x, y)


@given(st.sampled_from(METHOD_NAMES))
@settings(max_examples=30)
def test_preservation_pbt_absent_bridge_no_exception(method_name: str) -> None:
    """
    Property: for any composable method, when window.pywebview is absent,
    calling that method returns None without raising any exception.

    MUST PASS on unfixed code (graceful no-op is preserved behavior).
    """
    window = SimulatedWindow()  # pywebview = None
    composable = simulate_use_pywebview_unfixed(window)

    try:
        result = composable[method_name]()
        assert result is None, f"{method_name}() should return None when bridge absent, got {result!r}"
    except Exception as exc:
        pytest.fail(f"{method_name}() raised {type(exc).__name__} when bridge absent: {exc}")


@given(st.integers(min_value=-10000, max_value=10000), st.integers(min_value=-10000, max_value=10000))
@settings(max_examples=20)
def test_preservation_pbt_move_ball_absent_bridge_no_exception(x: int, y: int) -> None:
    """
    Property: moveBallWindow(x, y) returns None without raising when bridge absent.
    MUST PASS on unfixed code.
    """
    window = SimulatedWindow()
    composable = simulate_use_pywebview_unfixed(window)

    try:
        result = composable['moveBallWindow'](x, y)
        assert result is None
    except Exception as exc:
        pytest.fail(f"moveBallWindow({x}, {y}) raised {type(exc).__name__} when bridge absent: {exc}")


# ---------------------------------------------------------------------------
# Parametrized: each method delegates to the correct API method (no cross-wiring)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("composable_method,api_method", list(API_METHOD_MAP.items()))
def test_preservation_no_cross_wiring(composable_method: str, api_method: str) -> None:
    """
    Preservation: each composable method calls ONLY its own corresponding API method,
    not any other method. Ensures no cross-wiring regressions.

    MUST PASS on unfixed code.
    """
    window = SimulatedWindow()
    mock_api = MagicMock()
    window.pywebview = MagicMock()
    window.pywebview.api = mock_api

    composable = simulate_use_pywebview_unfixed(window)
    composable[composable_method]()

    # The correct method was called
    getattr(mock_api, api_method).assert_called_once()

    # No other API methods were called
    for other_api_method in API_METHOD_MAP.values():
        if other_api_method != api_method:
            getattr(mock_api, other_api_method).assert_not_called()
