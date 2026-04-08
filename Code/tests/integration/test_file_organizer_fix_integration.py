"""
集成测试：file-organizer-fix — 缺盘符路径与"文件夹"后缀修复验证。

**Validates: Requirements 2.1, 2.2, 2.4, 2.5**

Tests:
1. ChatAgent._run_file_organizer 正确解析缺盘符路径 + "文件夹"后缀
2. run_file_organizer 在临时目录中正确匹配 .pdf 文件并移动到目标子目录
"""
from __future__ import annotations

import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gui.chat_agent import ChatAgent
from gui.progress_manager import ProgressManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def chat_agent() -> ChatAgent:
    llm_client = MagicMock()
    pm = ProgressManager()
    stop_event = threading.Event()
    push_fn = MagicMock()
    return ChatAgent(
        llm_client=llm_client,
        progress_manager=pm,
        stop_event=stop_event,
        push_fn=push_fn,
    )


# ---------------------------------------------------------------------------
# Test 1: 缺盘符路径 + "文件夹"后缀组合修复
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_chat_agent_resolves_missing_drive_and_folder_suffix(
    chat_agent: ChatAgent,
) -> None:
    r"""_run_file_organizer 传入缺盘符路径 + "文件夹"后缀时，正确解析路径。

    source=r'\Users\32836\Desktop' → Path.home() / 'Desktop'
    target=r'\Users\32836\Desktop\文档文件夹' → Path.home() / 'Desktop' / '文档'

    **Validates: Requirements 2.1, 2.2**
    """
    expected_source = str(Path.home() / "Desktop")
    expected_target = str(Path.home() / "Desktop" / "文档")

    with patch("automation.file_organizer.run_file_organizer") as mock_run:
        mock_run.return_value = None
        chat_agent._run_file_organizer({
            "source": r"\Users\32836\Desktop",
            "target": r"\Users\32836\Desktop\文档文件夹",
        })

    mock_run.assert_called_once()
    call_args = mock_run.call_args
    actual_source = call_args.args[0]
    actual_target = call_args.args[1]

    assert actual_source == expected_source, (
        f"Expected source={expected_source!r}, got {actual_source!r}"
    )
    assert actual_target == expected_target, (
        f"Expected target={expected_target!r}, got {actual_target!r}"
    )


@pytest.mark.integration
def test_chat_agent_resolves_folder_suffix_only(
    chat_agent: ChatAgent,
) -> None:
    """target 仅含"文件夹"后缀（无缺盘符），也应正确去除后缀。

    target='桌面\\文档文件夹' → Path.home() / 'Desktop' / '文档'

    **Validates: Requirements 2.2**
    """
    expected_target = str(Path.home() / "Desktop" / "文档")

    with patch("automation.file_organizer.run_file_organizer") as mock_run:
        mock_run.return_value = None
        chat_agent._run_file_organizer({
            "source": "桌面",
            "target": "桌面\\文档文件夹",
        })

    mock_run.assert_called_once()
    actual_target = mock_run.call_args.args[1]
    assert actual_target == expected_target, (
        f"Expected target={expected_target!r}, got {actual_target!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: run_file_organizer 正确匹配 .pdf 文件并移动到目标子目录
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_file_organizer_moves_pdf_to_documents_subdir() -> None:
    """run_file_organizer 在临时目录中正确匹配 .pdf 文件并移动到 Documents 子目录。

    **Validates: Requirements 2.4, 2.5**
    """
    from automation.file_organizer import run_file_organizer

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        target = Path(tmp) / "target"

        # 创建 PDF 文件（大小写不敏感）
        (source / "report.pdf").write_text("pdf content")
        (source / "INVOICE.PDF").write_text("pdf content upper")
        # 非 PDF 文件
        (source / "photo.jpg").write_text("img content")

        stop_event = threading.Event()
        run_file_organizer(str(source), str(target), lambda s, p: None, stop_event)

        # PDF 文件应移动到 Documents/PDF 子目录
        assert (target / "Documents" / "PDF" / "report.pdf").exists(), (
            "report.pdf 应被移动到 target/Documents/PDF/"
        )
        assert (target / "Documents" / "PDF" / "INVOICE.PDF").exists(), (
            "INVOICE.PDF 应被移动到 target/Documents/PDF/"
        )
        # 非 PDF 文件应移动到对应子目录
        assert (target / "Images" / "JPG" / "photo.jpg").exists(), (
            "photo.jpg 应被移动到 target/Images/JPG/"
        )
        # 源目录中 PDF 文件不再存在
        assert not (source / "report.pdf").exists()
        assert not (source / "INVOICE.PDF").exists()


@pytest.mark.integration
def test_run_file_organizer_creates_target_dir_if_not_exists() -> None:
    """目标目录不存在时，run_file_organizer 应自动创建。

    **Validates: Requirements 2.5**
    """
    from automation.file_organizer import run_file_organizer

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        target = Path(tmp) / "nonexistent_target"  # 不预先创建

        (source / "test.pdf").write_text("pdf")

        stop_event = threading.Event()
        run_file_organizer(str(source), str(target), lambda s, p: None, stop_event)

        assert target.exists(), "目标目录应被自动创建"
        assert (target / "Documents" / "PDF" / "test.pdf").exists()


@pytest.mark.integration
def test_run_file_organizer_uses_existing_target_dir() -> None:
    """目标目录已存在时，run_file_organizer 直接使用，不重复创建。

    **Validates: Requirements 2.6**
    """
    from automation.file_organizer import run_file_organizer

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        target = Path(tmp) / "existing_target"
        target.mkdir()  # 预先创建
        # 目标目录中已有文件
        (target / "existing_file.txt").write_text("existing")

        (source / "new.pdf").write_text("pdf")

        stop_event = threading.Event()
        run_file_organizer(str(source), str(target), lambda s, p: None, stop_event)

        # 已有文件不受影响
        assert (target / "existing_file.txt").exists()
        # 新文件正确移动
        assert (target / "Documents" / "PDF" / "new.pdf").exists()
