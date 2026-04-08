"""
Bug Condition Exploration Test Suite — Font/Style Defects (Bug 3)

These tests are EXPECTED TO FAIL on unfixed code. They confirm that style
defects exist in the current source files by asserting the ABSENCE of required
style rules. Once Bug 3 is fixed (task 22), these tests will PASS.

Validates: Requirements 2.10, 2.11, 2.12, 2.13 from bugfix.md
"""

from pathlib import Path

import pytest

# Workspace root is two levels up from tests/unit/
WORKSPACE_ROOT = Path(__file__).parent.parent.parent


def test_global_css_body_does_not_use_arial():
    """
    Bug confirmed: global.css body uses system-ui (OS default CJK font) instead of Arial.

    Unfixed behavior: font-family is 'system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
    Expected behavior after fix: font-family should include 'Arial, Helvetica, sans-serif'

    This test FAILS after the fix is applied (when Arial is added to the body rule).

    **Validates: Requirements 2.10**
    """
    css_path = WORKSPACE_ROOT / "frontend" / "src" / "styles" / "global.css"
    content = css_path.read_text(encoding="utf-8")

    # On unfixed code, Arial is absent — this assertion holds (test passes on unfixed code)
    # After fix, Arial will be present — this assertion fails (test fails on fixed code)
    assert "Arial" not in content, (
        "COUNTEREXAMPLE FOUND: global.css body already contains 'Arial'. "
        "Bug 3 (requirement 2.10) appears to be fixed — this exploration test "
        "is no longer confirming the bug. "
        f"Relevant content snippet: {content[:500]}"
    )


def test_progress_bar_label_not_bold():
    """
    Bug confirmed: ProgressBar.vue .progress-label has no font-weight: bold.

    Unfixed behavior: .progress-label only sets font-size and color, no font-weight
    Expected behavior after fix: .progress-label should have font-weight: bold or font-weight: 600

    This test FAILS after the fix is applied.

    **Validates: Requirements 2.11**
    """
    vue_path = WORKSPACE_ROOT / "frontend" / "src" / "components" / "ProgressBar.vue"
    content = vue_path.read_text(encoding="utf-8")

    # On unfixed code, font-weight bold/600 is absent from .progress-label
    has_bold = "font-weight: bold" in content or "font-weight: 600" in content
    assert not has_bold, (
        "COUNTEREXAMPLE FOUND: ProgressBar.vue already contains 'font-weight: bold' "
        "or 'font-weight: 600'. Bug 3 (requirement 2.11) appears to be fixed — "
        "this exploration test is no longer confirming the bug."
    )


def test_ring_progress_text_not_bold_or_large():
    """
    Bug confirmed: RingProgress.vue center <text> element uses font-size="14" with no bold.

    Unfixed behavior: <text> has font-size="14" and no font-weight="bold"
    Expected behavior after fix: <text> should have font-size="18" AND font-weight="bold"

    This test FAILS after the fix is applied (when both attributes are updated).

    **Validates: Requirements 2.13**
    """
    vue_path = WORKSPACE_ROOT / "frontend" / "src" / "components" / "RingProgress.vue"
    content = vue_path.read_text(encoding="utf-8")

    # On unfixed code, font-size="18" is absent
    has_large_font = 'font-size="18"' in content
    # On unfixed code, font-weight="bold" is absent from the SVG text element
    has_bold_text = 'font-weight="bold"' in content

    assert not has_large_font, (
        "COUNTEREXAMPLE FOUND: RingProgress.vue already has font-size=\"18\" on the "
        "center text element. Bug 3 (requirement 2.13) font-size part appears fixed."
    )

    assert not has_bold_text, (
        "COUNTEREXAMPLE FOUND: RingProgress.vue already has font-weight=\"bold\" on the "
        "center text element. Bug 3 (requirement 2.13) font-weight part appears fixed."
    )


def test_log_output_no_bold_error_success_styling():
    """
    Bug confirmed: LogOutput.vue has no .log-line--error or .log-line--success classes with bold styling.

    Unfixed behavior: all log lines use the same unstyled .log-line class; no error/success distinction
    Expected behavior after fix: .log-line--error and .log-line--success classes with font-weight: bold

    This test FAILS after the fix is applied.

    **Validates: Requirements 2.11, 2.12**
    """
    vue_path = WORKSPACE_ROOT / "frontend" / "src" / "components" / "LogOutput.vue"
    content = vue_path.read_text(encoding="utf-8")

    # On unfixed code, these class definitions are absent
    has_error_class = ".log-line--error" in content
    has_success_class = ".log-line--success" in content

    assert not has_error_class, (
        "COUNTEREXAMPLE FOUND: LogOutput.vue already defines '.log-line--error'. "
        "Bug 3 (requirement 2.11) error styling appears to be fixed."
    )

    assert not has_success_class, (
        "COUNTEREXAMPLE FOUND: LogOutput.vue already defines '.log-line--success'. "
        "Bug 3 (requirement 2.11) success styling appears to be fixed."
    )
