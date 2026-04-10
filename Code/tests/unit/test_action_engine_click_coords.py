"""Bug condition exploration test for Bug 3:
ActionEngine.click passes logical coords to _send_move instead of physical coords.

On UNFIXED code: _send_move is called with (400, 300) (logical) → assertion FAILS.
On FIXED code:   _send_move is called with coords near (600, 450) (physical) → PASSES.
"""
from __future__ import annotations

from unittest.mock import patch, call
from typing import Any

import pytest

from execution import action_engine as ae
from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter


def test_bug3_click_passes_logical_not_physical_to_send_move() -> None:
    """Bug 3 exploration: ActionEngine.click must convert logical→physical before _send_move.

    Setup:
    - DPIAdapter(scale_factor=1.5)
    - _get_dpi_scale returns 1.5
    - _get_awareness returns 0  (DPI Unaware → bug condition active)
    - _get_virtual_screen_rect returns (0, 0, 1920, 1080)
    - _get_cursor_pos returns (0, 0)  (human_like_move starts from origin)
    - click(400, 300) is called with logical coords

    Expected (FIXED) behavior:
    - phys_x = round(400 * 1.5) = 600
    - phys_y = round(300 * 1.5) = 450
    - At least one _send_move call uses coords close to (600, 450) (±3 px jitter)

    On UNFIXED code:
    - human_like_move(400, 300) is called directly with logical coords
    - _send_move receives (400, 300) throughout
    - No call near (600, 450) → assertion FAILS ❌
    """
    engine = ActionEngine(DPIAdapter(scale_factor=1.5))

    send_move_calls: list[tuple[int, int]] = []

    def _capture_send_move(x: int, y: int) -> None:
        send_move_calls.append((x, y))

    with (
        patch.object(ae, "_send_move", side_effect=_capture_send_move),
        patch.object(ae, "_get_dpi_scale", return_value=1.5),
        patch.object(ae, "_get_awareness", return_value=0),
        patch.object(ae, "_get_virtual_screen_rect", return_value=(0, 0, 1920, 1080)),
        patch.object(ae, "_get_cursor_pos", return_value=(0, 0)),
        patch.object(ae, "_send_click"),          # suppress actual click
        patch("time.sleep"),                       # speed up the test
    ):
        engine.click(400, 300)

    assert send_move_calls, "click() made no _send_move calls at all"

    # Check that at least one call is close to the physical target (600, 450) ± 3 px jitter
    target_phys_x, target_phys_y = 600, 450
    close_calls = [
        (x, y) for (x, y) in send_move_calls
        if abs(x - target_phys_x) <= 3 and abs(y - target_phys_y) <= 3
    ]

    assert close_calls, (
        f"Bug 3 detected: no _send_move call near physical target ({target_phys_x}, {target_phys_y}). "
        f"All _send_move calls: {send_move_calls}. "
        f"Unfixed code passes logical coords (400, 300) directly, never reaching (600, 450)."
    )


# ---------------------------------------------------------------------------
# Preservation tests (Task 2) — MUST PASS on unfixed code
# ---------------------------------------------------------------------------

from hypothesis import given, settings
import hypothesis.strategies as st


@given(lx=st.integers(10, 1910), ly=st.integers(10, 1070))
@settings(max_examples=30)
def test_preservation_click_noop_at_scale_1(lx: int, ly: int) -> None:
    """Preservation: scale_factor=1.0 → to_physical is identity, _send_move gets same coords.

    **Validates: Requirements 3.5**
    """
    engine = ActionEngine(DPIAdapter(scale_factor=1.0))
    send_move_calls: list[tuple[int, int]] = []

    def _capture(x: int, y: int) -> None:
        send_move_calls.append((x, y))

    with (
        patch.object(ae, "_send_move", side_effect=_capture),
        patch.object(ae, "_get_dpi_scale", return_value=1.0),
        patch.object(ae, "_get_awareness", return_value=0),
        patch.object(ae, "_get_virtual_screen_rect", return_value=(0, 0, 1920, 1080)),
        patch.object(ae, "_get_cursor_pos", return_value=(0, 0)),
        patch.object(ae, "_send_click"),
        patch("time.sleep"),
    ):
        engine.click(lx, ly)

    assert send_move_calls, "click() made no _send_move calls"
    # At scale=1.0, physical == logical, so fine-position call should be near (lx, ly)
    close_calls = [
        (x, y) for (x, y) in send_move_calls
        if abs(x - lx) <= 3 and abs(y - ly) <= 3
    ]
    assert close_calls, (
        f"Preservation broken: no _send_move call near ({lx}, {ly}) at scale=1.0. "
        f"All calls: {send_move_calls}"
    )
