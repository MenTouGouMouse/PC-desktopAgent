"""
gui.chat_agent — 自然语言对话代理模块。

包含两个核心类：
- IntentParser: 调用 LLMClient 将用户自然语言解析为结构化 IntentResult
- ChatAgent: 管理多轮对话上下文，路由意图到对应自动化模块并推送结果到前端
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from decision.llm_client import LLMCallError, LLMClient
from gui.progress_manager import ProgressManager
from utils.path_resolver import resolve_path, strip_folder_suffix

logger = logging.getLogger(__name__)

# 系统提示词：要求模型只返回合法 JSON
_INTENT_SYSTEM_PROMPT = """你是一个桌面自动化助手的意图解析器。
用户会用中文描述任务，你需要将其解析为结构化 JSON。

支持的意图类型：
1. file_organize: 文件整理任务
   返回格式: {"intent": "file_organize", "params": {"source": "<路径或null>", "target": "<路径或null>", "filters": ["<扩展名>"]}}
   - source/target 路径规则：中文别名直接填（如"桌面"、"文档"、"下载"），英文路径原样填
   - filters 规则：从用户指令中提取文件类型，转为小写扩展名（不含点号），如 ["pdf", "jpg", "docx"]
     - "PDF文件" → ["pdf"]
     - "图片" → ["jpg", "jpeg", "png", "gif", "bmp", "webp"]
     - "文档" → ["pdf", "doc", "docx", "txt"]
     - "视频" → ["mp4", "avi", "mkv", "mov"]
     - 未指定文件类型 → [] （整理所有文件）
2. software_install: 软件安装任务
   返回格式: {"intent": "software_install", "params": {"package_path": "<路径或null>"}}
3. unknown: 无法识别的意图
   返回格式: {"intent": "unknown", "params": {}, "clarification": "<说明>"}

