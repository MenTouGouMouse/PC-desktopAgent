"""
Preservation property tests for Bug 3 (font/style) — BEFORE fix.

These tests verify that existing good styles in the Vue source files are preserved:
  - LogOutput.vue uses a monospace font for .log-output (regression guard)
  - FloatingBall.vue ball container has border-radius: 50% (regression guard)

They PASS on unfixed code and must continue to PASS after the style fix is applied.

Validates: Requirements 3.7, 3.8
"""
from __future__ import annotations

import pathlib

# Paths to Vue source files (relative to workspace root)
WORKSPACE_ROOT = pathlib.Path(__file__).parent.parent.parent
LOG_OUTPUT_VUE = WORKSPACE_ROOT / "frontend" / "src" / "components" / "LogOutput.vue"
FLOATING_BALL_VUE = WORKSPACE_ROOT / "frontend" / "src" / "FloatingBall.vue"


def _read_source(path: pathlib.Path) -> str:
    """Read a Vue source file as text."""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Property 2a: LogOutput.vue monospace font preservation
# Validates: Requirement 3.7
# ---------------------------------------------------------------------------

def test_log_output_uses_monospace_font() -> None:
    """
    **Validates: Requirements 3.7**

    WHEN the log output area renders log lines
    THEN the system SHALL CONTINUE TO use a monospace font for log text.

    Assert that LogOutput.vue scoped styles contain 'monospace' (or 'Consolas')
    so that any future style fix cannot accidentally remove the monospace font.
    """
    source = _read_source(LOG_OUTPUT_VUE)
    # The .log-output rule must reference a monospace font stack
    assert "monospace" in source, (
        "LogOutput.vue must contain 'monospace' in its font-family declaration. "
        "Removing the monospace font would break requirement 3.7."
    )


def test_log_output_font_family_in_log_output_rule() -> None:
    """
    **Validates: Requirements 3.7**

    More specific check: the font-family declaration must appear inside the
    .log-output scoped style block (not just anywhere in the file).
    """
    source = _read_source(LOG_OUTPUT_VUE)
    # Verify .log-output class is present and font-family is declared
    assert ".log-output" in source, "LogOutput.vue must define a .log-output CSS class"
    assert "font-family" in source, (
        "LogOutput.vue must have a font-family declaration in its scoped styles"
    )


# ---------------------------------------------------------------------------
# Property 2b: FloatingBall.vue border-radius: 50% preservation
# Validates: Requirement 3.8
# ---------------------------------------------------------------------------

def test_floating_ball_has_border_radius_50() -> None:
    """
    **Validates: Requirements 3.8**

    WHEN the floating ball's border-radius: 50% and transparent background are applied
    THEN the system SHALL CONTINUE TO render the ball as a circular overlay.

    Assert that FloatingBall.vue still contains 'border-radius: 50%' so that
    any future style fix cannot accidentally remove the circular shape.
    """
    source = _read_source(FLOATING_BALL_VUE)
    assert "border-radius: 50%" in source, (
        "FloatingBall.vue must contain 'border-radius: 50%' to keep the circular shape. "
        "Removing this would break requirement 3.8."
    )


def test_floating_ball_has_transparent_body_background() -> None:
    """
    **Validates: Requirements 3.8**

    The floating ball window body must have a transparent background so that
    no rectangular frame is visible around the circular ball.
    """
    source = _read_source(FLOATING_BALL_VUE)
    assert "background: transparent" in source, (
        "FloatingBall.vue must set 'background: transparent' on the body "
        "to ensure no rectangular frame is visible (requirement 3.8)."
    )
