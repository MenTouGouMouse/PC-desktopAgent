"""
Bug condition exploration tests for file organizer generalization fix.

**Validates: Requirements 1.1, 1.2**

These tests are EXPECTED TO FAIL (partially) on unfixed code — failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

Sub-property A — Relative path passthrough (EXPECTED: FAIL on unfixed code)
Sub-property B — resolve_chinese_path does not handle non-Chinese relative paths (EXPECTED: PASS)
Sub-property C — Nested relative path passthrough (EXPECTED: FAIL on unfixed code)
Sub-property D — Chinese non-mapped name passthrough (EXPECTED: PASS)

EXPECTED OUTCOME on unfixed code:
- Sub-properties A and C FAIL: captured target_dir is relative, not absolute based on source parent
  → Counterexample: captured target_dir='details' is relative, not '/tmp/details'
  → Counterexample: captured target_dir='output/sorted' is relative, not '/tmp/output/sorted'
- Sub-properties B and D PASS: resolve_chinese_path does not handle these cases (returns unchanged)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from decision.tools import DesktopToolkit, resolve_chinese_path


# ---------------------------------------------------------------------------
# Sub-property A — Relative path passthrough
# ---------------------------------------------------------------------------


def test_sub_property_a_relative_target_dir_not_resolved_to_absolute() -> None:
    """Sub-property A: when organize_files is called with target_dir='details'
    (a relative path), the unfixed code passes the bare relative string directly
    to run_file_organizer without resolving it to an absolute path based on
    source_dir's parent.

    **Validates: Requirements 1.1, 1.2**

    EXPECTED: FAIL on unfixed code.
    Counterexample: captured target_dir='details' — Path('details').is_absolute() is False.
    After fix: captured target_dir='/tmp/details' — is_absolute() is True.
    """
    captured: dict[str, str] = {}

    def fake_run_file_organizer(
        source_dir: str,
        target_dir: str,
        progress_callback,
        stop_event,
        file_filters=None,
    ) -> None:
        captured["target_dir"] = target_dir

    with patch("decision.tools.run_file_organizer", side_effect=fake_run_file_organizer):
        toolkit = DesktopToolkit(
            locator=MagicMock(),
            action_engine=MagicMock(),
            screen_capturer=MagicMock(),
        )
        toolkit.organize_files(
            json.dumps({"source_dir": "/tmp/src", "target_dir": "details"})
        )

    assert "target_dir" in captured, "run_file_organizer was not called"

    captured_target = captured["target_dir"]
    # On UNFIXED code: captured_target == 'details', is_absolute() is False → assertion FAILS
    # On FIXED code:   captured_target == '/tmp/details', is_absolute() is True → assertion PASSES
    assert Path(captured_target).is_absolute(), (
        f"Bug confirmed: captured target_dir={captured_target!r} is a relative path. "
        f"Expected an absolute path based on source_dir parent '/tmp', "
        f"e.g. '/tmp/details'. The relative path will be resolved against CWD instead."
    )


# ---------------------------------------------------------------------------
# Sub-property B — resolve_chinese_path does not handle non-Chinese relative paths
# ---------------------------------------------------------------------------


def test_sub_property_b_resolve_chinese_path_returns_details_unchanged() -> None:
    """Sub-property B: resolve_chinese_path('details') returns 'details' unchanged,
    confirming the function does not cover non-Chinese relative path names.

    **Validates: Requirements 1.1**

    EXPECTED: PASS on unfixed code (confirms the function does not handle this case,
    which is the root cause of the bug — no resolution step exists for relative paths).
    """
    result = resolve_chinese_path("details")
    assert result == "details", (
        f"Expected resolve_chinese_path('details') to return 'details' unchanged, "
        f"but got {result!r}. This confirms the function does not handle non-Chinese "
        f"relative paths, leaving them unresolved."
    )


# ---------------------------------------------------------------------------
# Sub-property C — Nested relative path passthrough
# ---------------------------------------------------------------------------


def test_sub_property_c_nested_relative_target_dir_not_resolved_to_absolute() -> None:
    """Sub-property C: same as A but with target_dir='output/sorted'. On unfixed code,
    the nested relative path is passed through unchanged to run_file_organizer.

    **Validates: Requirements 1.1, 1.2**

    EXPECTED: FAIL on unfixed code.
    Counterexample: captured target_dir='output/sorted' — is_absolute() is False.
    After fix: captured target_dir='/tmp/output/sorted' — is_absolute() is True.
    """
    captured: dict[str, str] = {}

    def fake_run_file_organizer(
        source_dir: str,
        target_dir: str,
        progress_callback,
        stop_event,
        file_filters=None,
    ) -> None:
        captured["target_dir"] = target_dir

    with patch("decision.tools.run_file_organizer", side_effect=fake_run_file_organizer):
        toolkit = DesktopToolkit(
            locator=MagicMock(),
            action_engine=MagicMock(),
            screen_capturer=MagicMock(),
        )
        toolkit.organize_files(
            json.dumps({"source_dir": "/tmp/src", "target_dir": "output/sorted"})
        )

    assert "target_dir" in captured, "run_file_organizer was not called"

    captured_target = captured["target_dir"]
    # On UNFIXED code: captured_target == 'output/sorted', is_absolute() is False → FAILS
    # On FIXED code:   captured_target == '/tmp/output/sorted', is_absolute() is True → PASSES
    assert Path(captured_target).is_absolute(), (
        f"Bug confirmed: captured target_dir={captured_target!r} is a relative path. "
        f"Expected an absolute path based on source_dir parent '/tmp', "
        f"e.g. '/tmp/output/sorted'. The nested relative path is passed through unresolved."
    )


# ---------------------------------------------------------------------------
# Sub-property D — Chinese non-mapped name passthrough
# ---------------------------------------------------------------------------


def test_sub_property_d_resolve_chinese_path_returns_unmapped_chinese_unchanged() -> None:
    """Sub-property D: resolve_chinese_path('详情') returns '详情' unchanged because
    '详情' is not in _CHINESE_FOLDER_MAP, confirming the same bug path is triggered
    for unmapped Chinese folder names.

    **Validates: Requirements 1.1**

    EXPECTED: PASS on unfixed code (confirms the function does not handle unmapped
    Chinese names, so they are passed through as relative paths — same bug path).
    """
    result = resolve_chinese_path("详情")
    assert result == "详情", (
        f"Expected resolve_chinese_path('详情') to return '详情' unchanged, "
        f"but got {result!r}. '详情' is not in _CHINESE_FOLDER_MAP, so it should "
        f"be returned as-is, confirming the same unresolved-relative-path bug applies."
    )