规则：
- 只返回合法 JSON，不包含任何 Markdown 代码块标记（如 ```json 或 ```）
- 如果缺少必要参数，在 clarification 字段中提出追问，对应 params 字段设为 null
- 不要返回任何额外文字，只返回 JSON 对象"""

# 上下文截断阈值（字符数）
_CONTEXT_MAX_CHARS: int = 8000
# 截断后保留的最近消息数
_CONTEXT_KEEP_RECENT: int = 10


def _load_chat_model() -> str:
    """从 config/settings.yaml 读取 chat_model，默认 'qwen-plus'。"""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    try:
        with open(config_path, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}
        return str(settings.get("chat_model", "qwen-plus"))
    except Exception:
        logger.warning("无法读取 settings.yaml，使用默认 chat_model=qwen-plus")
        return "qwen-plus"


@dataclass
class IntentResult:
    """意图解析结果数据类。

    Attributes:
        intent: 意图类型，"file_organize" | "software_install" | "unknown"
        params: 任务参数字典
        clarification: 追问内容，None 表示无需追问
    """

    intent: str
    params: dict[str, Any] = field(default_factory=dict)
    clarification: str | None = None


def _make_unknown(clarification: str = "AI 返回格式异常，请重新描述您的任务") -> IntentResult:
    """创建 unknown 兜底 IntentResult。"""
    return IntentResult(intent="unknown", params={}, clarification=clarification)


class IntentParser:
    """意图解析器，调用 LLMClient 将自然语言转换为 IntentResult。"""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def parse(self, messages: list[dict]) -> IntentResult:
        """解析对话消息列表，返回 IntentResult。

        Args:
            messages: 对话消息列表（OpenAI 兼容格式）。

        Returns:
            解析出的 IntentResult；JSON 解析失败时返回 unknown 兜底。

        Raises:
            LLMCallError: LLM API 调用失败时向上抛出。
        """
        full_messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}] + messages
        response = self._llm_client.chat(full_messages)
        content: str = ""
        if isinstance(response, dict):
            content = response.get("content", "") or ""
        else:
            content = str(response)

        stripped = self._strip_markdown(content)
        try:
            raw = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            logger.warning("IntentParser: JSON 解析失败，内容: %r", content[:200])
            return _make_unknown()

        return self._validate_and_build(raw)

    def _strip_markdown(self, text: str) -> str:
        """剥离 Markdown 代码块标记（```json ... ``` 或 ``` ... ```）。

        Args:
            text: 可能包含 Markdown 标记的字符串。

        Returns:
            剥离标记后的字符串。
        """
        stripped = text.strip()
        # 匹配 ```json ... ``` 或 ``` ... ```
        pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
        match = re.match(pattern, stripped, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return stripped

    def _validate_and_build(self, raw: Any) -> IntentResult:
        """校验解析后的字典并构建 IntentResult。

        Args:
            raw: json.loads 返回的对象。

        Returns:
            合法的 IntentResult；校验失败时返回 unknown 兜底。
        """
        if not isinstance(raw, dict):
            return _make_unknown()

        intent = raw.get("intent")
        if not isinstance(intent, str):
            return _make_unknown()

        params = raw.get("params", {})
        if not isinstance(params, dict):
            params = {}

        clarification = raw.get("clarification")
        if clarification is not None and not isinstance(clarification, str):
            clarification = str(clarification)

        return IntentResult(intent=intent, params=params, clarification=clarification)


class ChatAgent:
    """自然语言对话代理，管理多轮上下文并路由意图到自动化模块。

    Args:
        llm_client: LLMClient 实例，用于意图解析。
        progress_manager: ProgressManager 实例，用于同步任务进度。
        stop_event: 外部停止信号，复用 PythonAPI 的 _stop_event。
        push_fn: 推送消息到前端的回调，签名为 (role: str, content: str) -> None。
        model_id: 使用的模型 ID，默认从 settings.yaml 读取。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        progress_manager: ProgressManager,
        stop_event: threading.Event,
        push_fn: Callable[[str, str], None],
        model_id: str = "",
    ) -> None:
        self._llm_client = llm_client
        self._progress_manager = progress_manager
        self._stop_event = stop_event
        self._push_fn = push_fn
        self._model_id = model_id or _load_chat_model()
        self._context: list[dict] = []
        self._context_lock = threading.Lock()
        self._intent_parser = IntentParser(llm_client)

        # 检查 API Key
        import os
        from pathlib import Path as _Path
        _env_path = _Path(__file__).parent.parent / "config" / ".env"
        if _env_path.exists():
            load_dotenv(dotenv_path=_env_path, override=False)
        if not os.environ.get("DASHSCOPE_API_KEY"):
            logger.error("DASHSCOPE_API_KEY 未配置，请在 config/.env 中设置")
        logger.info("ChatAgent 初始化完成，model=%s", self._model_id)

    @property
    def is_running(self) -> bool:
        """当前是否有任务正在运行。"""
        return self._progress_manager.get().is_running

    def clear_context(self) -> None:
        """清空对话上下文。"""
        with self._context_lock:
            self._context.clear()
        logger.info("ChatAgent: 对话上下文已清空")

    def _truncate_context_if_needed(self) -> None:
        """若上下文总字符数超过阈值，保留最近 N 条消息。"""
        with self._context_lock:
            total_chars = sum(len(m.get("content", "")) for m in self._context)
            if total_chars > _CONTEXT_MAX_CHARS:
                self._context = self._context[-_CONTEXT_KEEP_RECENT:]
                logger.info("ChatAgent: 上下文已截断，保留最近 %d 条", _CONTEXT_KEEP_RECENT)
                # 在锁外推送，避免死锁
                truncated = True
            else:
                truncated = False

        if truncated:
            self._push_fn("system", "上下文已自动截断以节省资源")

    def handle_message(self, message: str) -> None:
        """处理用户消息，解析意图并路由到对应自动化模块。

        Args:
            message: 用户输入的自然语言消息。
        """
        import os

        logger.info("ChatAgent.handle_message: 消息长度=%d", len(message))

        # 检查 API Key
        if not os.environ.get("DASHSCOPE_API_KEY"):
            self._push_fn("system", "API 密钥未配置，请检查 config/.env 文件")
            return

        # 追加用户消息到上下文
        with self._context_lock:
            self._context.append({"role": "user", "content": message})
            context_snapshot = list(self._context)

        self._truncate_context_if_needed()

        # 解析意图
        try:
            intent_result = self._intent_parser.parse(context_snapshot)
        except LLMCallError as exc:
            logger.error("ChatAgent: LLM 调用失败: %s", exc)
            self._push_fn("system", f"AI 服务调用失败：{exc}")
            return

        logger.info(
            "ChatAgent: intent=%s, params_keys=%s",
            intent_result.intent,
            list(intent_result.params.keys()),
        )

        # 路由
        if intent_result.clarification is not None:
            self._push_fn("assistant", intent_result.clarification)
            return

        if intent_result.intent == "file_organize":
            if self.is_running:
                self._push_fn("assistant", "当前有任务正在执行，请等待完成后再发起新任务")
                return
            # 设置任务目标：将 filters 转为带点号的扩展名关键词，无 filters 时匹配所有文件
            self._set_file_organize_target(intent_result.params)
            logger.info("ChatAgent: 启动文件整理任务，时间=%s", time.strftime("%Y-%m-%d %H:%M:%S"))
            thread = threading.Thread(
                target=self._run_file_organizer,
                args=(intent_result.params,),
                daemon=True,
            )
            thread.start()

        elif intent_result.intent == "software_install":
            if self.is_running:
                self._push_fn("assistant", "当前有任务正在执行，请等待完成后再发起新任务")
                return
            # 设置任务目标：安装步骤中常见的按钮文字
            self._set_install_target()
            logger.info("ChatAgent: 启动软件安装任务，时间=%s", time.strftime("%Y-%m-%d %H:%M:%S"))
            thread = threading.Thread(
                target=self._run_software_installer,
                args=(intent_result.params,),
                daemon=True,
            )
            thread.start()
        else:
            # unknown 或其他
            clarification = intent_result.clarification or "抱歉，我无法理解您的指令，请重新描述您想要执行的任务。"
            self._push_fn("assistant", clarification)

    def _run_file_organizer(self, params: dict) -> None:
        """在后台线程中执行文件整理任务（真实实现）。"""
        from automation.file_organizer import run_file_organizer

        source = params.get("source")
        target = params.get("target")
        filters = params.get("filters") or []

        # Resolve aliases and foreign-user paths before validation
        # Rule: if raw value is an alias (e.g. "桌面", "Desktop"), map to home subdir.
        # If it's already an absolute path (e.g. D:\Projects), pass through unchanged.
        def _resolve(raw: str) -> str:
            p = Path(raw)
            # Already absolute — pass through (supports D:\, C:\, /home/... etc.)
            if p.is_absolute():
                return raw
            # Alias or relative — use resolve_path
            return str(resolve_path(raw))

        source = _resolve(source) if source is not None else None
        if target is not None:
            resolved_target = resolve_path(target)
            cleaned_name = strip_folder_suffix(resolved_target.name)
            resolved_str = str(resolved_target.parent / cleaned_name)

            # If target is still relative after alias resolution, anchor it to
            # source directory (e.g. "details" → Desktop/details)
            resolved_path = Path(resolved_str)
            if not resolved_path.is_absolute() and source is not None:
                resolved_path = Path(source) / resolved_str
                logger.info(
                    "_run_file_organizer: 相对目标路径已规范化: %r → %r",
                    resolved_str, str(resolved_path),
                )
            target = str(resolved_path)
        else:
            target = None

        # 校验必要参数
        if source is None or target is None:
            missing = "源路径" if source is None else "目标路径"
            self._push_fn(
                "assistant",
                f"请告诉我{missing}，例如：整理 D:/Downloads 到 D:/Organized",
            )
            # 参数不足，清除已设置的任务目标
            from automation.task_context import TaskContext
            TaskContext.get_instance().clear_target()
            return

        self._progress_manager.update(0, "文件整理任务启动中...", "file_organize", is_running=True)
        self._stop_event.clear()

        logger.info(
            "ChatAgent._run_file_organizer: source=%r, target=%r, filters=%r",
            source, target, filters,
        )

        # 诊断：扫描源目录，推送实际文件列表
        try:
            _src_path = Path(source)
            if _src_path.exists():
                _all = [p.name for p in _src_path.iterdir() if p.is_file()]
                logger.info("ChatAgent: 源目录文件列表(%d): %s", len(_all), _all[:20])
                self._push_fn("system", f"[诊断] 源目录共 {len(_all)} 个文件，filters={filters or '全部'}")
            else:
                logger.warning("ChatAgent: 源目录不存在: %r", source)
                self._push_fn("system", f"[诊断] 源目录不存在: {source}")
        except Exception as _e:
            logger.warning("ChatAgent: 诊断扫描失败: %s", _e)

        def _cb(step: str, percent: int) -> None:
            self._progress_manager.update(percent, step, "file_organize", is_running=True)
            self._push_fn("system", f"[文件整理] {step}")

        try:
            run_file_organizer(source, target, _cb, self._stop_event, filters)
            self._progress_manager.update(100, "文件整理完成", "file_organize", is_running=False)
            self._push_fn(
                "assistant",
                f"**文件整理**任务已完成。源路径 **{source}** → 目标路径 **{target}**",
            )
            logger.info("ChatAgent: 文件整理任务完成")
        except Exception as exc:
            logger.error("ChatAgent: 文件整理任务异常: %s", exc, exc_info=True)
            self._push_fn("system", f"**文件整理**任务出错：{exc}")
            self._progress_manager.update(
                self._progress_manager.get().percent,
                "任务出错",
                "file_organize",
                is_running=False,
            )
        finally:
            # 任务结束（无论成功或失败）清除任务目标，避免后续检测框误匹配
            from automation.task_context import TaskContext
            TaskContext.get_instance().clear_target()

    def _set_file_organize_target(self, params: dict) -> None:
        """根据文件整理参数设置任务目标，供检测框置信度提升使用。

        将 filters（扩展名列表，如 ["pdf", "jpg"]）转为带点号的关键词（[".pdf", ".jpg"]）。
        无 filters 时使用通配符 "*"，匹配所有文件。

        Args:
            params: 意图解析结果的 params 字典，含 filters 字段。
        """
        from automation.task_context import TaskContext, TaskTarget

        filters: list[str] = params.get("filters") or []
        if filters:
            # 确保每个扩展名以 "." 开头
            keywords = [f if f.startswith(".") else f".{f}" for f in filters]
            description = f"文件整理：{', '.join(keywords)}"
        else:
            # 无过滤条件，匹配所有文件（用通配符）
            keywords = ["*"]
            description = "文件整理：所有文件"

        TaskContext.get_instance().set_target(
            TaskTarget(intent="file_organize", keywords=keywords, description=description)
        )
        logger.info("ChatAgent: 文件整理任务目标已设置: %s", description)

    def _set_install_target(self) -> None:
        """设置软件安装任务目标：常见安装向导按钮文字。

        覆盖安装流程中所有常见按钮（中英文），确保安装按钮在预览中显示绿色。
        """
        from automation.task_context import TaskContext, TaskTarget

        # 覆盖常见安装向导按钮（中英文）
        keywords = [
            "下一步", "next", "安装", "install",
            "我同意", "agree", "accept",
            "完成", "finish", "确定", "ok",
        ]
        description = "软件安装：安装向导按钮"
        TaskContext.get_instance().set_target(
            TaskTarget(intent="software_install", keywords=keywords, description=description)
        )
        logger.info("ChatAgent: 软件安装任务目标已设置: %s", description)

    def _run_software_installer(self, params: dict) -> None:
        """在后台线程中执行软件安装任务（真实实现）。"""
        from automation.software_installer import run_software_installer

        package_path = params.get("package_path")

        # 校验必要参数
        if package_path is None:
            self._push_fn(
                "assistant",
                "请告诉我安装包路径，例如：安装 D:/Downloads/setup.exe",
            )
            from automation.task_context import TaskContext
            TaskContext.get_instance().clear_target()
            return

        self._progress_manager.update(0, "软件安装任务启动中...", "software_install", is_running=True)
        self._stop_event.clear()

        def _cb(step: str, percent: int) -> None:
            self._progress_manager.update(percent, step, "software_install", is_running=True)
            self._push_fn("system", f"[软件安装] {step}")

        try:
            run_software_installer(package_path, _cb, self._stop_event)
            self._progress_manager.update(100, "软件安装完成", "software_install", is_running=False)
            self._push_fn(
                "assistant",
                f"**软件安装**任务已完成。安装包：**{package_path}**",
            )
            logger.info("ChatAgent: 软件安装任务完成")
        except Exception as exc:
            logger.error("ChatAgent: 软件安装任务异常: %s", exc, exc_info=True)
            self._push_fn("system", f"**软件安装**任务出错：{exc}")
            self._progress_manager.update(
                self._progress_manager.get().percent,
                "任务出错",
                "software_install",
                is_running=False,
            )
        finally:
            from automation.task_context import TaskContext
            TaskContext.get_instance().clear_target()
