"""
集成测试：automation.file_organizer 真实文件系统集成。
"""
from __future__ import annotations

import threading

import pytest

from automation.file_organizer import run_file_organizer


@pytest.mark.integration
class TestFileOrganizerIntegration:
    def test_files_moved_to_correct_subdirectories(self, tmp_path):
        """验证文件实际被移动到正确子目录。"""
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        # Create test files
        (source / "photo.jpg").write_text("img")
        (source / "video.mp4").write_text("vid")
        (source / "doc.pdf").write_text("doc")
        (source / "music.mp3").write_text("aud")
        (source / "archive.zip").write_text("arc")
        (source / "script.py").write_text("code")

        stop_event = threading.Event()
        run_file_organizer(source, target, lambda s, p: None, stop_event)

        assert (target / "Images" / "JPG" / "photo.jpg").exists()
        assert (target / "Videos" / "MP4" / "video.mp4").exists()
        assert (target / "Documents" / "PDF" / "doc.pdf").exists()
        assert (target / "Audio" / "MP3" / "music.mp3").exists()
        assert (target / "Archives" / "ZIP" / "archive.zip").exists()
        assert (target / "Code" / "Python" / "script.py").exists()

    def test_progress_callback_monotonically_increases_to_100(self, tmp_path):
        """验证 progress_callback 被调用且 percent 单调递增至 100。"""
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        for i in range(5):
            (source / f"file{i}.jpg").write_text("data")

        percents: list[int] = []
        stop_event = threading.Event()

        run_file_organizer(source, target, lambda s, p: percents.append(p), stop_event)

        assert len(percents) == 5
        assert percents == sorted(percents), "Percents should be monotonically increasing"
        assert percents[-1] == 100

    def test_source_files_no_longer_in_source_after_move(self, tmp_path):
        """验证文件移动后源目录中不再存在。"""
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        (source / "test.jpg").write_text("data")

        stop_event = threading.Event()
        run_file_organizer(source, target, lambda s, p: None, stop_event)

        assert not (source / "test.jpg").exists()
        assert (target / "Images" / "JPG" / "test.jpg").exists()
