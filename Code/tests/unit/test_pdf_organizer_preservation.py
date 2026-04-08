"""
Preservation property tests for run_file_organizer — Non-Buggy Behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

These tests MUST PASS on UNFIXED code — they capture baseline behavior to preserve.
They verify that the fix does NOT regress any existing correct behavior.

Property 4: Preservation — Non-Buggy Inputs Unchanged
  For any FileOrganizeRequest where none of the three bug conditions hold,
  the fixed run_file_organizer SHALL produce exactly the same result as the original.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from automation.file_organizer import FILE_CATEGORY_MAP, run_file_organizer


# ---------------------------------------------------------------------------
# Property-based test: FILE_CATEGORY_MAP preservation
# ---------------------------------------------------------------------------


@given(st.lists(st.sampled_from(sorted(FILE_CATEGORY_MAP.keys())), min_size=1, max_size=20))
@settings(max_examples=50)
def test_property_file_category_map_preservation(extensions: list[str]) -> None:
    """Property: for any set of file extensions from FILE_CATEGORY_MAP, each file
    lands in the correct category subdirectory as defined by FILE_CATEGORY_MAP.

    **Validates: Requirements 3.1, 3.4**

    This is the core preservation property — FILE_CATEGORY_MAP categorization
    must remain unchanged after the fix.
    """
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        target_dir = Path(tmp) / "target"
        source_dir.mkdir()

        # Create one file per extension (deduplicate extensions to avoid name collisions)
        seen_exts: set[str] = set()
        created: list[tuple[str, tuple[str, str]]] = []  # (filename, (parent, sub))
        for i, ext in enumerate(extensions):
            if ext in seen_exts:
                continue
            seen_exts.add(ext)
            filename = f"file_{i}{ext}"
            (source_dir / filename).write_bytes(b"data")
            created.append((filename, FILE_CATEGORY_MAP[ext]))

        stop_event = threading.Event()
        run_file_organizer(
            source_dir=source_dir,
            target_dir=target_dir,
            progress_callback=lambda s, p: None,
            stop_event=stop_event,
        )

        for filename, (parent, sub) in created:
            dest = target_dir / parent / sub / filename
            assert dest.exists(), (
                f"File '{filename}' should be in '{parent}/{sub}/' "
                f"but was not found at '{dest}'"
            )


# ---------------------------------------------------------------------------
# Example-based test: stop_event halts processing
# ---------------------------------------------------------------------------


def test_stop_event_halts_processing_without_moving_further_files(tmp_path: Path) -> None:
    """Example: setting stop_event mid-run halts processing without moving further files.

    **Validates: Requirements 3.2**

    Creates 10 files. Sets stop_event after the 3rd callback. Verifies that
    fewer than 10 files are moved (processing was halted).
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    # Create 10 files with known names so we can count what was moved
    for i in range(10):
        (source_dir / f"file{i:02d}.jpg").write_bytes(b"data")

    target_dir = tmp_path / "target"
    stop_event = threading.Event()
    callback_count = 0

    def progress_callback(step: str, percent: int) -> None:
        nonlocal callback_count
        callback_count += 1
        # Set stop after 3rd successful move callback
        if callback_count >= 3:
            stop_event.set()

    run_file_organizer(
        source_dir=source_dir,
        target_dir=target_dir,
        progress_callback=progress_callback,
        stop_event=stop_event,
    )

    # Fewer than 10 files should have been moved (stop_event halted processing)
    moved_files = list((target_dir / "Images").rglob("*.jpg")) if (target_dir / "Images").exists() else []
    assert len(moved_files) < 10, (
        f"Expected fewer than 10 files to be moved after stop_event, "
        f"but found {len(moved_files)} files moved."
    )
    # At least some files were moved before the stop
    assert len(moved_files) >= 1, "Expected at least 1 file to be moved before stop_event."


# ---------------------------------------------------------------------------
# Example-based test: no-match reporting
# ---------------------------------------------------------------------------


def test_no_match_file_filters_reports_completion_at_100(tmp_path: Path) -> None:
    """Example: file_filters with no matching files triggers
    progress_callback("无匹配文件，任务完成", 100).

    **Validates: Requirements 3.3**
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    # Create files that do NOT match the filter
    (source_dir / "photo.jpg").write_bytes(b"img")
    (source_dir / "doc.txt").write_bytes(b"text")

    target_dir = tmp_path / "target"
    stop_event = threading.Event()
    callbacks: list[tuple[str, int]] = []

    run_file_organizer(
        source_dir=source_dir,
        target_dir=target_dir,
        progress_callback=lambda s, p: callbacks.append((s, p)),
        stop_event=stop_event,
        file_filters=[".pdf"],  # no PDFs in source
    )

    assert len(callbacks) == 1, (
        f"Expected exactly 1 callback for no-match case, got {len(callbacks)}: {callbacks}"
    )
    step, percent = callbacks[0]
    assert percent == 100, f"Expected percent=100 for no-match, got {percent}"
    assert "无匹配文件" in step, (
        f"Expected '无匹配文件' in callback message, got: '{step}'"
    )
    assert "任务完成" in step, (
        f"Expected '任务完成' in callback message, got: '{step}'"
    )


# ---------------------------------------------------------------------------
# Example-based test: per-file error skip
# ---------------------------------------------------------------------------


def test_per_file_oserror_skips_file_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Example: mock shutil.move raising OSError for one file — that file is
    skipped with a WARNING log, and remaining files continue to be processed.

    **Validates: Requirements 3.5**
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "fail.jpg").write_bytes(b"fail")
    (source_dir / "ok.jpg").write_bytes(b"ok")

    target_dir = tmp_path / "target"
    stop_event = threading.Event()
    callbacks: list[tuple[str, int]] = []

    # Sort order matters: we need to know which file is processed first.
    # shutil.move side_effect: first call raises OSError, second succeeds.
    call_count = 0

    def mock_move(src: str, dst: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Permission denied")
        # Second call: actually perform the move so the file lands in target
        import shutil as _shutil
        _shutil.move.__wrapped__(src, dst) if hasattr(_shutil.move, "__wrapped__") else None

    with caplog.at_level(logging.WARNING, logger="automation.file_organizer"):
        with patch("shutil.move", side_effect=mock_move):
            run_file_organizer(
                source_dir=source_dir,
                target_dir=target_dir,
                progress_callback=lambda s, p: callbacks.append((s, p)),
                stop_event=stop_event,
            )

    # A WARNING log must have been emitted for the failed file
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_messages) >= 1, (
        f"Expected at least 1 WARNING log for the failed move, got: {caplog.records}"
    )
    # The warning should mention the failure
    assert any("移动文件失败" in msg or "跳过" in msg for msg in warning_messages), (
        f"Expected WARNING to mention '移动文件失败' or '跳过', got: {warning_messages}"
    )

    # Processing must not have been aborted — we got at least one callback
    # (the second file was attempted, even if the mock didn't actually move it)
    assert call_count == 2, (
        f"Expected shutil.move to be called twice (once fail, once succeed), "
        f"got {call_count} calls."
    )
