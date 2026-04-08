"""
Unit tests for utils.path_resolver.resolve_path.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.1**

Covers:
- Each alias in ALIAS_MAP resolves to Path.home() / subfolder
- Foreign-user Windows path normalization
- Foreign-user Unix path normalization
- Valid absolute path outside home passes through unchanged
- Current user's own home path passes through unchanged
- Edge cases: empty string, trailing slash, mixed-case alias (no match)
"""
from __future__ import annotations

import platform
from pathlib import Path

import pytest

from utils.path_resolver import ALIAS_MAP, resolve_path


# ---------------------------------------------------------------------------
# Alias resolution tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,subfolder", list(ALIAS_MAP.items()))
def test_alias_resolves_to_home_subfolder(alias: str, subfolder: str) -> None:
    """Each alias in ALIAS_MAP must resolve to Path.home() / subfolder."""
    result = resolve_path(alias)
    assert result == Path.home() / subfolder, (
        f"resolve_path({alias!r}) expected {Path.home() / subfolder}, got {result}"
    )


# ---------------------------------------------------------------------------
# Foreign-user path normalization
# ---------------------------------------------------------------------------

def test_foreign_user_windows_path_resolves_to_home_subfolder() -> None:
    """C:\\Users\\other_user\\Downloads → Path.home() / 'Downloads'."""
    foreign_path = "C:\\Users\\other_user\\Downloads"
    p = Path(foreign_path)
    # Only run the assertion if this path actually triggers the foreign-user rule
    # (i.e. parts[2] != current user). On Windows with user 'other_user' this
    # would be a same-user path, but 'other_user' is chosen to be distinct.
    if p.parts[2] == Path.home().name:
        pytest.skip("Current user is 'other_user'; cannot test foreign-user path")
    result = resolve_path(foreign_path)
    assert result == Path.home() / "Downloads"


@pytest.mark.skipif(platform.system() == "Windows", reason="Unix-style paths not absolute on Windows")
def test_foreign_user_unix_path_resolves_to_home_subfolder() -> None:
    """/home/other_user/Documents → Path.home() / 'Documents'."""
    foreign_path = "/home/other_user/Documents"
    p = Path(foreign_path)
    if p.parts[2] == Path.home().name:
        pytest.skip("Current user is 'other_user'; cannot test foreign-user path")
    result = resolve_path(foreign_path)
    assert result == Path.home() / "Documents"


@pytest.mark.skipif(platform.system() == "Windows", reason="Unix-style paths not absolute on Windows")
def test_foreign_user_path_with_nested_subdir() -> None:
    """Foreign-user path with nested subdirectory re-roots correctly."""
    foreign_path = "/home/other_user/Documents/work/notes"
    p = Path(foreign_path)
    if p.parts[2] == Path.home().name:
        pytest.skip("Current user is 'other_user'; cannot test foreign-user path")
    result = resolve_path(foreign_path)
    assert result == Path.home() / "Documents" / "work" / "notes"


# ---------------------------------------------------------------------------
# Pass-through tests (preservation)
# ---------------------------------------------------------------------------

def test_absolute_path_outside_home_passes_through() -> None:
    """D:\\Projects\\foo must pass through unchanged (not a home path)."""
    raw = "D:\\Projects\\foo"
    result = resolve_path(raw)
    assert result == Path(raw)


def test_current_user_home_path_passes_through_unchanged() -> None:
    """Current user's own Downloads path must not be rewritten."""
    own_path = str(Path.home() / "Downloads")
    result = resolve_path(own_path)
    assert result == Path(own_path)


def test_relative_path_not_in_alias_map_passes_through() -> None:
    """A relative path that is not an alias must pass through unchanged."""
    raw = "some/relative/path"
    result = resolve_path(raw)
    assert result == Path(raw)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string_passes_through() -> None:
    """Empty string is not an alias; must pass through as Path('')."""
    result = resolve_path("")
    assert result == Path("")


def test_path_with_trailing_slash_passes_through() -> None:
    """A path with a trailing slash that is not an alias passes through."""
    raw = "Downloads/"
    result = resolve_path(raw)
    assert result == Path(raw)


def test_mixed_case_alias_does_not_match() -> None:
    """Aliases are exact/case-sensitive; 'downloads' must NOT match 'Downloads'."""
    result = resolve_path("downloads")
    assert result == Path("downloads"), (
        "Mixed-case alias 'downloads' should not match 'Downloads' in ALIAS_MAP"
    )


