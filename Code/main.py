"""入口模块：启动 CV 桌面自动化智能体。

职责：
- 调用 config_loader 验证必需环境变量，缺失时输出错误并退出
- 创建 QueueManager，启动执行子进程（运行 DesktopAgent）
- 在主进程中启动 Gradio UI
- 捕获 KeyboardInterrupt，优雅关闭子进程
"""
from __future__ import annotations

import ctypes
import logging
import multiprocessing
import sys
from datetime import datetime, timezone
from multiprocessing import Process, Queue


def _set_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


_set_dpi_awareness()

from config.config_loader import ConfigMissingError, load_config
from ui.gradio_app import build_app
from ui.queue_manager import CommandMessage, QueueManager, StatusMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(tz=timezone.utc).isoformat()


def execution_worker(cmd_queue: Queue, status_queue: Queue, api_key: str) -> None:  # type: ignore[type-arg]
    """执行子进程入口：实例化 DesktopAgent，循环读取指令并执行。

    Args:
        cmd_queue: UI → 执行进程的指令队列。
        status_queue: 执行进程 → UI 的状态队列。
        api_key: DashScope API Key，由主进程验证后传入，避免子进程重复加载配置。
    """
    worker_logger = logging.getLogger(__name__ + ".worker")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from decision.agent import DesktopAgent
        from decision.llm_client import LLMClient
        from decision.tools import DesktopToolkit

        llm_client = LLMClient(api_key=api_key)
        toolkit = DesktopToolkit()
        agent = DesktopAgent(llm_client=llm_client, tools=toolkit.get_tools())
        worker_logger.info("execution_worker: DesktopAgent 初始化完成，等待指令…")
    except Exception as exc:  # noqa: BLE001
        worker_logger.error("execution_worker: 初始化失败: %s", exc, exc_info=True)
        status_queue.put(
            StatusMessage(status="error", message=f"执行进程初始化失败：{exc}", timestamp=_now_iso())
        )
        return

    # 用于在 record start/stop 之间保持 FlowRecorder 实例
    active_recorder = None

    while True:
        try:
            msg: CommandMessage = cmd_queue.get(timeout=1.0)
        except Exception:  # queue.Empty or other
            continue

        worker_logger.info(
            "execution_worker: 收到指令 type=%s payload=%s",
            msg.message_type,
            msg.payload,
        )

        if msg.message_type == "stop":
            worker_logger.info("execution_worker: 收到 stop 指令，退出")
            break

        elif msg.message_type == "execute":
            instruction: str = msg.payload.get("instruction", "")
            if not instruction:
                status_queue.put(
                    StatusMessage(status="error", message="指令内容为空", timestamp=_now_iso())
                )
                continue
            try:
                result = agent.run(instruction)
                status_queue.put(
                    StatusMessage(status="success", message=result, timestamp=_now_iso())
                )
            except Exception as exc:  # noqa: BLE001
                worker_logger.error("execution_worker: 执行指令失败: %s", exc, exc_info=True)
                status_queue.put(
                    StatusMessage(status="error", message=str(exc), timestamp=_now_iso())
                )

        elif msg.message_type == "record":
            action = msg.payload.get("action", "")
            active_recorder = _handle_record(
                action, msg.payload, status_queue, worker_logger, active_recorder
            )

        else:
            worker_logger.warning("execution_worker: 未知指令类型 %s", msg.message_type)


def _handle_record(
    action: str,
    payload: dict,
    status_queue: Queue,  # type: ignore[type-arg]
    worker_logger: logging.Logger,
    recorder: object | None,
) -> object | None:
    """处理录制相关指令，返回更新后的 recorder 实例（或 None）。

    Args:
        action: "start" 或 "stop"。
        payload: 指令附带参数。
        status_queue: 状态消息队列。
        worker_logger: 子进程日志记录器。
        recorder: 当前活跃的 FlowRecorder 实例，或 None。

    Returns:
        更新后的 FlowRecorder 实例，或 None（stop 后清空）。
    """
    from task.flow_recorder import FlowRecorder

    if action == "start":
        name = payload.get("name", "recording")
        try:
            new_recorder = FlowRecorder()
            new_recorder.start(name)
            worker_logger.info("_handle_record: 录制已开始，name=%s", name)
            status_queue.put(
                StatusMessage(status="running", message=f"录制已开始：{name}", timestamp=_now_iso())
            )
            return new_recorder
        except Exception as exc:  # noqa: BLE001
            worker_logger.error("_handle_record: 录制启动失败: %s", exc)
            status_queue.put(
                StatusMessage(status="error", message=f"录制启动失败：{exc}", timestamp=_now_iso())
            )
            return recorder  # 保持原状态

    elif action == "stop":
        if recorder is None:
            status_queue.put(
                StatusMessage(status="error", message="未找到活跃录制会话", timestamp=_now_iso())
            )
            return None
        try:
            path = recorder.stop()  # type: ignore[union-attr]
            worker_logger.info("_handle_record: 录制已保存至 %s", path)
            status_queue.put(
                StatusMessage(status="success", message=f"录制已保存：{path}", timestamp=_now_iso())
            )
            return None  # 清空 recorder
        except Exception as exc:  # noqa: BLE001
            worker_logger.error("_handle_record: 录制停止失败: %s", exc)
            status_queue.put(
                StatusMessage(status="error", message=f"录制停止失败：{exc}", timestamp=_now_iso())
            )
            return recorder  # 保持原状态

    else:
        worker_logger.warning("_handle_record: 未知 action=%s", action)
        return recorder


def main() -> None:
    """应用入口：验证配置、启动子进程、运行 Gradio UI。"""
    # 1. 验证必需环境变量（Requirements 13.4），并获取 api_key 供子进程使用
    try:
        config = load_config()
    except ConfigMissingError as exc:
        print(f"[ERROR] 配置错误：{exc}", file=sys.stderr)
        sys.exit(1)

    logger.info("main: 配置验证通过，启动应用…")

    # 2. 创建 QueueManager（Requirements 12.1）
    queue_manager = QueueManager()

    # 3. 启动执行子进程（daemon=True，主进程退出时自动终止）
    worker_process = Process(
        target=execution_worker,
        args=(queue_manager.cmd_queue, queue_manager.status_queue, config.dashscope_api_key),
        daemon=True,
        name="execution-worker",
    )
    worker_process.start()
    logger.info("main: 执行子进程已启动，pid=%d", worker_process.pid)

    # 4. 构建并启动 Gradio UI（主进程）
    app = build_app(queue_manager.cmd_queue, queue_manager.status_queue)
    try:
        app.launch()
    except KeyboardInterrupt:
        pass
    finally:
        # 5. 优雅关闭子进程
        logger.info("main: 正在关闭执行子进程…")
        if worker_process.is_alive():
            try:
                queue_manager.send_command("stop", {})
                worker_process.join(timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
            if worker_process.is_alive():
                worker_process.terminate()
                worker_process.join(timeout=3.0)
                logger.info("main: 执行子进程已强制终止")
            else:
                logger.info("main: 执行子进程已正常退出")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows 打包支持
    main()
