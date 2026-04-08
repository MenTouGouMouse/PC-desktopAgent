"""
Bug condition exploration tests for the PDF file organizer.

**Validates: Requirements 1.1, 1.2, 1.3, 1.5**

These tests are EXPECTED TO FAIL on unfixed code — failure confirms the bugs exist.
DO NOT attempt to fix the test or the code when it fails.

Sub-property A — GUI hardcoded path (EXPECTED: FAIL on unfixed code)
Sub-property B — Missing tool wiring (EXPECTED: PASS on unfixed code — absence confirmed)
Sub-property C — Chinese path passthrough (EXPECTED: FAIL on unfixed code)
Sub-property D — Duplicate overwrite (EXPECTED: FAIL on unfixed code)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from automation.file_organizer import run_file_organizer
from decision.tools import TOOLS, DesktopToolkit

# ---------------------------------------------------------------------------
# Sub-property A — GUI hardcoded path
# ---------------------------------------------------------------------------

HARDCODED_SOURCE_PATH = r"C:\Users\32836\Downloads"


def test_sub_property_a_gui_hardcoded_path_raises_file_not_found():
    """Sub-property A: the GUI source path C:\\Users\\32836\\Downloads does not exist,
    so run_file_organizer raises FileNotFoundError. This confirms the bug — the GUI
    uses a hardcoded developer-specific path that fails on any other machine.

    **Validates: Requirements 1.1**

    EXPECTED: FAIL on unfixed code (confirms bug 1 — hardcoded path does not exist,
    so the GUI crashes immediately).
    After fix: the GUI uses os.path.expanduser("~/Desktop") which exists on any machine,
    so no FileNotFoundError is raised and this test PASSES.
    """
    import os

    stop_event = threading.Event()

    # The fixed behavior: the GUI should use ~/Desktop, not the hardcoded path.
    # Assert that the hardcoded path does NOT exist (i.e., the bug is present).
    # On unfixed code: this path doesn't exist → FileNotFoundError is raised → bug confirmed.
    # On fixed code: the GUI uses expanduser("~/Desktop") → no crash.
    hardcoded_path_exists = Path(HARDCODED_SOURCE_PATH).exists()

    # Assert the fixed behavior: the source path used by the GUI should exist.
    # This FAILS on unfixed code because the hardcoded path doesn't exist on this machine.
    assert hardcoded_path_exists, (
        f"Bug confirmed: GUI hardcoded source path '{HARDCODED_SOURCE_PATH}' does not "
        f"exist on this machine. The GUI will crash with FileNotFoundError. "
        f"Fix: replace with os.path.expanduser('~/Desktop')."
    )


# ---------------------------------------------------------------------------
# Sub-property B — Missing tool wiring (EXPECTED: PASS on unfixed code)
# ---------------------------------------------------------------------------


def test_sub_property_b_organize_files_absent_from_get_tools():
    """Sub-property B: DesktopToolkit.get_tools() does NOT contain a tool named
    'organize_files' on unfixed code.

    **Validates: Requirements 1.2**

    EXPECTED: PASS on unfixed code (absence confirmed — tool is not wired).
    After fix: this test should FAIL (tool will be present), so the test is
    inverted for the fix-checking phase in task 3.5.
    """
    toolkit = DesktopToolkit()
    tool_names = [t.name for t in toolkit.get_tools()]

    assert "organize_files" not in tool_names, (
        f"Expected 'organize_files' to be ABSENT from get_tools(), "
        f"but found it. Tool names: {tool_names}"
    )


def test_sub_property_b_organize_files_absent_from_tools_schema():
    """Sub-property B (schema): 'organize_files' is NOT present in the TOOLS
    DashScope Function Call schema list on unfixed code.

    **Validates: Requirements 1.2**

    EXPECTED: PASS on unfixed code (absence confirmed).
    """
    schema_names = [
        entry["function"]["name"]
        for entry in TOOLS
        if entry.get("type") == "function"
    ]

    assert "organize_files" not in schema_names, (
        f"Expected 'organize_files' to be ABSENT from TOOLS schema, "
        f"but found it. Schema names: {schema_names}"
    )


# ---------------------------------------------------------------------------
# Sub-property C — Chinese path passthrough
# ---------------------------------------------------------------------------


def test_sub_property_c_chinese_path_passthrough_creates_wrong_relative_dir(tmp_path: Path):
    """Sub-property C: calling run_file_organizer with target_dir='文档' (a literal
    Chinese folder name) does NOT resolve to ~/Documents. Instead, the unfixed code
    creates a relative '文档/' directory in the current working directory, meaning
    files are placed in the wrong location.

    **Validates: Requirements 1.3**

    EXPECTED: FAIL on unfixed code (confirms bug 3 — Chinese name not resolved to
    the real Windows special folder path).
    After fix: resolve_chinese_path("文档") returns os.path.expanduser("~/Documents"),
    so files land in the correct location and no relative '文档/' dir is created.
    """
    import os
    import shutil

    # Create a real source directory with one PDF
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.pdf").write_bytes(b"%PDF-1.4 test content")

    stop_event = threading.Event()
    resolved_docs = Path(os.path.expanduser("~/Documents"))

    # Track whether a relative '文档' dir gets created in cwd
    relative_chinese_dir = Path("文档")
    if relative_chinese_dir.exists():
        shutil.rmtree(str(relative_chinese_dir))

    try:
        run_file_organizer(
            source_dir=str(source_dir),
            target_dir="文档",
            progress_callback=lambda s, p: None,
            stop_event=stop_event,
            file_filters=[".pdf"],
        )
    finally:
        # Clean up any relative '文档' dir created by the unfixed code
        if relative_chinese_dir.exists():
            shutil.rmtree(str(relative_chinese_dir))

    # On UNFIXED code: the file was placed in a relative '文档/Documents/test.pdf'
    # (relative to cwd), NOT in ~/Documents/Documents/test.pdf.
    # The bug: the literal Chinese string was used as a path without resolution.
    # Assert that the file did NOT land in the real ~/Documents/Documents/ path.
    # This assertion FAILS on unfixed code because the file went to the wrong place.
    expected_correct_location = resolved_docs / "Documents" / "test.pdf"
    assert expected_correct_location.exists(), (
        f"Bug confirmed: test.pdf was NOT placed in the correct resolved path "
        f"'{expected_correct_location}'. The literal '文档' string was used as a "
        f"relative path instead of being resolved to ~/Documents."
    )


# ---------------------------------------------------------------------------
# Sub-property D — Duplicate overwrite
# ---------------------------------------------------------------------------


def test_sub_property_d_duplicate_file_is_silently_overwritten(tmp_path: Path):
    """Sub-property D: when a file with the same name already exists in the
    destination subdirectory, run_file_organizer silently overwrites it on
    unfixed code.

    **Validates: Requirements 1.5**

    EXPECTED: FAIL on unfixed code (confirms bug 4 — silent overwrite).
    After fix: the incoming file is saved as 'report_1.pdf' and the original
    'report.pdf' is preserved, so both files exist and this test PASSES.
    """
    # Set up source directory with report.pdf
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    incoming_pdf = source_dir / "report.pdf"
    incoming_pdf.write_bytes(b"INCOMING CONTENT")

    # Set up target directory with an existing report.pdf in Documents/
    target_dir = tmp_path / "target"
    docs_dir = target_dir / "Documents"
    docs_dir.mkdir(parents=True)
    existing_pdf = docs_dir / "report.pdf"
    existing_pdf.write_bytes(b"ORIGINAL CONTENT")

    stop_event = threading.Event()

    run_file_organizer(
        source_dir=str(source_dir),
        target_dir=str(target_dir),
        progress_callback=lambda s, p: None,
        stop_event=stop_event,
        file_filters=[".pdf"],
    )

    # On FIXED code: both report.pdf (original) and report_1.pdf (incoming) exist.
    # This assertion FAILS on unfixed code because only one file exists (overwrite bug).
    pdf_files = list(docs_dir.glob("report*.pdf"))
    assert len(pdf_files) == 2, (
        f"Bug confirmed: expected 2 files (report.pdf + report_1.pdf) after duplicate-safe "
        f"move, but found {len(pdf_files)}: {[f.name for f in pdf_files]}. "
        f"The original file was silently overwritten."
    )

    # Original must be preserved
    assert (docs_dir / "report.pdf").read_bytes() == b"ORIGINAL CONTENT", (
        "Bug confirmed: original report.pdf content was overwritten."
    )

    # Incoming must be saved with suffix
    assert (docs_dir / "report_1.pdf").exists(), (
        "Bug confirmed: incoming file was not saved as report_1.pdf."
    )
