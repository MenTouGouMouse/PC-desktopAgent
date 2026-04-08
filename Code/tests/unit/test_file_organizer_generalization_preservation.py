"""
Preservation property tests for file organizer generalization fix.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

These tests MUST PASS on UNFIXED code — they capture baseline behavior to preserve.
They verify that the fix does NOT regress any existing correct behavior.

Property 2: Preservation — Non-Buggy Inputs Unchanged
  For any FileOrganizeRequest where isBugCondition does NOT hold
  (target_dir is already absolute, or is a mapped Chinese folder name),
  the fixed organize_files / run_file_organizer SHALL produce exactly the
  same result as the original code.

Tests:
  1. Absolute path passthrough — organize_files passes absolute target_dir unchanged
  2. Chinese mapped name resolution — target_dir="桌面" resolves via resolve_chinese_path
  3. FILE_CATEGORY_MAP preservation (PBT) — each extension lands in correct category
  4. No-match reporting — no matching files triggers progress_callback("无匹配文件，任务完成", 100)
  5. stop_event halts processing — stop_event set mid-run halts immediately
  6. Per-file error skip — OSError on one file skips it with WARNING, rest continue
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from automation.file_organizer import FILE_CATEGORY_MAP, run_file_organizer
from decision.tools import DesktopToolkit, resolve_chinese_path


# ---------------------------------------------------------------------------
# 1. Absolute path passthrough
# ---------------------------------------------------------------------------


def test_absolute_target_dir_passed_through_unchanged(tmp_path: Path) -> None:
    """Absolute target_dir is passed to run_file_organizer without modification.

    **Validates: Requirements 3.1**

    organize_files with target_dir already absolute must pass that exact path
    to run_file_organizer — the fix must not alter it.
    Uses tmp_path to get a platform-appropriate absolute path.
    """
    abs_source = str(tmp_path / "src")
    abs_target = str(tmp_path / "target")

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
            json.dumps({"source_dir": abs_source, "target_dir": abs_target})
        )

    assert "target_dir" in captured, "run_file_organizer was not called"
    captured_target = captured["target_dir"]
    assert Path(captured_target).is_absolute(), (
        f"Expected absolute target_dir to remain absolute, got: {captured_target!r}"
    )
    assert captured_target == abs_target, (
        f"Expected target_dir={abs_target!r} to be passed through unchanged, "
        f"got: {captured_target!r}"
    )


# ---------------------------------------------------------------------------
# 2. Chinese mapped name resolution
# ---------------------------------------------------------------------------


def test_chinese_mapped_name_resolves_to_expanduser_desktop() -> None:
    """organize_files with target_dir='桌面' resolves to os.path.expanduser('~/Desktop').

    **Validates: Requirements 3.2**

    resolve_chinese_path maps '桌面' → '~/Desktop' → expanduser result.
    The fix must not change this behavior.
    """
    expected_path = os.path.expanduser("~/Desktop")

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
            json.dumps({"source_dir": "/tmp/src", "target_dir": "桌面"})
        )

    assert "target_dir" in captured, "run_file_organizer was not called"
    captured_target = captured["target_dir"]
    assert captured_target == expected_path, (
        f"Expected target_dir='桌面' to resolve to {expected_path!r} via "
        f"resolve_chinese_path, got: {captured_target!r}"
    )


def test_resolve_chinese_path_maps_all_known_chinese_names() -> None:
    """resolve_chinese_path maps every key in _CHINESE_FOLDER_MAP to an absolute path.

    **Validates: Requirements 3.2**
    """
    chinese_names = ["桌面", "文档", "下载", "图片", "音乐", "视频"]
    for name in chinese_names:
        result = resolve_chinese_path(name)
        assert Path(result).is_absolute(), (
            f"resolve_chinese_path('{name}') should return an absolute path, "
            f"got: {result!r}"
        )
        assert "~" not in result, (
            f"resolve_chinese_path('{name}') should expand '~', got: {result!r}"
        )


# ---------------------------------------------------------------------------
# 3. FILE_CATEGORY_MAP preservation (Hypothesis PBT)
# ---------------------------------------------------------------------------


@given(st.lists(st.sampled_from(sorted(FILE_CATEGORY_MAP.keys())), min_size=1, max_size=20))
@settings(max_examples=50)
def test_property_file_category_map_preservation(extensions: list[str]) -> None:
    """Property: for any set of extensions from FILE_CATEGORY_MAP, each file
    lands in the correct category subdirectory.

    **Validates: Requirements 3.1, 3.4**

    This is the core preservation property — FILE_CATEGORY_MAP categorization
    must remain unchanged after the fix is applied.
    """
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        target_dir = Path(tmp) / "target"
        source_dir.mkdir()

        # Create one file per unique extension
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
# 4. No-match reporting
# ---------------------------------------------------------------------------


def test_no_match_file_filters_reports_completion_at_100(tmp_path: Path) -> None:
    """file_filters with no matching files triggers progress_callback("无匹配文件，任务完成", 100).

    **Validates: Requirements 3.3**
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
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
# 5. stop_event halts processing
# ---------------------------------------------------------------------------


