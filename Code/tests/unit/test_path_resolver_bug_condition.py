"""
Bug condition exploration test — file path resolution (file-path-resolution-fix).

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**

This test was originally written to confirm the bug exists on UNFIXED code by
asserting that `run_file_organizer` raises `FileNotFoundError` for alias inputs.

After the fix (task 3.1), this test has been updated to assert that
`resolve_path(input)` returns the correct `Path.home()`-based path for every
known buggy input — confirming the bug is resolved.

EXPECTED OUTCOME on FIXED code:
  - The test PASSES — every sampled input resolves to Path.home() / subfolder,
    confirming the fix works correctly.

COUNTEREXAMPLES DOCUMENTED (from running on unfixed code):
--------------------------------------------------------------------------
  FileNotFoundError: 源目录不存在：桌面
  FileNotFoundError: 源目录不存在：下载
  FileNotFoundError: 源目录不存在：文档
  FileNotFoundError: 源目录不存在：图片
  FileNotFoundError: 源目录不存在：视频
  FileNotFoundError: 源目录不存在：音乐
  FileNotFoundError: 源目录不存在：Desktop
  FileNotFoundError: 源目录不存在：Downloads
  FileNotFoundError: 源目录不存在：Documents
  FileNotFoundError: 源目录不存在：Pictures
  FileNotFoundError: 源目录不存在：Videos
  FileNotFoundError: 源目录不存在：Music
  FileNotFoundError: 源目录不存在：C:/Users/__foreign_user__/Downloads
    (or /home/__foreign_user__/Documents on Unix)
  FileNotFoundError: 源目录不存在：桌面\文档
    (LLM returned composite alias "桌面\文档" as target; not in ALIAS_MAP,
     passed through unchanged → Path("桌面\\文档").exists() == False)
--------------------------------------------------------------------------

Root cause confirmed:
  `run_file_organizer` calls `Path(source_dir).exists()` immediately with no
  alias resolution or user-path normalization. Alias strings like "桌面" and
  paths containing a foreign username are not valid filesystem paths on the
  current machine, so `.exists()` returns False and FileNotFoundError is raised.

Fix verified:
  `resolve_path` maps all alias keys and foreign-user paths to
  `Path.home() / <subfolder>`, so `run_file_organizer` receives a valid path.
  Rule 1b additionally handles composite alias paths like "桌面\\文档" by
  splitting on the path separator and mapping the first component via ALIAS_MAP.
"""
from __future__ import annotations

import platform
from pathlib import Path

from hypothesis import given, settings
from hypothesis.strategies import sampled_from

from utils.path_resolver import ALIAS_MAP, resolve_path

# ---------------------------------------------------------------------------
# Known alias keys — mirrors the ALIAS_MAP in utils/path_resolver.py
# ---------------------------------------------------------------------------
ALIAS_MAP_KEYS: list[str] = list(ALIAS_MAP.keys())

# ---------------------------------------------------------------------------
# Foreign-user path — a path whose parts[2] differs from Path.home().name
# ---------------------------------------------------------------------------
_FOREIGN_USER = "__foreign_user__"
assert _FOREIGN_USER != Path.home().name, (
    f"Foreign user '{_FOREIGN_USER}' must differ from current user '{Path.home().name}'"
)

if platform.system() == "Windows":
    FOREIGN_USER_PATH = f"C:\\Users\\{_FOREIGN_USER}\\Downloads"
else:
    FOREIGN_USER_PATH = f"/home/{_FOREIGN_USER}/Documents"

# ---------------------------------------------------------------------------
# Combined input space: all alias keys + the foreign-user path
#                       + composite alias paths (Rule 1b)
# ---------------------------------------------------------------------------

# Composite alias paths — first component is an alias, rest is a sub-path.
# These reproduce the real failure: LLM returned "桌面\文档" as target.
_COMPOSITE_ALIAS_INPUTS: list[str] = [
    "桌面\\文档",   # backslash — Windows path separator from LLM output
    "桌面/文档",    # forward slash variant
    "下载/installers",
]

_ALL_BUGGY_INPUTS: list[str] = ALIAS_MAP_KEYS + [FOREIGN_USER_PATH] + _COMPOSITE_ALIAS_INPUTS

# Expected subfolder for each buggy input
_EXPECTED_SUBFOLDER: dict[str, str] = {**ALIAS_MAP}
# Foreign-user path resolves to the subfolder after the username
if platform.system() == "Windows":
    _EXPECTED_SUBFOLDER[FOREIGN_USER_PATH] = "Downloads"
else:
    _EXPECTED_SUBFOLDER[FOREIGN_USER_PATH] = "Documents"
# Composite alias paths resolve to Path.home() / mapped_root / rest
# We store the full expected Path for these separately.
_COMPOSITE_EXPECTED: dict[str, Path] = {
    "桌面\\文档": Path.home() / "Desktop" / "文档",
    "桌面/文档": Path.home() / "Desktop" / "文档",
    "下载/installers": Path.home() / "Downloads" / "installers",
}


# ---------------------------------------------------------------------------
# Property-based test (updated for fix verification)
# ---------------------------------------------------------------------------


@settings(max_examples=len(_ALL_BUGGY_INPUTS))
@given(sampled_from(_ALL_BUGGY_INPUTS))
def test_buggy_input_resolves_to_home_based_path(buggy_input: str) -> None:
    """Assert resolve_path returns Path.home() / subfolder for each known buggy input.

    Property 1 (Fix Checking): For every known buggy input (Chinese/English
    folder alias, absolute path with a foreign username, or composite alias path
    like "桌面\\文档"), `resolve_path(input)` returns a Path.home()-based path.

    This test PASSES on fixed code, confirming the bug is resolved.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    result = resolve_path(buggy_input)

    # Composite alias inputs have a specific full expected path
    if buggy_input in _COMPOSITE_EXPECTED:
        expected = _COMPOSITE_EXPECTED[buggy_input]
    else:
        expected_subfolder = _EXPECTED_SUBFOLDER[buggy_input]
        expected = Path.home() / expected_subfolder

    assert result == expected, (
        f"resolve_path({buggy_input!r}) expected {expected}, got {result}"
    )
    assert result.is_absolute(), (
        f"resolve_path({buggy_input!r}) must return an absolute path, got {result}"
    )
