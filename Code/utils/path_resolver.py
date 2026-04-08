"""
utils.path_resolver — 路径别名解析与外部用户路径归一化工具。

提供 resolve_path 函数，将中英文文件夹别名和硬编码的外部用户路径
映射到当前用户的 Path.home() 下对应子目录，避免 FileNotFoundError。
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Alias map: Chinese and English folder names → home subfolder name
# ---------------------------------------------------------------------------
ALIAS_MAP: dict[str, str] = {
    # Chinese aliases
    "桌面": "Desktop",
    "下载": "Downloads",
    "文档": "Documents",
    "图片": "Pictures",
    "视频": "Videos",
    "音乐": "Music",
    # English aliases
    "Desktop": "Desktop",
    "Downloads": "Downloads",
    "Documents": "Documents",
    "Pictures": "Pictures",
    "Videos": "Videos",
    "Music": "Music",
}


def resolve_path(raw: str | Path) -> Path:
    """Resolve a raw path string or Path to a valid filesystem Path.

    Resolution rules (applied in order):
    1. If str(raw) is a key in ALIAS_MAP, return Path.home() / ALIAS_MAP[str(raw)].
    2. If the path is absolute, has >= 3 parts, parts[1] is "Users" or "home"
       (Windows/Unix home root), and parts[2] differs from the current user's
       home directory name, re-root the sub-path after the username under
       Path.home().
    3. Otherwise return Path(raw) unchanged.

    Args:
        raw: A path string or Path object to resolve.

    Returns:
        A Path object pointing to the resolved location.
    """
    s = str(raw)

    # Rule 1: alias map lookup (exact match, case-sensitive)
    if s in ALIAS_MAP:
        return Path.home() / ALIAS_MAP[s]

    p = Path(s)

    # Rule 1b: composite alias path — first component is an alias, rest is a sub-path
    # e.g. "桌面\文档" → Path.home() / "Desktop" / "文档"
    # Works for both backslash (Windows) and forward-slash separators.
    if len(p.parts) >= 2 and p.parts[0] in ALIAS_MAP:
        return Path.home() / ALIAS_MAP[p.parts[0]] / Path(*p.parts[1:])

    # Rule 2b: Windows path missing drive letter, e.g. \Users\32836\Desktop
    # Path('\Users\32836\Desktop').is_absolute() == False on Windows,
    # but parts == ('\\', 'Users', '32836', 'Desktop')
    # Note: we remap regardless of whether the username matches, because a
    # path without a drive letter is always invalid on Windows and must be fixed.
    if (
        not p.is_absolute()
        and len(p.parts) >= 3
        and p.parts[0] == "\\"
        and p.parts[1] in ("Users", "home")
    ):
        sub_parts = p.parts[3:]
        if sub_parts:
            return Path.home().joinpath(*sub_parts)
        return Path.home()

    # Rule 2: foreign-user absolute path normalization
    if (
        p.is_absolute()
        and len(p.parts) >= 3
        and p.parts[1] in ("Users", "home")
        and p.parts[2] != Path.home().name
    ):
        # Extract the sub-path after the username component and re-root under home
        sub_parts = p.parts[3:]  # everything after /Users/<username>/
        if sub_parts:
            return Path.home().joinpath(*sub_parts)
        return Path.home()

    # Rule 3: pass through unchanged
    return p


def strip_folder_suffix(name: str) -> str:
    """去除中文文件夹名中的'文件夹'后缀。

    例如："文档文件夹" → "文档"，"文档" → "文档"（不变）。
    边界情况："文件夹"（长度恰好为 3）原样返回，不去除。

    Args:
        name: 待处理的文件夹名称字符串。

    Returns:
        去除"文件夹"后缀后的字符串；若不满足条件则原样返回。
    """
    if name.endswith("文件夹") and len(name) > 3:
        return name[:-3]
    return name
