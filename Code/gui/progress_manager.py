"""
gui.progress_manager — 全局任务进度状态管理模块。

提供线程安全的 ProgressManager，主窗口与悬浮球共享同一实例，
通过订阅/取消订阅机制将进度变更推送给所有注册的回调函数。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TaskProgress:
    """描述当前任务进度的数据类。"""

    percent: int = 0
    status_text: str = "就绪"
    task_name: str = ""
    is_running: bool = False


class ProgressManager:
    """线程安全的全局任务进度管理器。

    使用 threading.Lock 保护内部状态，支持多个订阅者回调，
    状态变更时通知所有已注册的回调函数。
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._state: TaskProgress = TaskProgress()
        self._subscribers: list[Callable[[TaskProgress], None]] = []
        logger.debug("ProgressManager initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        percent: int,
        status_text: str,
        task_name: str = "",
        is_running: bool = True,
    ) -> None:
        """更新进度状态并通知所有订阅者。

        percent 超出 [0, 100] 时自动 clamp，不抛出异常。
        锁仅在状态写入阶段持有，通知订阅者在锁外执行，避免死锁。
        """
        clamped = max(0, min(percent, 100))
        if clamped != percent:
            logger.debug("percent clamped from %d to %d", percent, clamped)

        with self._lock:
            self._state = TaskProgress(
                percent=clamped,
                status_text=status_text,
                task_name=task_name,
                is_running=is_running,
            )
            snapshot = TaskProgress(
                percent=self._state.percent,
                status_text=self._state.status_text,
                task_name=self._state.task_name,
                is_running=self._state.is_running,
            )
            subscribers_snapshot = list(self._subscribers)

        logger.debug(
            "Progress updated: percent=%d status_text=%r task_name=%r is_running=%s",
            clamped,
            status_text,
            task_name,
            is_running,
        )
        self._notify(subscribers_snapshot, snapshot)

    def reset(self) -> None:
        """将进度重置为初始就绪状态并通知所有订阅者。"""
        with self._lock:
            self._state = TaskProgress(percent=0, status_text="就绪", task_name="", is_running=False)
            snapshot = TaskProgress(
                percent=self._state.percent,
                status_text=self._state.status_text,
                task_name=self._state.task_name,
                is_running=self._state.is_running,
            )
            subscribers_snapshot = list(self._subscribers)

        logger.info("ProgressManager reset to 就绪")
        self._notify(subscribers_snapshot, snapshot)

    def get(self) -> TaskProgress:
        """返回当前进度状态的副本（线程安全）。"""
        with self._lock:
            return TaskProgress(
                percent=self._state.percent,
                status_text=self._state.status_text,
                task_name=self._state.task_name,
                is_running=self._state.is_running,
            )

    def subscribe(self, callback: Callable[[TaskProgress], None]) -> None:
        """注册进度变更回调函数。"""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
                logger.debug("Subscriber registered: %r", callback)

    def unsubscribe(self, callback: Callable[[TaskProgress], None]) -> None:
        """取消注册进度变更回调函数。"""
        with self._lock:
            try:
                self._subscribers.remove(callback)
                logger.debug("Subscriber unregistered: %r", callback)
            except ValueError:
                logger.warning("Attempted to unsubscribe unknown callback: %r", callback)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _notify(
        subscribers: list[Callable[[TaskProgress], None]],
        progress: TaskProgress,
    ) -> None:
        """调用所有订阅者回调，单个回调异常不影响其他订阅者。"""
        for callback in subscribers:
            try:
                callback(progress)
            except Exception:
                logger.exception("Error in progress subscriber callback %r", callback)
