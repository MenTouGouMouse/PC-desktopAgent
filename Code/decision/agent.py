"""决策层：桌面自动化 ReAct Agent 模块。

使用 DashScope 原生 Function Call 循环实现 ReAct 范式，将自然语言指令分解为
detect_gui_elements / click / type_text / open_application 工具调用序列。
使用滚动摘要机制管理超出上下文窗口的对话历史。
集成 MemorySystem，在执行前检索相似历史操作，执行后持久化操作记录。

职责边界：
- 只负责"思考"和路由，不直接操作鼠标/键盘
- 所有坐标以逻辑坐标传递，不做 DPI 转换
- LLMCallError 在 run() 中捕获并返回错误字符串，不调用任何 ActionEngine 方法
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

from langchain_core.tools import Tool

from decision.llm_client import LLMCallError, LLMClient
from decision.memory import MemorySystem, OperationRecord
from decision.tools import TOOLS as _DESKTOP_TOOL_SCHEMAS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个桌面自动化助手，能够通过工具控制计算机完成用户指定的任务。\n"
    "请根据用户指令，逐步调用工具完成任务。每次只调用一个工具，观察结果后再决定下一步。\n"
    "重要原则：\n"
    "1. 如果某个元素找不到，换一个更简单的描述词重试，或尝试其他方式完成任务。\n"
    "2. 如果连续 3 次找不到同一个元素，停止尝试并说明原因。\n"
    "3. 任务完成后，立即用中文简洁描述执行结果，不要继续调用工具。\n"
    "4. 打开应用程序时，使用英文命令名（如 explorer、notepad、calc）而不是中文名称。"
)


class DesktopAgent:
    """基于 DashScope Function Call 循环的桌面自动化智能体。

    使用 DashScope 原生 tool_call 实现 ReAct 范式：
    Thought（LLM 推理）→ Action（tool_call）→ Observation（工具结果）循环，
    直到 LLM 不再发起工具调用为止。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tools: list[Tool],
        memory_system: MemorySystem | None = None,
        max_iterations: int = 50,
        memory_max_tokens: int = 2000,
    ) -> None:
        """初始化 DesktopAgent。

        Args:
            llm_client: 已初始化的 LLMClient 实例。
            tools: LangChain Tool 对象列表（来自 DesktopToolkit.get_tools()）。
            memory_system: 可选的 MemorySystem 实例。
            max_iterations: 最大工具调用轮次，防止无限循环。
            memory_max_tokens: 滚动摘要的最大 token 数（近似字符数）。
        """
        self._llm_client = llm_client
        self._tools = tools
        self._memory_system = memory_system
        self._max_iterations = max_iterations
        self._memory_max_tokens = memory_max_tokens

        # 直接使用 tools.py 中定义的标准 DashScope Function Call schema
        self._tool_schemas = _DESKTOP_TOOL_SCHEMAS
        # 工具名 → 可调用函数的映射
        self._tool_map: dict[str, Any] = {t.name: t.func for t in tools}

        # 滚动摘要：存储压缩后的历史摘要字符串
        self._conversation_summary: str = ""

        logger.info(
            "DesktopAgent 初始化完成，工具数量=%d，max_iterations=%d",
            len(self._tools),
            self._max_iterations,
        )

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _retrieve_similar_history(self, instruction: str) -> str:
        """从 MemorySystem 检索语义相似的历史操作。"""
        if self._memory_system is None:
            return ""
        try:
            records = self._memory_system.search_similar(instruction)
            if not records:
                return ""
            lines = ["【相似历史操作参考】"]
            for r in records:
                lines.append(f"- [{r.timestamp}] {r.action_type}: {r.description} → {r.result}")
            context = "\n".join(lines)
            logger.info("DesktopAgent: 检索到 %d 条相似历史操作", len(records))
            return context
        except Exception as exc:  # noqa: BLE001
            logger.warning("DesktopAgent: 历史检索失败，跳过: %s", exc)
            return ""

    def _store_operation_record(self, instruction: str, result_text: str, outcome: Literal["success", "failure"]) -> None:
        """将本次执行记录持久化到 MemorySystem。"""
        if self._memory_system is None:
            return
        try:
            record = OperationRecord(
                timestamp=datetime.now().isoformat(),
                action_type="agent_run",
                description=instruction,
                coordinates=None,
                result=outcome,
                metadata={"output": result_text},
            )
            self._memory_system.store(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DesktopAgent: 持久化操作记录失败，忽略: %s", exc)

    def _maybe_summarize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """当消息历史过长时，调用 LLM 生成摘要并压缩历史。

        简单实现：按字符数估算 token，超出阈值时请求摘要。
        """
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if total_chars <= self._memory_max_tokens:
            return messages

        logger.info("DesktopAgent: 消息历史过长（%d chars），触发滚动摘要", total_chars)
        try:
            history_text = "\n".join(
                f"{m['role']}: {m.get('content', '')}" for m in messages
                if m["role"] != "system"
            )
            summary_messages = [
                {"role": "system", "content": "请用简洁的中文总结以下对话历史，保留关键操作步骤和结果："},
                {"role": "user", "content": history_text},
            ]
            resp = self._llm_client.chat(summary_messages)
            self._conversation_summary = resp.get("content", "")
            logger.info("DesktopAgent: 滚动摘要生成完成，长度=%d", len(self._conversation_summary))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DesktopAgent: 摘要生成失败，保留原始历史: %s", exc)
            return messages

        # 保留 system 消息 + 摘要消息 + 最近 2 条非 system 消息
        system_msgs = [m for m in messages if m["role"] == "system"]
        non_system = [m for m in messages if m["role"] != "system"]
        recent = non_system[-2:] if len(non_system) >= 2 else non_system
        compressed = system_msgs + [
            {"role": "assistant", "content": f"【历史摘要】{self._conversation_summary}"}
        ] + recent
        return compressed

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """执行工具调用，返回结果字符串。

        DesktopToolkit 的工具函数接受 args_json 字符串，
        而 DashScope 传来的是已解析的 dict，需要重新序列化。
        """
        func = self._tool_map.get(tool_name)
        if func is None:
            return f"错误：未知工具 '{tool_name}'"
        try:
            # DesktopToolkit 工具函数统一接受 JSON 字符串参数
            args_json = json.dumps(tool_args, ensure_ascii=False)
            result = func(args_json)
            return str(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("DesktopAgent: 工具 '%s' 执行异常: %s", tool_name, exc)
            return f"工具执行失败：{exc}"

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self, instruction: str) -> str:
        """执行自然语言指令，返回执行摘要。

        使用 DashScope Function Call 循环实现 ReAct：
        1. 执行前检索相似历史操作
        2. 进入 Thought→Action→Observation 循环（最多 max_iterations 轮）
        3. LLM 不再发起工具调用时结束，返回最终回复
        4. 执行后持久化操作记录

        Args:
            instruction: 用户的自然语言指令。

        Returns:
            执行摘要字符串；LLM 调用失败时返回包含错误描述的字符串，
            不调用任何 ActionEngine 方法。
        """
        logger.info("DesktopAgent.run: 开始执行指令，长度=%d", len(instruction))

        # 1. 检索相似历史
        history_context = self._retrieve_similar_history(instruction)
        user_content = instruction
        if history_context:
            user_content = f"{history_context}\n\n当前指令：{instruction}"

        # 2. 构建初始消息列表
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        final_output = ""

        try:
            for iteration in range(self._max_iterations):
                logger.debug("DesktopAgent.run: 第 %d 轮 LLM 调用", iteration + 1)

                # 滚动摘要压缩
                messages = self._maybe_summarize(messages)

                # 调用 LLM（可能抛出 LLMCallError）
                response = self._llm_client.chat(messages, tools=self._tool_schemas)

                tool_calls = response.get("tool_calls")

                if not tool_calls:
                    # LLM 没有发起工具调用，任务完成
                    final_output = response.get("content", "任务已完成")
                    logger.info("DesktopAgent.run: LLM 未发起工具调用，任务完成")
                    break

                # 将 assistant 消息（含 tool_calls）加入历史
                # 确保 tool_calls 中的 arguments 是 JSON 字符串（DashScope 要求）
                normalized_tool_calls = []
                for tc in tool_calls:
                    tc_copy = dict(tc)
                    func_copy = dict(tc_copy.get("function", {}))
                    args = func_copy.get("arguments", "{}")
                    if not isinstance(args, str):
                        func_copy["arguments"] = json.dumps(args, ensure_ascii=False)
                    tc_copy["function"] = func_copy
                    normalized_tool_calls.append(tc_copy)

                messages.append({
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": normalized_tool_calls,
                })

                # 执行所有工具调用，收集结果
                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name", "")
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    tool_call_id = tc.get("id", f"call_{iteration}")

                    try:
                        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        tool_args = {"args_json": raw_args}

                    logger.info(
                        "DesktopAgent.run: 执行工具 '%s'，参数=%s", tool_name, tool_args
                    )
                    observation = self._execute_tool(tool_name, tool_args)
                    logger.info("DesktopAgent.run: 工具 '%s' 结果: %s", tool_name, observation[:200])

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": observation,
                    })

            else:
                # 达到最大迭代次数
                final_output = f"任务已达到最大迭代次数（{self._max_iterations}），请检查任务是否完成。"
                logger.warning("DesktopAgent.run: 达到最大迭代次数 %d", self._max_iterations)

            self._store_operation_record(instruction, final_output, "success")
            return final_output

        except LLMCallError as exc:
            error_msg = f"任务执行失败：{exc}"
            logger.error("DesktopAgent.run: LLMCallError - %s", exc)
            self._store_operation_record(instruction, error_msg, "failure")
            return error_msg

        except Exception as exc:  # noqa: BLE001
            error_msg = f"任务执行失败：{exc}"
            logger.error("DesktopAgent.run: 未预期异常 - %s", exc, exc_info=True)
            self._store_operation_record(instruction, error_msg, "failure")
            return error_msg
