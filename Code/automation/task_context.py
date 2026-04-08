"""automation/task_context.py — 任务上下文单例，存储当前活动任务的目标描述。

职责：
- 提供线程安全的全局任务目标存储（TaskContext 单例）
- 提供灵活的目标匹配函数（支持通配符、部分匹配、正则、中英文）
- 提供置信度提升函数，对匹配目标强制设置高置信度

设计原则：
- 不修改检测逻辑，只在检测结果写入缓存前做后处理
- 匹配逻辑与绘制逻辑完全解耦
- 任务完成或新任务开始时自动清除旧目标
"""
from __future__ import annotations

import fnmatch
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Literal

from automation.vision_box_drawer import BoundingBoxDict

logger = logging.getLogger(__name__)

# 任务匹配成功时强制设置的置信度
TASK_MATCH_CONFIDENCE: float = 0.95


@dataclass
class TaskTarget:
    """描述当前活动任务的目标信息。

    Attributes:
        intent: 任务类型，"file_organize" | "software_install"
        keywords: 匹配关键词列表（扩展名如 [".pdf", ".jpg"]，或按钮文字如 ["下一步", "安装"]）
        description: 人类可读的目标描述，用于日志
    """

    intent: Literal["file_organize", "software_install"]
    keywords: list[str]
    description: str = ""

    def __post_init__(self) -> None:
        # 统一转小写，方便大小写不敏感匹配
        self.keywords = [k.lower().strip() for k in self.keywords if k.strip()]


class TaskContext:
    """线程安全的全局任务上下文单例。

    通过 TaskContext.get_instance() 获取单例，在任务开始时调用 set_target()，
    任务结束时调用 clear_target()。
    """

    _instance: TaskContext | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._target: TaskTarget | None = None
        self._lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TaskContext:
        """获取全局单例（双重检查锁定）。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_target(self, target: TaskTarget) -> None:
        """设置当前任务目标，线程安全。

        Args:
            target: 新的任务目标描述。
        """
        with self._lock:
            self._target = target
        logger.info(
            "TaskContext: 设置任务目标 intent=%s keywords=%s desc=%r",
            target.intent, target.keywords, target.description,
        )

    def clear_target(self) -> None:
        """清除当前任务目标（任务完成或新任务开始时调用）。"""
        with self._lock:
            old = self._target
            self._target = None
        if old is not None:
            logger.info("TaskContext: 清除任务目标 (was: %r)", old.description)

    def get_target(self) -> TaskTarget | None:
        """获取当前任务目标，线程安全。"""
        with self._lock:
            return self._target

    @property
    def has_target(self) -> bool:
        """是否有活动任务目标。"""
        with self._lock:
            return self._target is not None


# ---------------------------------------------------------------------------
# 目标匹配函数
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """统一转小写并去除首尾空白，用于大小写不敏感匹配。"""
    return text.lower().strip()


def matches_target(label: str, target: TaskTarget) -> bool:
    """判断检测框标签是否与任务目标匹配。

    匹配策略（按优先级依次尝试）：
    1. 扩展名匹配：keyword 以 "." 开头，检查 label 是否以该扩展名结尾
    2. 通配符匹配：keyword 含 "*" 或 "?"，使用 fnmatch
       - file_organize 意图下，通配符 "*" 只匹配含扩展名的标签（避免匹配 "detected_object"）
    3. 正则匹配：keyword 以 "/" 开头和结尾，如 "/report.*/"
    4. 子串匹配：keyword 是 label 的子串（大小写不敏感）

    Args:
        label: 检测框的标签文字。
        target: 当前任务目标。

    Returns:
        True 表示匹配成功。
    """
    norm_label = _normalize(label)

    for keyword in target.keywords:
        # 1. 扩展名匹配（如 ".pdf"）
        if keyword.startswith("."):
            if norm_label.endswith(keyword):
                return True
            continue

        # 2. 通配符匹配（如 "*.pdf"、"report_*"、"*"）
        if "*" in keyword or "?" in keyword:
            # file_organize 意图下，纯通配符 "*" 只匹配含扩展名的标签
            # 避免将 "detected_object" 等无扩展名的轮廓标签误判为文件
            if keyword == "*" and target.intent == "file_organize":
                if "." not in norm_label:
                    continue
            if fnmatch.fnmatch(norm_label, keyword):
                return True
            continue

        # 3. 正则匹配（如 "/report.*/"）
        if keyword.startswith("/") and keyword.endswith("/") and len(keyword) > 2:
            pattern = keyword[1:-1]
            try:
                if re.search(pattern, norm_label):
                    return True
            except re.error:
                pass  # 非法正则，跳过
            continue

        # 4. 子串匹配（最宽松，兜底）
        if keyword in norm_label:
            return True

    return False


# ---------------------------------------------------------------------------
# 置信度提升函数
# ---------------------------------------------------------------------------


def apply_task_boost(boxes: list[BoundingBoxDict]) -> list[BoundingBoxDict]:
    """对检测框列表应用任务上下文置信度提升。

    遍历每个检测框，若其标签与当前任务目标匹配，则将置信度强制提升至
    TASK_MATCH_CONFIDENCE（0.95），使其在预览中显示为绿色。
    无活动任务时原样返回，不做任何修改。

    Args:
        boxes: 原始检测框列表（来自 _run_detection 或外部写入）。

    Returns:
        处理后的检测框列表（匹配项置信度已提升，其余不变）。
        返回新列表，不修改原始数据。
    """
    ctx = TaskContext.get_instance()
    target = ctx.get_target()

    if target is None:
        # 无活动任务，原样返回
        return boxes

    result: list[BoundingBoxDict] = []
    for box in boxes:
        label = box.get("label", "")
        original_conf = float(box.get("confidence", 0.0))

        if matches_target(label, target):
            boosted_box = BoundingBoxDict(
                bbox=list(box["bbox"]),
                label=box["label"],
                confidence=TASK_MATCH_CONFIDENCE,
            )
            result.append(boosted_box)
            logger.info(
                "TaskContext: 目标匹配成功：%r，置信度 %.2f → %.2f（强制绿色）",
                label, original_conf, TASK_MATCH_CONFIDENCE,
            )
        else:
            result.append(box)
            logger.debug(
                "TaskContext: 未匹配目标：%r，保持原始置信度 %.2f",
                label, original_conf,
            )

    return result
