"""决策层：LangChain 工具定义模块。

将感知层（ElementLocator）和执行层（ActionEngine）的能力封装为 LangChain Tool 对象，
供 ReAct AgentExecutor 调用。决策层只负责"思考"和路由，不直接操作鼠标/键盘。

同时暴露 TOOLS 常量（DashScope Function Call Schema），供 LLMClient 注册工具。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from automation.file_organizer import run_file_organizer

from langchain_core.tools import Tool

from execution.action_engine import ActionEngine
from perception.element_locator import ElementLocator
from perception.screen_capturer import ScreenCapturer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chinese folder name → expanduser path mapping
# ---------------------------------------------------------------------------

_CHINESE_FOLDER_MAP: dict[str, str] = {
    "桌面": "~/Desktop",
    "文档": "~/Documents",
    "下载": "~/Downloads",
    "图片": "~/Pictures",
    "音乐": "~/Music",
    "视频": "~/Videos",
}


def resolve_chinese_path(path: str) -> str:
    """将中文文件夹名解析为对应的系统路径。

    检查 path 本身或其第一个路径组件是否为 _CHINESE_FOLDER_MAP 中的键。
    若匹配，返回 os.path.expanduser(mapped_value)；否则原样返回。

    Args:
        path: 待解析的路径字符串，可能是中文文件夹名（如 "文档"）或普通路径。

    Returns:
        解析后的路径字符串。若无匹配则返回原始 path。
    """
    # Check the full path first, then the first component
    first_component = Path(path).parts[0] if Path(path).parts else path
    key = path if path in _CHINESE_FOLDER_MAP else (first_component if first_component in _CHINESE_FOLDER_MAP else None)
    if key is not None:
        return os.path.expanduser(_CHINESE_FOLDER_MAP[key])
    return path


# ---------------------------------------------------------------------------
# DashScope Function Call Schema（供 LLMClient 使用）
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "detect_gui_elements",
            "description": "在当前屏幕截图中检测指定 GUI 元素的位置",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "目标元素的文字描述，如'安装按钮'",
                    },
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "可选截图区域 [x, y, width, height]",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "在指定逻辑坐标执行鼠标点击",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "click_type": {
                        "type": "string",
                        "enum": ["single", "double", "right"],
                        "default": "single",
                    },
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "通过剪贴板粘贴方式输入文本（支持中文）",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "通过名称或路径打开应用程序",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "description": "应用名称或完整路径",
                    },
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "organize_files",
            "description": "将源目录中的文件按类型整理到目标目录的分类子目录中",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_dir": {
                        "type": "string",
                        "description": "源目录路径（支持中文文件夹名，如'桌面'、'下载'）",
                    },
                    "target_dir": {
                        "type": "string",
                        "description": "目标目录路径（支持中文文件夹名，如'文档'、'图片'）",
                    },
                    "file_filters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选扩展名过滤列表，如 [\".pdf\", \".jpg\"]；不填则处理所有文件",
                    },
                },
                "required": ["source_dir", "target_dir"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# DesktopToolkit
# ---------------------------------------------------------------------------


class DesktopToolkit:
    """桌面自动化工具集，将感知层与执行层能力封装为 LangChain Tool 列表。

    持有 ElementLocator、ActionEngine 和 ScreenCapturer 的引用，
    每个工具方法解析 JSON 字符串参数并路由至对应的底层方法。
    """

    def __init__(
        self,
        locator: ElementLocator | None = None,
        action_engine: ActionEngine | None = None,
        screen_capturer: ScreenCapturer | None = None,
    ) -> None:
        """初始化 DesktopToolkit。

        Args:
            locator: ElementLocator 实例；若为 None 则自动创建。
            action_engine: ActionEngine 实例；若为 None 则自动创建。
            screen_capturer: ScreenCapturer 实例；若为 None 则自动创建。
        """
        self._locator: ElementLocator = locator if locator is not None else ElementLocator()
        self._action: ActionEngine = action_engine if action_engine is not None else ActionEngine()
        self._capturer: ScreenCapturer = screen_capturer if screen_capturer is not None else ScreenCapturer()
        logger.info("DesktopToolkit 初始化完成")

    # ------------------------------------------------------------------
    # 工具方法（LangChain 以 JSON 字符串传入参数）
    # ------------------------------------------------------------------

    def detect_gui_elements(self, args_json: str) -> str:
        """检测屏幕中指定 GUI 元素的位置。

        Args:
            args_json: JSON 字符串，包含 ``description``（必填）和 ``region``（可选）。

        Returns:
            JSON 字符串，包含元素名称、边界框、置信度和识别策略；失败时返回错误描述。
        """
        try:
            args: dict[str, Any] = json.loads(args_json)
            description: str = args["description"]
            region: list[int] | None = args.get("region")

            logger.info("detect_gui_elements: description=%r, region=%s", description, region)

            if region and len(region) == 4:
                x, y, w, h = region
                screenshot = self._capturer.capture_region(x, y, w, h)
            else:
                screenshot = self._capturer.capture_full()

            result = self._locator.locate_by_text(screenshot, description)

            output = {
                "name": result.name,
                "bbox": list(result.bbox),
                "confidence": result.confidence,
                "strategy": result.strategy,
                "center": [result.bbox[0] + result.bbox[2] // 2, result.bbox[1] + result.bbox[3] // 2],
            }
            logger.info("detect_gui_elements: 成功定位 %r, bbox=%s", description, result.bbox)
            return json.dumps(output, ensure_ascii=False)

        except KeyError as exc:
            msg = f"detect_gui_elements: 缺少必填参数 {exc}"
            logger.error(msg)
            return json.dumps({"error": msg}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            msg = f"detect_gui_elements: 执行失败 - {exc}"
            logger.error(msg)
            return json.dumps({"error": msg}, ensure_ascii=False)

    def click(self, args_json: str) -> str:
        """在指定逻辑坐标执行鼠标点击。

        Args:
            args_json: JSON 字符串，包含 ``x``、``y``（必填）和 ``click_type``（可选）。

        Returns:
            操作结果描述字符串。
        """
        try:
            args: dict[str, Any] = json.loads(args_json)
            x: int = int(args["x"])
            y: int = int(args["y"])
            click_type: str = args.get("click_type", "single")

            logger.info("click: x=%d, y=%d, click_type=%s", x, y, click_type)
            success = self._action.click(x, y, click_type)  # type: ignore[arg-type]

            if success:
                result_msg = f"已在坐标 ({x}, {y}) 执行 {click_type} 点击"
                logger.info("click: %s", result_msg)
                return result_msg
            else:
                error_msg = f"点击失败：坐标 ({x}, {y}) 超出屏幕边界或操作被拒绝"
                logger.warning("click: %s", error_msg)
                return error_msg

        except KeyError as exc:
            msg = f"click: 缺少必填参数 {exc}"
            logger.error(msg)
            return msg
        except Exception as exc:  # noqa: BLE001
            msg = f"click: 执行失败 - {exc}"
            logger.error(msg)
            return msg

    def type_text(self, args_json: str) -> str:
        """通过剪贴板粘贴方式输入文本。

        Args:
            args_json: JSON 字符串，包含 ``text``（必填）。

        Returns:
            操作结果描述字符串。
        """
        try:
            args: dict[str, Any] = json.loads(args_json)
            text: str = args["text"]

            logger.info("type_text: 文本长度=%d", len(text))
            success = self._action.type_text(text)

            if success:
                result_msg = f"已输入文本（长度={len(text)}）"
                logger.info("type_text: %s", result_msg)
                return result_msg
            else:
                error_msg = "type_text: 输入文本失败"
                logger.warning(error_msg)
                return error_msg

        except KeyError as exc:
            msg = f"type_text: 缺少必填参数 {exc}"
            logger.error(msg)
            return msg
        except Exception as exc:  # noqa: BLE001
            msg = f"type_text: 执行失败 - {exc}"
            logger.error(msg)
            return msg

    def open_application(self, args_json: str) -> str:
        """通过名称或路径打开应用程序。

        Args:
            args_json: JSON 字符串，包含 ``app``（必填）。

        Returns:
            操作结果描述字符串。
        """
        try:
            args: dict[str, Any] = json.loads(args_json)
            app: str = args["app"]

            logger.info("open_application: app=%r", app)
            success = self._action.open_application(app)

            if success:
                result_msg = f"已启动应用程序：{app}"
                logger.info("open_application: %s", result_msg)
                return result_msg
            else:
                error_msg = f"open_application: 启动失败 - {app}"
                logger.warning(error_msg)
                return error_msg

        except KeyError as exc:
            msg = f"open_application: 缺少必填参数 {exc}"
            logger.error(msg)
            return msg
        except Exception as exc:  # noqa: BLE001
            msg = f"open_application: 执行失败 - {exc}"
            logger.error(msg)
            return msg

    def organize_files(self, args_json: str) -> str:
        """将源目录中的文件按类型整理到目标目录的分类子目录中。

        Args:
            args_json: JSON 字符串，包含 ``source_dir``（必填）、``target_dir``（必填）
                       和 ``file_filters``（可选，扩展名列表）。

        Returns:
            操作结果描述字符串。
        """
        try:
            args: dict[str, Any] = json.loads(args_json)
            source_dir: str = resolve_chinese_path(args["source_dir"])
            target_dir: str = resolve_chinese_path(args["target_dir"])
            file_filters: list[str] | None = args.get("file_filters")

            # If source_dir is relative, resolve against CWD
            if not Path(source_dir).is_absolute():
                source_dir = str(Path(source_dir).resolve())

            # If target_dir is still relative after Chinese path resolution,
            # resolve it relative to source_dir's parent directory
            if not Path(target_dir).is_absolute():
                target_dir = str(Path(source_dir).parent / target_dir)
                logger.info("organize_files: 相对路径已规范化为绝对路径: %r", target_dir)

            logger.info(
                "organize_files: source_dir=%r, target_dir=%r, file_filters=%s",
                source_dir, target_dir, file_filters,
            )

            run_file_organizer(
                source_dir,
                target_dir,
                lambda step, pct: logger.debug("organize_files progress: %s (%d%%)", step, pct),
                threading.Event(),
                file_filters,
            )

            result_msg = "文件整理完成"
            logger.info("organize_files: %s", result_msg)
            return result_msg

        except FileNotFoundError as exc:
            msg = f"organize_files: 目录不存在 - {exc}"
            logger.error(msg)
            return msg
        except KeyError as exc:
            msg = f"organize_files: 缺少必填参数 {exc}"
            logger.error(msg)
            return msg
        except Exception as exc:  # noqa: BLE001
            msg = f"organize_files: 执行失败 - {exc}"
            logger.error(msg)
            return msg

    # ------------------------------------------------------------------
    # 公共接口：返回 LangChain Tool 列表
    # ------------------------------------------------------------------

    def get_tools(self) -> list[Tool]:
        """返回 LangChain Tool 对象列表，供 AgentExecutor 注册使用。

        Returns:
            包含五个工具的列表：detect_gui_elements、click、type_text、open_application、organize_files。
        """
        return [
            Tool(
                name="detect_gui_elements",
                func=self.detect_gui_elements,
                description=(
                    "在当前屏幕截图中检测指定 GUI 元素的位置。"
                    "输入 JSON：{\"description\": \"目标元素描述\", \"region\": [x, y, w, h]}（region 可选）。"
                    "返回元素的边界框和中心坐标。"
                ),
            ),
            Tool(
                name="click",
                func=self.click,
                description=(
                    "在指定逻辑坐标执行鼠标点击。"
                    "输入 JSON：{\"x\": 整数, \"y\": 整数, \"click_type\": \"single|double|right\"}。"
                    "click_type 默认为 single。"
                ),
            ),
            Tool(
                name="type_text",
                func=self.type_text,
                description=(
                    "通过剪贴板粘贴方式输入文本（支持中文）。"
                    "输入 JSON：{\"text\": \"要输入的文本内容\"}。"
                ),
            ),
            Tool(
                name="open_application",
                func=self.open_application,
                description=(
                    "通过名称或路径打开应用程序。"
                    "输入 JSON：{\"app\": \"应用名称或完整路径\"}。"
                ),
            ),
            Tool(
                name="organize_files",
                func=self.organize_files,
                description=(
                    "将源目录中的文件按类型整理到目标目录的分类子目录中。"
                    "输入 JSON：{\"source_dir\": \"源目录路径\", \"target_dir\": \"目标目录路径\", "
                    "\"file_filters\": [\".pdf\", \".jpg\"]}（file_filters 可选）。"
                    "支持中文文件夹名，如'桌面'、'文档'、'下载'。"
                ),
            ),
        ]
