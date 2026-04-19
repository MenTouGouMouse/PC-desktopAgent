"""main_gui.py — Desktop GUI client entry point.

Replaces the Gradio launch path in main.py with a PyWebView-based desktop
GUI client. Wires together config loading, QueueManager, ProgressManager,
OverlayDrawer, an execution worker subprocess, and PyWebViewApp.

Usage:
    python main_gui.py

Validates: Requirements 1.1, 12.1, 12.4
"""
from __future__ import annotations

import ctypes
import logging
import multiprocessing
import sys
from multiprocessing import Process, Queue


def _set_dpi_awareness() -> None:
    """设置进程为 Per-Monitor DPI Aware v2，统一物理像素坐标系。

    必须在创建任何窗口或调用 Win32 坐标 API 之前调用。
    设置后 mss 截图坐标、SetCursorPos、GetCursorPos 均使用物理像素，消除坐标系矛盾。
    """
    if sys.platform != "win32":
        return
    try:
        # Per-Monitor Aware v2 (Windows 10 1703+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            # 回退: System Aware
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


# 必须在模块导入阶段尽早调用，早于任何可能创建窗口的 import
_set_dpi_awareness()

from config.config_loader import ConfigMissingError, load_config
from gui.app import PyWebViewApp
from gui.progress_manager import ProgressManager
from ui.queue_manager import CommandMessage, QueueManager, StatusMessage
from vision.overlay_drawer import OverlayDrawer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _gui_execution_worker(
    cmd_queue: Queue[CommandMessage],
    status_queue: Queue[StatusMessage],
) -> None:
    """Execution worker subprocess: reads commands from cmd_queue and processes them.

    This is a simplified placeholder that handles the stop command and drains
    the queue. The full agent worker from main.py can be substituted here when
    the agent dependencies are available.

    Args:
        cmd_queue: Command queue from the UI process.
        status_queue: Status queue back to the UI process.
    """
    import queue as _queue
    from datetime import datetime, timezone

    worker_logger = logging.getLogger(__name__ + ".worker")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker_logger.info("GUI execution worker started, waiting for commands…")

    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    while True:
        try:
            msg: CommandMessage = cmd_queue.get(timeout=1.0)
        except _queue.Empty:
            continue
        except Exception as exc:  # noqa: BLE001
            worker_logger.error("Worker queue read error: %s", exc)
            continue

        worker_logger.info(
            "Worker received command: type=%s payload=%s",
            msg.message_type,
            msg.payload,
        )

        if msg.message_type == "stop":
            worker_logger.info("Worker received stop command, exiting.")
            break
        elif msg.message_type == "execute":
            instruction: str = msg.payload.get("instruction", "")
            worker_logger.info("Worker execute: %s", instruction)
            status_queue.put(
                StatusMessage(
                    status="running",
                    message=f"执行中：{instruction}",
                    timestamp=_now_iso(),
                )
            )
        else:
            worker_logger.warning("Worker unknown command type: %s", msg.message_type)


def main() -> None:
    """Application entry point: validate config, start worker, run GUI."""
    # 1. Load and validate config — exit with error if required env vars are missing
    try:
        config = load_config()
    except ConfigMissingError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("Configuration validated successfully.")

    # 2. Create shared managers
    queue_manager = QueueManager()
    progress_manager = ProgressManager()
    overlay_drawer = OverlayDrawer(fps=8)

    # 3. Start execution worker subprocess
    worker = Process(
        target=_gui_execution_worker,
        args=(queue_manager.cmd_queue, queue_manager.status_queue),
        daemon=True,
        name="gui-execution-worker",
    )
    worker.start()
    logger.info("Execution worker started, pid=%d", worker.pid)

    # 4. Create PyWebViewApp and wire subscriptions
    app = PyWebViewApp(progress_manager, queue_manager, overlay_drawer, dashscope_api_key=config.dashscope_api_key)

    # 5. Run the PyWebView event loop (blocks until window is closed)
    # Note: app.run() internally subscribes push_progress and starts overlay_drawer
    logger.info("Starting PyWebView application…")
    app.run()

    # 6. Cleanup on exit (after app.run() returns)
    logger.info("PyWebView application exited, cleaning up…")

    overlay_drawer.stop()
    logger.info("OverlayDrawer stopped.")

    try:
        queue_manager.send_command("stop", {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send stop command to worker: %s", exc)

    worker.join(timeout=5.0)
    if worker.is_alive():
        logger.warning("Worker did not exit within timeout, terminating.")
        worker.terminate()
        worker.join(timeout=3.0)
    else:
        logger.info("Worker exited cleanly.")

    logger.info("main_gui.py shutdown complete.")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows packaging support
    main()
