"""
main_gui1.py — Liquid Glass GUI 启动入口（Vue 3 + TypeScript 版本）

与 main_gui.py 完全独立，不修改任何原有代码。
前端源码位于 gui_new/，构建产物位于 gui_new/dist/。

启动方式：
    python main_gui1.py

构建前端（首次或修改后）：
    cd gui_new
    npm install      # 首次需要
    npm run build
    cd ..
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

import webview

from gui.app import PyWebViewApp, PythonAPI
from gui.progress_manager import ProgressManager
from ui.queue_manager import QueueManager
from vision.overlay_drawer import OverlayDrawer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_DIST      = _ROOT / "gui_new" / "dist" / "index.html"
_FLOAT_HTML = _ROOT / "gui_new" / "dist" / "floating.html"
_FLOAT_SRC  = _ROOT / "frontend" / "floating.html"


class LiquidGlassAPI(PythonAPI):
    """PythonAPI subclass that fixes the floating ball URL for gui_new."""

    def minimize_to_ball(self) -> None:
        """Override to use dist-relative path for floating.html (served by http_server)."""
        if self._main_win is not None:
            self._main_win.hide()

        if self._ball_win is None:
            # Use relative path — http_server roots at gui_new/dist/
            ball_url = "floating.html"
            logger.info("minimize_to_ball: creating ball window url=%s", ball_url)
            self._ball_win = webview.create_window(
                title="",
                url=ball_url,
                js_api=self,
                width=80,
                height=80,
                resizable=False,
                frameless=True,
                on_top=True,
                transparent=True,
                easy_drag=False,
            )
            self._ball_is_shown = True
        else:
            try:
                self._ball_win.show()
            except Exception as e:
                logger.warning("minimize_to_ball show() failed: %s", e)
            self._ball_is_shown = True

        logger.debug("minimize_to_ball: main hidden, ball shown")


class LiquidGlassApp(PyWebViewApp):
    """PyWebViewApp subclass that loads gui_new/dist and uses LiquidGlassAPI."""

    def __init__(
        self,
        progress_manager: ProgressManager,
        queue_manager: QueueManager,
        overlay_drawer: OverlayDrawer,
    ) -> None:
        # Call grandparent init logic manually to swap in LiquidGlassAPI
        self._progress_manager = progress_manager
        self._queue_manager = queue_manager
        self._overlay_drawer = overlay_drawer
        self._main_win = None
        self._ball_win = None
        self.api = LiquidGlassAPI(progress_manager, queue_manager)
        self.api._app = self

    def run(self) -> None:
        api = self.api

        def _on_closed() -> None:
            # Stop overlay drawer first to prevent evaluate_js on disposed WebView2
            self._overlay_drawer.stop()
            if self._ball_win is not None:
                try:
                    self._ball_win.hide()
                except Exception:
                    pass
            sys.exit(0)

        self._main_win = webview.create_window(
            title="AutoAgent Desktop — Liquid Glass",
            url=str(_DIST),
            js_api=api,
            width=1260,
            height=800,
            min_size=(900, 560),
            resizable=True,
            frameless=False,
        )
        self._main_win.events.closed += _on_closed
        api.set_windows(self._main_win, None)
        self._progress_manager.subscribe(self.push_progress)
        self._overlay_drawer.start(self.push_frame)
        webview.start(self._on_webview_started, http_server=True)


def main() -> None:
    if not _DIST.exists():
        print(
            "[main_gui1] 前端尚未构建，请先执行：\n"
            "    cd gui_new\n"
            "    npm install\n"
            "    npm run build\n"
            "    cd ..\n"
            "然后再运行 python main_gui1.py"
        )
        sys.exit(1)

    # 把 floating.html 复制到 dist/ 旁边，确保 http_server 能访问到
    import shutil
    if _FLOAT_SRC.exists() and not _FLOAT_HTML.exists():
        shutil.copy2(_FLOAT_SRC, _FLOAT_HTML)
        logger.info("Copied floating.html to %s", _FLOAT_HTML)

    progress_manager = ProgressManager()
    queue_manager = QueueManager()
    overlay_drawer = OverlayDrawer()

    app = LiquidGlassApp(progress_manager, queue_manager, overlay_drawer)
    app.run()


if __name__ == "__main__":
    main()
