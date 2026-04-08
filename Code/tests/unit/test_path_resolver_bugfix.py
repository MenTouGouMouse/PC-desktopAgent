"""
Bug Condition 探索性测试 — file-organizer-fix

**Validates: Requirements 1.2, 1.3, 1.5**

此测试编码了期望行为，在未修复代码上预期 FAIL（失败即证明 bug 存在），
修复后应 PASS。

EXPECTED OUTCOME on UNFIXED code:
  - 测试 FAIL — 证明 bug 存在

Bug 条件：
  情况 A：缺盘符 Windows 路径（如 \\Users\\32836\\Desktop），
          Rule 2 要求 is_absolute() 为 True，但缺盘符路径返回 False，
          导致 Rule 2 不触发，路径原样返回。
  情况 B：strip_folder_suffix 函数不存在，调用会抛出 ImportError/AttributeError。
  情况 A+B：两者叠加，路径既无法正确解析，末段也无法去除"文件夹"后缀。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis.strategies import sampled_from

from utils.path_resolver import resolve_path

# ---------------------------------------------------------------------------
# 情况 A：缺盘符 Windows 路径解析
# ---------------------------------------------------------------------------


def test_case_a_missing_drive_letter_desktop() -> None:
    """情况 A：resolve_path(r"\\Users\\32836\\Desktop") 应返回 Path.home() / "Desktop"。

    未修复代码中 Rule 2 不触发（is_absolute() 为 False），路径原样返回，
    导致此断言失败——证明 bug 存在。

    **Validates: Requirements 1.2, 1.5**
    """
    raw = r"\Users\32836\Desktop"
    result = resolve_path(raw)
    expected = Path.home() / "Desktop"
    assert result == expected, (
        f"resolve_path({raw!r}) 应返回 {expected}，实际返回 {result}。"
        f"（未修复代码原样返回 Path({raw!r})，Rule 2 未触发）"
    )


# ---------------------------------------------------------------------------
# 情况 B：strip_folder_suffix 函数存在性及正确性
# ---------------------------------------------------------------------------


def test_case_b_strip_folder_suffix_exists() -> None:
    """情况 B：strip_folder_suffix("文档文件夹") 应返回 "文档"。

    未修复代码中 strip_folder_suffix 函数不存在，导致 ImportError，
    证明 bug 存在。

    **Validates: Requirements 1.3**
    """
    try:
        from utils.path_resolver import strip_folder_suffix  # type: ignore[attr-defined]
    except ImportError as exc:
        pytest.fail(
            f"strip_folder_suffix 函数不存在（ImportError: {exc}）——证明 bug 存在"
        )

    result = strip_folder_suffix("文档文件夹")
    assert result == "文档", (
        f"strip_folder_suffix('文档文件夹') 应返回 '文档'，实际返回 {result!r}"
    )


def test_case_b_strip_folder_suffix_returns_correct_value() -> None:
    """情况 B 补充：验证 strip_folder_suffix 对多种输入的正确性。

    **Validates: Requirements 1.3**
    """
    try:
        from utils.path_resolver import strip_folder_suffix  # type: ignore[attr-defined]
    except ImportError as exc:
        pytest.fail(f"strip_folder_suffix 函数不存在（ImportError: {exc}）")

    assert strip_folder_suffix("文档文件夹") == "文档"
    assert strip_folder_suffix("下载文件夹") == "下载"
    # 长度恰好为 3 的"文件夹"不去除
    assert strip_folder_suffix("文件夹") == "文件夹"
    # 无后缀原样返回
    assert strip_folder_suffix("文档") == "文档"


# ---------------------------------------------------------------------------
# 情况 A+B 叠加：缺盘符路径 + 文件夹后缀
# ---------------------------------------------------------------------------


def test_case_ab_combined_missing_drive_and_folder_suffix() -> None:
    """情况 A+B 叠加：resolve_path + strip_folder_suffix 组合处理。

    resolve_path(r"\\Users\\32836\\Desktop\\文档文件夹") 应返回
    Path.home() / "Desktop" / "文档文件夹"（缺盘符路径不解析末段），
    再经 strip_folder_suffix 处理末段后得 Path.home() / "Desktop" / "文档"。

    未修复代码中：
      1. resolve_path 不触发 Rule 2，原样返回 Path(r"\\Users\\32836\\Desktop\\文档文件夹")
      2. strip_folder_suffix 不存在

    **Validates: Requirements 1.2, 1.3, 1.5**
    """
    raw = r"\Users\32836\Desktop\文档文件夹"

    # Step 1: resolve_path 应将缺盘符路径映射到 Path.home() 下
    resolved = resolve_path(raw)
    expected_resolved = Path.home() / "Desktop" / "文档文件夹"
    assert resolved == expected_resolved, (
        f"resolve_path({raw!r}) 应返回 {expected_resolved}，实际返回 {resolved}"
    )

    # Step 2: strip_folder_suffix 处理末段
    try:
        from utils.path_resolver import strip_folder_suffix  # type: ignore[attr-defined]
    except ImportError as exc:
        pytest.fail(f"strip_folder_suffix 函数不存在（ImportError: {exc}）")

    cleaned_name = strip_folder_suffix(resolved.name)
    final_path = resolved.parent / cleaned_name
    expected_final = Path.home() / "Desktop" / "文档"
    assert final_path == expected_final, (
        f"组合处理后应得 {expected_final}，实际得 {final_path}"
    )


# ---------------------------------------------------------------------------
# 属性测试：对子路径做属性测试（@given sampled_from）
# ---------------------------------------------------------------------------


@settings(max_examples=3)
@given(sampled_from(["Desktop", "Downloads", "Documents"]))
def test_property_missing_drive_resolves_to_home_subfolder(subfolder: str) -> None:
    """属性测试：对任意常见子路径，缺盘符路径应解析到 Path.home() / subfolder。

    使用 @given(sampled_from(...)) 对 Desktop/Downloads/Documents 三个子路径
    验证 Rule 2b 的正确性。未修复代码中此断言失败——证明 bug 存在。

    **Validates: Requirements 1.2, 1.5**
    """
    raw = rf"\Users\32836\{subfolder}"
    result = resolve_path(raw)
    expected = Path.home() / subfolder
    assert result == expected, (
        f"resolve_path({raw!r}) 应返回 {expected}，实际返回 {result}。"
        f"（未修复代码 Rule 2 不触发，原样返回 Path({raw!r})）"
    )