def test_stop_event_halts_processing_immediately(tmp_path: Path) -> None:
    """stop_event set mid-run halts processing without moving further files.

    **Validates: Requirements 3.3**

    Creates 10 files. Sets stop_event after the 3rd callback. Verifies that
    fewer than 10 files are moved (processing was halted).
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for i in range(10):
        (source_dir / f"file{i:02d}.jpg").write_bytes(b"data")

    target_dir = tmp_path / "target"
    stop_event = threading.Event()
    callback_count = 0

    def progress_callback(step: str, percent: int) -> None:
        nonlocal callback_count
        callback_count += 1
        if callback_count >= 3:
            stop_event.set()

    run_file_organizer(
        source_dir=source_dir,
        target_dir=target_dir,
        progress_callback=progress_callback,
        stop_event=stop_event,
    )

    images_dir = target_dir / "Images"
    moved_files = list(images_dir.rglob("*.jpg")) if images_dir.exists() else []
    assert len(moved_files) < 10, (
        f"Expected fewer than 10 files to be moved after stop_event, "
        f"but found {len(moved_files)} files moved."
    )
    assert len(moved_files) >= 1, (
        "Expected at least 1 file to be moved before stop_event was set."
    )


# ---------------------------------------------------------------------------
# 6. Per-file error skip
# ---------------------------------------------------------------------------


def test_per_file_oserror_skips_file_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """OSError on one file causes it to be skipped with WARNING; remaining files continue.

    **Validates: Requirements 3.5**

    Mocks shutil.move to raise OSError on the first call. Verifies:
    - A WARNING log is emitted for the failed file
    - shutil.move is called a second time (remaining file is attempted)
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "fail.jpg").write_bytes(b"fail")
    (source_dir / "ok.jpg").write_bytes(b"ok")

    target_dir = tmp_path / "target"
    stop_event = threading.Event()
    call_count = 0

    def mock_move(src: str, dst: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Permission denied")
        # Second call: do nothing (file stays in source, but no exception)

    with caplog.at_level(logging.WARNING, logger="automation.file_organizer"):
        with patch("shutil.move", side_effect=mock_move):
            run_file_organizer(
                source_dir=source_dir,
                target_dir=target_dir,
                progress_callback=lambda s, p: None,
                stop_event=stop_event,
            )

    # A WARNING log must have been emitted for the failed file
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_messages) >= 1, (
        f"Expected at least 1 WARNING log for the failed move, got: {caplog.records}"
    )
    assert any("移动文件失败" in msg or "跳过" in msg for msg in warning_messages), (
        f"Expected WARNING to mention '移动文件失败' or '跳过', got: {warning_messages}"
    )

    # shutil.move must have been called twice — second file was attempted
    assert call_count == 2, (
        f"Expected shutil.move to be called twice (once fail, once continue), "
        f"got {call_count} calls."
    )
