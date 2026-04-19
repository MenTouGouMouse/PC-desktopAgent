"""
gui_main1.py — Liquid Glass GUI 入口文件。

通过 `python gui_main1.py` 启动新版 Liquid Glass 风格桌面自动化助手。
与原版 main_gui.py 完全独立，共享同一套后端逻辑。

注意：此文件与 main_gui.py 功能相同，均使用 gui.app.PyWebViewApp。
"""
from __future__ import annotations

from gui.app import PyWebViewApp
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager
from vision.overlay_drawer import OverlayDrawer


def main() -> None:
    """初始化所有管理器并启动 Liquid Glass GUI 应用。"""
    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    overlay_drawer = OverlayDrawer()
    app = PyWebViewApp(progress_manager, queue_manager, overlay_drawer)
    app.run()


if __name__ == "__main__":
    main()
