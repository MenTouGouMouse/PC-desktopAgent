"""
保留性属性测试 — file-organizer-fix

**Validates: Requirements 3.1, 3.5**

此测试验证非 bug 条件的路径行为在修复前后保持不变（不应回归）。
在未修复代码上应 PASS，修复后也应 PASS。

EXPECTED OUTCOME: 测试 PASS（确认基线行为，修复后不应回归）

保留性测试覆盖：
  - Rule 1：中文别名（"桌面"）解析为 Path.home() / "Desktop"
  - Rule 1b：复合别名路径（"桌面\\文档"）解析为 Path.home() / "Desktop" / "文档"
  - Rule 3：有效绝对路径（"D:\\Projects\\foo"）原样直通
  - 当前用户路径不重映射（Path.home() / "Downloads" 原样返回）
  - 属性测试：对任意非 bug 条件字符串，resolve_path 行为与预期一致
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis.strategies import text

from utils.path_resolver import resolve_path


# ---------------------------------------------------------------------------
# isBugCondition 定义（用于属性测试过滤）
# ---------------------------------------------------------------------------

def is_bug_condition(s: str) -> bool:
    """判断字符串是否触发已知 bug 条件。

    情况 A：缺盘符 Windows 路径（以 \\ 或 / 开头，但 is_absolute() 为 False，
            且结构为 \\Users\\<user>\\... 或 /home/<user>/...）
    情况 B：文件夹名含"文件夹"后缀（如"文档文件夹"）
    """
    p = Path(s)
    # 情况 A：缺盘符 Windows 路径
    if (
        (s.startswith("\\") or s.startswith("/"))
        and not p.is_absolute()
        and len(p.parts) >= 3
        and p.parts[0] in ("\\", "/")
        and p.parts[1] in ("Users", "home")
    ):
        return True
    # 情况 B：文件夹名含"文件夹"后缀
    if s.endswith("文件夹") and len(s) > 3:
        return True
    return False


# ---------------------------------------------------------------------------
# Rule 1：中文别名解析（保留性）
# ---------------------------------------------------------------------------


def test_preservation_rule1_chinese_alias_desktop() -> None:
    """Rule 1 保留：resolve_path("桌面") 应返回 Path.home() / "Desktop"。

    **Validates: Requirements 3.5**
    """
    result = resolve_path("桌面")
    expected = Path.home() / "Desktop"
    assert result == expected, (
        f'resolve_path("桌面") 应返回 {expected}，实际返回 {result}'
    )


def test_preservation_rule1_chinese_alias_downloads() -> None:
    """Rule 1 保留：resolve_path("下载") 应返回 Path.home() / "Downloads"。

    **Validates: Requirements 3.5**
    """
    result = resolve_path("下载")
    expected = Path.home() / "Downloads"
    assert result == expected, (
        f'resolve_path("下载") 应返回 {expected}，实际返回 {result}'
    )


# ---------------------------------------------------------------------------
# Rule 1b：复合别名路径解析（保留性）
# ---------------------------------------------------------------------------


def test_preservation_rule1b_composite_alias_path() -> None:
    """Rule 1b 保留：resolve_path("桌面\\文档") 应返回 Path.home() / "Desktop" / "文档"。

    **Validates: Requirements 3.5**
    """
    result = resolve_path("桌面\\文档")
    expected = Path.home() / "Desktop" / "文档"
    assert result == expected, (
        f'resolve_path("桌面\\\\文档") 应返回 {expected}，实际返回 {result}'
    )


# ---------------------------------------------------------------------------
# Rule 3：有效绝对路径直通（保留性）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 盘符路径仅在 Windows 上有效")
def test_preservation_rule3_absolute_path_passthrough_windows() -> None:
    """Rule 3 保留（Windows）：resolve_path("D:\\Projects\\foo") 应原样返回。

    **Validates: Requirements 3.1**
    """
    raw = r"D:\Projects\foo"
    result = resolve_path(raw)
    expected = Path(raw)
    assert result == expected, (
        f"resolve_path({raw!r}) 应原样返回 {expected}，实际返回 {result}"
    )


def test_preservation_rule3_absolute_path_passthrough_unix() -> None:
    """Rule 3 保留（Unix）：resolve_path("/opt/myapp/data") 应原样返回。

    **Validates: Requirements 3.1**
    """
    raw = "/opt/myapp/data"
    result = resolve_path(raw)
    expected = Path(raw)
    assert result == expected, (
        f"resolve_path({raw!r}) 应原样返回 {expected}，实际返回 {result}"
    )


# ---------------------------------------------------------------------------
# 当前用户路径不重映射（保留性）
# ---------------------------------------------------------------------------


def test_preservation_current_user_path_not_remapped() -> None:
    """当前用户路径不重映射：resolve_path(str(Path.home() / "Downloads")) 应原样返回。

    Rule 2 的触发条件要求 parts[2] != Path.home().name，
    当前用户路径 parts[2] == Path.home().name，因此不触发重映射。

    **Validates: Requirements 3.1**
    """
    raw = str(Path.home() / "Downloads")
    result = resolve_path(raw)
    expected = Path(raw)
    assert result == expected, (
        f"resolve_path({raw!r}) 应原样返回 {expected}，实际返回 {result}"
    )


def test_preservation_current_user_desktop_not_remapped() -> None:
    """当前用户桌面路径不重映射：resolve_path(str(Path.home() / "Desktop")) 应原样返回。

    **Validates: Requirements 3.1**
    """
    raw = str(Path.home() / "Desktop")
    result = resolve_path(raw)
    expected = Path(raw)
    assert result == expected, (
        f"resolve_path({raw!r}) 应原样返回 {expected}，实际返回 {result}"
    )


# ---------------------------------------------------------------------------
# 属性测试：非 bug 条件字符串，resolve_path 行为与预期一致
# ---------------------------------------------------------------------------


@settings(max_examples=50)
@given(text())
def test_property_preservation_non_bug_condition(s: str) -> None:
    """属性测试：对任意非 bug 条件字符串，resolve_path 不抛出异常且结果稳定。

    过滤掉 is_bug_condition(s) 为 True 的字符串，验证：
    1. resolve_path(s) 不抛出异常
    2. 对同一输入调用两次结果相同（幂等性）

    **Validates: Requirements 3.1, 3.5**
    """
    if is_bug_condition(s):
        return  # 跳过 bug 条件输入，仅测试非 bug 条件

    # 不应抛出异常
    result = resolve_path(s)

    # 幂等性：对同一输入调用两次结果相同
    result2 = resolve_path(s)
    assert result == result2, (
        f"resolve_path({s!r}) 两次调用结果不一致：{result} vs {result2}"
    )

    # 结果应为 Path 类型
    assert isinstance(result, Path), (
        f"resolve_path({s!r}) 应返回 Path 类型，实际返回 {type(result)}"
    )