def test_mixed_case_chinese_alias_does_not_match() -> None:
    """Partial/wrong Chinese string must not match any alias."""
    result = resolve_path("桌面 ")  # trailing space — not in map
    assert result == Path("桌面 ")


def test_resolve_path_accepts_path_object() -> None:
    """resolve_path must accept a Path object as input, not just str."""
    result = resolve_path(Path("桌面"))
    assert result == Path.home() / "Desktop"


def test_resolve_path_idempotent_for_alias() -> None:
    """Applying resolve_path twice yields the same result as once (idempotence)."""
    alias = "下载"
    once = resolve_path(alias)
    twice = resolve_path(once)
    assert once == twice, f"resolve_path not idempotent: once={once}, twice={twice}"


# ---------------------------------------------------------------------------
# Composite alias path tests (Rule 1b)
# Reproduces the real failure: LLM returned "桌面\文档" as target path,
# which is not in ALIAS_MAP and was passed through unchanged → FileNotFoundError.
# ---------------------------------------------------------------------------

def test_composite_chinese_alias_backslash() -> None:
    """'桌面\\文档' → Path.home() / 'Desktop' / '文档'.

    Reproduces the real failure observed in logs:
      target="桌面\\文档" → FileNotFoundError: 源目录不存在：桌面\\文档
    """
    result = resolve_path("桌面\\文档")
    assert result == Path.home() / "Desktop" / "文档"


def test_composite_chinese_alias_forward_slash() -> None:
    """'桌面/文档' → Path.home() / 'Desktop' / '文档'."""
    result = resolve_path("桌面/文档")
    assert result == Path.home() / "Desktop" / "文档"


def test_composite_english_alias_with_subdir() -> None:
    """'Downloads/installers' → Path.home() / 'Downloads' / 'installers'."""
    result = resolve_path("Downloads/installers")
    assert result == Path.home() / "Downloads" / "installers"


def test_composite_alias_deeply_nested() -> None:
    """'文档/work/notes' → Path.home() / 'Documents' / 'work' / 'notes'."""
    result = resolve_path("文档/work/notes")
    assert result == Path.home() / "Documents" / "work" / "notes"


def test_non_alias_first_component_passes_through() -> None:
    """'mydir/subdir' — first component not in ALIAS_MAP — passes through unchanged."""
    result = resolve_path("mydir/subdir")
    assert result == Path("mydir/subdir")


# ---------------------------------------------------------------------------
# Rule 2b: Windows path missing drive letter (file-organizer-fix)
# ---------------------------------------------------------------------------

def test_rule2b_missing_drive_desktop() -> None:
    r"""Rule 2b: resolve_path(r'\Users\32836\Desktop') → Path.home() / 'Desktop'."""
    result = resolve_path(r"\Users\32836\Desktop")
    assert result == Path.home() / "Desktop"


def test_rule2b_missing_drive_with_subpath() -> None:
    r"""Rule 2b: resolve_path(r'\Users\32836\Desktop\文档') → Path.home() / 'Desktop' / '文档'."""
    result = resolve_path(r"\Users\32836\Desktop\文档")
    assert result == Path.home() / "Desktop" / "文档"


@pytest.mark.skipif(platform.system() == "Windows", reason="Unix no-drive paths behave differently on Windows")
def test_rule2b_unix_missing_drive_documents() -> None:
    r"""Rule 2b (Unix): resolve_path(r'\home\other\Documents') → Path.home() / 'Documents'."""
    result = resolve_path(r"\home\other\Documents")
    assert result == Path.home() / "Documents"


# ---------------------------------------------------------------------------
# strip_folder_suffix tests (file-organizer-fix)
# ---------------------------------------------------------------------------

from utils.path_resolver import strip_folder_suffix  # noqa: E402


def test_strip_folder_suffix_removes_suffix() -> None:
    """'文档文件夹' → '文档'."""
    assert strip_folder_suffix("文档文件夹") == "文档"


def test_strip_folder_suffix_downloads() -> None:
    """'下载文件夹' → '下载'."""
    assert strip_folder_suffix("下载文件夹") == "下载"


def test_strip_folder_suffix_exact_three_chars_unchanged() -> None:
    """'文件夹'（长度恰好 3）原样返回，不去除。"""
    assert strip_folder_suffix("文件夹") == "文件夹"


def test_strip_folder_suffix_no_suffix_unchanged() -> None:
    """'文档'（无后缀）原样返回。"""
    assert strip_folder_suffix("文档") == "文档"


def test_strip_folder_suffix_empty_string() -> None:
    """空字符串原样返回。"""
    assert strip_folder_suffix("") == ""
