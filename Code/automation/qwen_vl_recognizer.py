"""automation/qwen_vl_recognizer — Qwen-VL 视觉文件识别模块。

负责截图预处理、构造提示词、调用 Qwen-VL API、解析 JSON、坐标转换，
并将识别结果写入 DetectionCache，输出 list[VisionFileItem]。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
import yaml
from dotenv import load_dotenv

# 确保 .env 已加载（兜底，正常由 config_loader.load_config() 负责）
_ENV_PATH = Path(__file__).parent.parent / "config" / ".env"
if _ENV_PATH.exists() and not os.environ.get("DASHSCOPE_API_KEY"):
    load_dotenv(dotenv_path=_ENV_PATH, override=False)

if TYPE_CHECKING:
    from automation.object_detector import DetectionCache

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

_VALID_FILE_TYPES = frozenset(
    ["PDF", "Word", "Excel", "PowerPoint", "Image", "Video", "Audio", "Archive", "Code", "Folder", "Other"]
)

# Task 8.1: 高召回率提示词模板
_PROMPT_TEMPLATE = (
    "你是一个精准的文件管理器视觉识别模型。下面是一张 Windows 文件资源管理器或桌面的截图。\n\n"
    "**核心任务**：找出截图中【所有】文件和文件夹图标，一个都不能遗漏。\n\n"
    "**强制要求**：\n"
    "- 列出截图中全部文件，一个都不能遗漏\n"
    "- 即使文件名模糊或部分遮挡，也必须尝试识别\n"
    "- 返回的 JSON 数组长度必须等于截图中可见文件总数\n"
    "- 不要只返回最显著的一个，必须扫描整个截图区域\n\n"
    "对每个图标，返回以下字段：\n"
    "- bbox: [x1, y1, x2, y2]，图标（含文件名标签）的边界框像素坐标，原点为图像左上角\n"
    "- type: 文件类型，从以下枚举中选择：PDF/Word/Excel/PowerPoint/Image/Video/Audio/Archive/Code/Folder/Other\n"
    "- name: 图标下方显示的完整文件名（必须包含扩展名，如 report.pdf、简历.docx）；无法识别时为 null\n"
    "- confidence: 0.0~1.0 之间的浮点数，表示你对该结果的确定程度\n"
    "- icon_appearance: 图标的视觉外观描述（<=50字符），例如：红色矩形带白色PDF字样、蓝色W形Word图标、黄色文件夹\n\n"
    "**图标外观参考**：\n"
    "- PDF（.pdf）：红色矩形图标，带白色PDF字样\n"
    "- Word（.doc/.docx）：蓝色图标，带白色W字样\n"
    "- Excel（.xls/.xlsx）：绿色图标，带白色X字样\n"
    "- PowerPoint（.ppt/.pptx）：橙色/红色图标，带白色P字样\n"
    "- TXT（.txt）：白色或灰色纯文本图标，显示文字行条纹，无特殊颜色\n"
    "- 文件夹：黄色/金色文件夹图标\n"
    "- 图片（.jpg/.png等）：含缩略图预览或山景默认图标\n"
    "- 压缩包（.zip/.rar）：带拉链或叠层纸张图标，蓝色或黄色\n"
    "- 代码文件（.py/.js等）：白色文档图标，带语言logo或齿轮图标\n\n"
    "**重要规则**：\n"
    "- 只返回 JSON 数组，不要任何 Markdown 标记或额外文字\n"
    "- 坐标必须基于截图本身的像素，不要使用百分比\n"
    "- 中英文混合文件名请尽量精确识别，包括括号、数字、空格\n\n"
    "**示例输出1**（3个文件）：\n"
    "[{\"bbox\": [10, 20, 74, 100], \"type\": \"PDF\", \"name\": \"个人简历.pdf\", \"confidence\": 0.92, \"icon_appearance\": \"红色矩形带白色PDF字样\"},\n"
    " {\"bbox\": [90, 20, 154, 100], \"type\": \"Word\", \"name\": \"报告.docx\", \"confidence\": 0.88, \"icon_appearance\": \"蓝色W形Word图标\"},\n"
    " {\"bbox\": [170, 20, 234, 100], \"type\": \"Folder\", \"name\": \"项目文件夹\", \"confidence\": 0.95, \"icon_appearance\": \"黄色文件夹图标\"}]\n\n"
    "**示例输出2**（4个文件）：\n"
    "[{\"bbox\": [10, 20, 74, 100], \"type\": \"Excel\", \"name\": \"数据.xlsx\", \"confidence\": 0.90, \"icon_appearance\": \"绿色X形Excel图标\"},\n"
    " {\"bbox\": [90, 20, 154, 100], \"type\": \"Image\", \"name\": \"截图.png\", \"confidence\": 0.85, \"icon_appearance\": \"含缩略图预览的图片图标\"},\n"
    " {\"bbox\": [170, 20, 234, 100], \"type\": \"Archive\", \"name\": \"备份.zip\", \"confidence\": 0.87, \"icon_appearance\": \"蓝色带拉链压缩包图标\"},\n"
    " {\"bbox\": [250, 20, 314, 100], \"type\": \"Code\", \"name\": \"main.py\", \"confidence\": 0.83, \"icon_appearance\": \"白色文档带Python图标\"}]"
)


# Task 8.2: 增强版重试提示词
def _build_enhanced_prompt(n: int) -> str:
    """构建增强版重试提示词，动态插入上次返回数量。

    Args:
        n: 上次 API 调用返回的文件数量。

    Returns:
        增强版提示词字符串。
    """
    return (
        _PROMPT_TEMPLATE
        + f"\n\n**重要提示**：上次仅返回了 {n} 个结果，这是不完整的，"
        "请重新仔细扫描整张截图并返回所有文件，不要遗漏任何一个。"
    )


class QwenVLAPIError(Exception):
    """Qwen-VL API 调用失败时抛出。

    触发条件：
    - DASHSCOPE_API_KEY 未设置
    - API 返回非 200 状态码
    """


@dataclass
class VisionFileItem:
    """Qwen-VL 识别的单个文件结果。

    Attributes:
        name: 文件名（含扩展名）；模型未返回或为空时为 None。
        file_type: 文件类型枚举字符串（PDF/Word/Excel/PowerPoint/Image/Video/
                   Audio/Archive/Code/Folder/Other）。
        bbox: 图标边界框 (x, y, width, height)，逻辑坐标。
        center: 图标中心点 (cx, cy)，逻辑坐标；由 __post_init__ 自动计算。
        confidence: 模型返回的置信度，范围 0.0~1.0；缺失时默认 0.5。
        icon_appearance: 图标视觉外观描述（<=50字符）；缺失时为 None。
    """

    name: str | None
    file_type: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int] = field(default_factory=lambda: (0, 0))
    confidence: float = 0.5
    icon_appearance: str | None = None

    def __post_init__(self) -> None:
        x, y, w, h = self.bbox
        self.center = (x + w // 2, y + h // 2)


class QwenVLRecognizer:
    """Qwen-VL 视觉文件识别器。

    截图预处理 -> base64 编码 -> 构造提示词 -> 调用 Qwen-VL API ->
    解析 JSON -> 坐标转换 -> 写入 DetectionCache -> 返回 list[VisionFileItem]。
    """

    def __init__(
        self,
        dpi_adapter: object | None = None,
        detection_cache: DetectionCache | None = None,
        monitor_index: int = 0,
    ) -> None:
        """初始化 QwenVLRecognizer。

        Args:
            dpi_adapter: DPIAdapter 实例，用于逻辑坐标转换；为 None 时不做 DPI 转换。
            detection_cache: DetectionCache 实例，识别结果写入此缓存；为 None 时跳过写入。
            monitor_index: 显示器索引，传递给 DPIAdapter.to_logical()。
        """
        self._dpi_adapter = dpi_adapter
        self._detection_cache = detection_cache
        self._monitor_index = monitor_index
        self._scale_ratio: float = 1.0

        # 一次性读取所有配置
        vision_cfg: dict = {}
        vision_box_cfg: dict = {}
        try:
            with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            vision_cfg = data.get("vision", {}) or {}
            vision_box_cfg = data.get("vision_box", {}) or {}
        except Exception as exc:
            logger.warning("读取 settings.yaml 失败，使用全部默认值: %s", exc)

        # 模型名称
        self._model = vision_cfg.get("qwen_vl_model", "qwen3-vl-plus")

        # vision_box.enabled
        self._vision_box_enabled: bool = bool(vision_box_cfg.get("enabled", True))

        # max_tokens（带范围校验）
        try:
            max_tokens = int(vision_cfg.get("qwen_vl_max_tokens", 4096))
            if max_tokens < 1024 or max_tokens > 8192:
                logger.warning("qwen_vl_max_tokens=%d 超出范围 [1024,8192]，使用默认值 4096", max_tokens)
                max_tokens = 4096
        except (TypeError, ValueError):
            logger.warning("qwen_vl_max_tokens 类型非法，使用默认值 4096")
            max_tokens = 4096
        self._max_tokens: int = max_tokens

        # temperature
        try:
            self._temperature: float = float(vision_cfg.get("qwen_vl_temperature", 0.1))
        except (TypeError, ValueError):
            logger.warning("qwen_vl_temperature 类型非法，使用默认值 0.1")
            self._temperature = 0.1

        # chunk_height
        try:
            self._chunk_height: int = int(vision_cfg.get("chunk_height", 1000))
        except (TypeError, ValueError):
            logger.warning("chunk_height 类型非法，使用默认值 1000")
            self._chunk_height = 1000

        # chunk_overlap
        try:
            self._chunk_overlap: int = int(vision_cfg.get("chunk_overlap", 100))
        except (TypeError, ValueError):
            logger.warning("chunk_overlap 类型非法，使用默认值 100")
            self._chunk_overlap = 100

        # nms_iou_threshold
        try:
            self._nms_iou_threshold: float = float(vision_cfg.get("nms_iou_threshold", 0.5))
        except (TypeError, ValueError):
            logger.warning("nms_iou_threshold 类型非法，使用默认值 0.5")
            self._nms_iou_threshold = 0.5

        # chunk_trigger_height
        try:
            self._chunk_trigger_height: int = int(vision_cfg.get("chunk_trigger_height", 2000))
        except (TypeError, ValueError):
            logger.warning("chunk_trigger_height 类型非法，使用默认值 2000")
            self._chunk_trigger_height = 2000

    def _preprocess_screenshot(self, bgr: np.ndarray) -> np.ndarray:
        """对截图进行预处理：小图放大提升清晰度，大图缩小减少 token。

        - 宽 > 1920 或高 > 1080：用 INTER_AREA 等比缩小至 1920x1080 以内（优先检查）
        - 宽 < 800 且高 < 600（且不超出上限）：用 INTER_CUBIC 放大到至少 800x600
        - 记录 scale_ratio 供后续坐标还原使用。
        """
        h, w = bgr.shape[:2]

        # 优先处理超大图：缩小至 1920x1080 以内
        if w > 1920 or h > 1080:
            ratio = min(1920 / w, 1080 / h)
            new_w = max(1, int(w * ratio))
            new_h = max(1, int(h * ratio))
            resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
            self._scale_ratio = ratio
            logger.debug(
                "_preprocess_screenshot: 缩放 %dx%d -> %dx%d (ratio=%.4f)",
                w, h, new_w, new_h, ratio,
            )
            return resized

        # 小图放大提升清晰度（仅在不超出上限时）
        if w < 800 or h < 600:
            scale = max(800 / w, 600 / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            self._scale_ratio = scale
            logger.debug(
                "_preprocess_screenshot: 放大 %dx%d -> %dx%d (ratio=%.4f)",
                w, h, new_w, new_h, scale,
            )
            return resized

        self._scale_ratio = 1.0
        return bgr

    def _encode_to_base64(self, img: np.ndarray) -> str:
        """将图像编码为 base64 PNG 字符串（内联格式）。"""
        success, buf = cv2.imencode(".png", img)
        if not success:
            raise RuntimeError("cv2.imencode 失败")
        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    # Task 4.1: NMS 去重
    @staticmethod
    def apply_nms(
        items: list[VisionFileItem],
        iou_threshold: float,
    ) -> list[VisionFileItem]:
        """对识别结果执行非极大值抑制（NMS）。

        Args:
            items: 输入识别结果列表。
            iou_threshold: IoU 阈值，范围 [0.0, 1.0]。

        Returns:
            去重后的列表，长度 <= 输入长度。

        Raises:
            ValueError: iou_threshold 不在 [0.0, 1.0] 范围内。
        """
        if iou_threshold < 0.0 or iou_threshold > 1.0:
            raise ValueError(
                f"iou_threshold={iou_threshold} 不在合法范围 [0.0, 1.0] 内"
            )
        if not items:
            return []

        sorted_items = sorted(items, key=lambda x: x.confidence, reverse=True)
        kept: list[VisionFileItem] = []

        for candidate in sorted_items:
            suppressed = False
            for kept_item in kept:
                if QwenVLRecognizer._compute_iou(candidate.bbox, kept_item.bbox) > iou_threshold:
                    suppressed = True
                    break
            if not suppressed:
                kept.append(candidate)

        return kept

    @staticmethod
    def _compute_iou(
        bbox_a: tuple[int, int, int, int],
        bbox_b: tuple[int, int, int, int],
    ) -> float:
        """计算两个 bbox 的 IoU。bbox 格式为 (x, y, w, h)。"""
        ax, ay, aw, ah = bbox_a
        bx, by, bw, bh = bbox_b

        inter_x1 = max(ax, bx)
        inter_y1 = max(ay, by)
        inter_x2 = min(ax + aw, bx + bw)
        inter_y2 = min(ay + ah, by + bh)

        inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
        union_area = aw * ah + bw * bh - inter_area

        if union_area <= 0:
            return 0.0
        return inter_area / union_area

    # Task 5.1: Explorer 区域裁剪
    def crop_explorer_file_list(
        self,
        bgr: np.ndarray,
        window_rect: tuple[int, int, int, int] | None,
    ) -> tuple[np.ndarray, int, int]:
        """从 Explorer 截图中裁剪出 File_List_Region。

        Args:
            bgr: 原始截图（BGR）。
            window_rect: Explorer 窗口矩形 (x, y, w, h)；None 时使用启发式裁剪。

        Returns:
            (cropped_bgr, crop_offset_x, crop_offset_y)
            若裁剪后尺寸 < 100x100，返回原图和 (0, 0)。
        """
        h, w = bgr.shape[:2]

        if window_rect is not None:
            wx, wy, ww, wh = window_rect
            top_offset = 120
            bottom_offset = 40
            y1 = wy + top_offset
            y2 = wy + wh - bottom_offset
            x1 = wx
            x2 = wx + ww
            y1 = max(0, min(y1, h))
            y2 = max(0, min(y2, h))
            x1 = max(0, min(x1, w))
            x2 = max(0, min(x2, w))
            cropped = bgr[y1:y2, x1:x2]
            crop_offset_x, crop_offset_y = x1, y1
        else:
            top_cut = min(120, h)
            bottom_cut = min(40, h - top_cut)
            y1 = top_cut
            y2 = h - bottom_cut
            cropped = bgr[y1:y2, 0:w]
            crop_offset_x, crop_offset_y = 0, y1

        ch, cw = cropped.shape[:2]
        if ch < 100 or cw < 100:
            logger.warning(
                "crop_explorer_file_list: 裁剪后尺寸 %dx%d < 100x100，返回原图",
                cw, ch,
            )
            return bgr, 0, 0

        logger.debug(
            "crop_explorer_file_list: 裁剪 %dx%d -> %dx%d, offset=(%d,%d)",
            w, h, cw, ch, crop_offset_x, crop_offset_y,
        )
        return cropped, crop_offset_x, crop_offset_y

    # Task 6.1: 分块识别
    def recognize_in_chunks(
        self,
        image: np.ndarray,
        chunk_height: int,
        overlap: int,
        api_key: str,
        prompt: str,
    ) -> list[VisionFileItem]:
        """将图像分块识别并合并结果（未做 NMS）。

        Args:
            image: 待识别图像（BGR）。
            chunk_height: 每块高度（像素）。
            overlap: 相邻块重叠像素数。
            api_key: DashScope API Key。
            prompt: 使用的提示词。

        Returns:
            合并后的 VisionFileItem 列表（已叠加 y 偏移）。
        """
        from openai import OpenAI  # noqa: PLC0415

        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        h, w = image.shape[:2]
        step = max(1, chunk_height - overlap)
        chunks: list[tuple[int, int]] = []
        y = 0
        while y < h:
            y_end = min(y + chunk_height, h)
            chunks.append((y, y_end))
            if y_end >= h:
                break
            y += step

        logger.info("recognize_in_chunks: 图像高度=%d，分 %d 块处理", h, len(chunks))

        all_items: list[VisionFileItem] = []
        for idx, (y_start, y_end) in enumerate(chunks):
            chunk_img = image[y_start:y_end, 0:w]
            try:
                processed = self._preprocess_screenshot(chunk_img)
                b64_url = self._encode_to_base64(processed)
                # b64_url 已含 "data:image/png;base64," 前缀
                response = client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": b64_url}},
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    temperature=self._temperature,
                    top_p=0.9,
                    max_tokens=self._max_tokens,
                )
                text = response.choices[0].message.content or ""

                chunk_items = self._parse_response(text)

                offset_items: list[VisionFileItem] = []
                for item in chunk_items:
                    x, y_coord, bw, bh = item.bbox
                    new_bbox = (x, y_coord + y_start, bw, bh)
                    offset_items.append(VisionFileItem(
                        name=item.name,
                        file_type=item.file_type,
                        bbox=new_bbox,
                        confidence=item.confidence,
                        icon_appearance=item.icon_appearance,
                    ))
                all_items.extend(offset_items)
                logger.info("recognize_in_chunks: 第 %d 块识别 %d 个文件", idx, len(chunk_items))

            except Exception as exc:
                logger.error("recognize_in_chunks: 第 %d 块处理失败，跳过: %s", idx, exc)
                continue

        return all_items

    # Task 7.1: 图标外观联合判断
    @staticmethod
    def _reconcile_type(
        file_type_from_name: str,
        file_type_from_icon: str,
        icon_appearance: str | None,
    ) -> str:
        """联合文件名扩展名推断类型与图标外观推断类型。

        规则（优先级从高到低）：
        1. icon_appearance 为 None 或空 -> 直接返回 file_type_from_name
        2. 两者一致 -> 直接采用
        3. 两者不一致且 file_type_from_name != "Other" -> 优先采用文件名推断类型
        4. file_type_from_name == "Other" -> 采用图标外观推断类型
        """
        if not icon_appearance:
            return file_type_from_name

        if file_type_from_name == file_type_from_icon:
            return file_type_from_name

        if file_type_from_name != "Other":
            logger.debug(
                "_reconcile_type: 类型冲突 name_type=%s icon_type=%s，采用文件名推断类型",
                file_type_from_name, file_type_from_icon,
            )
            return file_type_from_name

        logger.debug(
            "_reconcile_type: 图标外观辅助修正 file_type: 原类型=%s, 修正为=%s, icon_appearance=%s",
            file_type_from_name, file_type_from_icon, icon_appearance,
        )
        return file_type_from_icon

    @staticmethod
    def _infer_type_from_appearance(appearance: str | None) -> str:
        """从图标外观描述推断文件类型。"""
        if not appearance:
            return "Other"
        a = appearance.lower()
        if "pdf" in a or "红色矩形" in a:
            return "PDF"
        if "word" in a or "蓝色w" in a or "蓝色 w" in a:
            return "Word"
        if "excel" in a or "绿色x" in a or "绿色 x" in a:
            return "Excel"
        if "powerpoint" in a or "ppt" in a or "橙色p" in a or "橙色 p" in a:
            return "PowerPoint"
        if "txt" in a or "文字行条纹" in a or "纯文本" in a:
            return "Other"
        if "文件夹" in a or "folder" in a or "黄色" in a:
            return "Folder"
        if "图片" in a or "缩略图" in a or "image" in a or "山景" in a:
            return "Image"
        if "压缩" in a or "zip" in a or "rar" in a or "拉链" in a:
            return "Archive"
        if "代码" in a or "python" in a or "js" in a or "齿轮" in a:
            return "Code"
        if "视频" in a or "video" in a or "mp4" in a:
            return "Video"
        if "音频" in a or "audio" in a or "mp3" in a:
            return "Audio"
        return "Other"

    # Task 9.1: 扩展 _parse_response
    def _parse_response(self, text: str) -> list[VisionFileItem]:
        """解析 Qwen-VL 返回的 JSON 文本为 VisionFileItem 列表。

        自动去除 markdown 代码块包裹，逐元素容错解析。

        Args:
            text: API 返回的原始文本。

        Returns:
            解析成功的 VisionFileItem 列表；JSON 解析失败时返回 []。
        """
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        cleaned = cleaned.strip()

        try:
            raw_list = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Qwen-VL 返回非法 JSON，返回 []。原始响应前 500 字符: %s... 错误: %s",
                text[:500],
                exc,
            )
            return []

        if not isinstance(raw_list, list):
            logger.warning("Qwen-VL 返回非列表 JSON，返回 []。类型: %s", type(raw_list))
            return []

        items: list[VisionFileItem] = []
        for elem in raw_list:
            if not isinstance(elem, dict):
                logger.warning("跳过非 dict 元素: %r", elem)
                continue

            raw_bbox = elem.get("bbox")
            if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                logger.warning("跳过 bbox 格式非法元素（非 4 元素列表）: %r", elem)
                continue
            try:
                bx1, by1, bx2, by2 = [int(v) for v in raw_bbox]
            except (TypeError, ValueError):
                logger.warning("跳过 bbox 含非数值元素: %r", elem)
                continue
            if bx1 < 0 or by1 < 0 or bx2 < 0 or by2 < 0:
                logger.warning("跳过 bbox 含负数坐标元素: %r", elem)
                continue

            if self._scale_ratio != 1.0:
                r = self._scale_ratio
                bx1 = int(round(bx1 / r))
                by1 = int(round(by1 / r))
                bx2 = int(round(bx2 / r))
                by2 = int(round(by2 / r))

            if self._dpi_adapter is not None:
                try:
                    lx1, ly1 = self._dpi_adapter.to_logical(bx1, by1, self._monitor_index)
                    lx2, ly2 = self._dpi_adapter.to_logical(bx2, by2, self._monitor_index)
                    bx1, by1, bx2, by2 = lx1, ly1, lx2, ly2
                except Exception as exc:
                    logger.debug("DPI 转换失败，使用原始坐标: %s", exc)

            bbox = (bx1, by1, bx2 - bx1, by2 - by1)

            raw_type = elem.get("type", "Other")
            _TYPE_ALIAS: dict[str, str] = {
                "pdf": "PDF", "doc": "Word", "docx": "Word", "word": "Word",
                "xls": "Excel", "xlsx": "Excel", "excel": "Excel",
                "ppt": "PowerPoint", "pptx": "PowerPoint", "powerpoint": "PowerPoint",
                "jpg": "Image", "jpeg": "Image", "png": "Image", "gif": "Image",
                "bmp": "Image", "webp": "Image", "image": "Image",
                "mp4": "Video", "avi": "Video", "mkv": "Video", "video": "Video",
                "mp3": "Audio", "wav": "Audio", "flac": "Audio", "audio": "Audio",
                "zip": "Archive", "rar": "Archive", "7z": "Archive", "archive": "Archive",
                "py": "Code", "js": "Code", "ts": "Code", "java": "Code", "code": "Code",
                "folder": "Folder", "file": "Other",
            }
            normalized_type = _TYPE_ALIAS.get(str(raw_type).lower(), raw_type)
            file_type = normalized_type if normalized_type in _VALID_FILE_TYPES else "Other"
            if normalized_type not in _VALID_FILE_TYPES:
                logger.debug("未知 type \"%s\"，设为 \"Other\"", raw_type)

            raw_name = elem.get("name")
            if not raw_name:
                logger.warning("元素缺少 name 或 name 为空，设为 None: %r", elem)
                name: str | None = None
            else:
                name = str(raw_name)

            raw_conf = elem.get("confidence")
            if raw_conf is None:
                confidence = 0.5
            else:
                try:
                    confidence = float(raw_conf)
                except (TypeError, ValueError):
                    confidence = 0.5

            # Task 9.1: 提取 icon_appearance 并联合判断类型
            raw_appearance = elem.get("icon_appearance")
            icon_appearance: str | None = str(raw_appearance)[:50] if raw_appearance else None

            icon_type = QwenVLRecognizer._infer_type_from_appearance(icon_appearance)
            final_file_type = QwenVLRecognizer._reconcile_type(file_type, icon_type, icon_appearance)

            item = VisionFileItem(
                name=name,
                file_type=final_file_type,
                bbox=bbox,
                confidence=confidence,
                icon_appearance=icon_appearance,
            )
            items.append(item)

        return items

    # Task 10.1-10.5: 修改 recognize_file_icons 主方法
    def recognize_file_icons(
        self,
        screenshot_bgr: np.ndarray,
        min_expected: int | None = None,
        window_rect: tuple[int, int, int, int] | None = None,
    ) -> list[VisionFileItem]:
        """对截图执行 Qwen-VL 文件识别。

        Args:
            screenshot_bgr: BGR uint8 numpy 数组（物理像素）。
            min_expected: 最小期望识别数量；不足时触发智能重试。为 None 时跳过智能重试。
            window_rect: Explorer 窗口矩形 (x, y, w, h)；为 None 时使用启发式裁剪。

        Returns:
            VisionFileItem 列表，坐标为逻辑坐标。

        Raises:
            QwenVLAPIError: API Key 缺失或 API 返回非 200 状态码。
        """
        # 1. API Key 检查
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise QwenVLAPIError("DASHSCOPE_API_KEY 未设置，无法调用 Qwen-VL API")

        from openai import OpenAI  # noqa: PLC0415

        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        # 2. Task 10.2: 裁剪 Explorer 文件列表区域
        cropped, crop_offset_x, crop_offset_y = self.crop_explorer_file_list(
            screenshot_bgr, window_rect
        )

        # 3. 预处理
        processed = self._preprocess_screenshot(cropped)

        # 4. base64 编码
        b64_url = self._encode_to_base64(processed)

        # 5. Task 10.3: 判断是否需要分块识别
        cropped_h = cropped.shape[0]
        items: list[VisionFileItem] = []

        if cropped_h > self._chunk_trigger_height:
            logger.info(
                "recognize_file_icons: 裁剪图高度 %d > chunk_trigger_height %d，启用分块识别",
                cropped_h, self._chunk_trigger_height,
            )
            # 分块识别（内部会调用 _preprocess_screenshot，会更新 _scale_ratio）
            raw_items = self.recognize_in_chunks(
                image=cropped,
                chunk_height=self._chunk_height,
                overlap=self._chunk_overlap,
                api_key=api_key,
                prompt=_PROMPT_TEMPLATE,
            )
            # 分块结果已叠加 chunk y 偏移，但坐标仍是 cropped 坐标系
            # 需要叠加 crop_offset（在 scale_ratio 还原之后）
            # 注意：recognize_in_chunks 内部调用 _parse_response，_parse_response 已做 scale_ratio 还原
            # 所以这里直接叠加 crop_offset
            offset_items: list[VisionFileItem] = []
            for item in raw_items:
                x, y, w, h = item.bbox
                new_bbox = (x + crop_offset_x, y + crop_offset_y, w, h)
                offset_items.append(VisionFileItem(
                    name=item.name,
                    file_type=item.file_type,
                    bbox=new_bbox,
                    confidence=item.confidence,
                    icon_appearance=item.icon_appearance,
                ))
            items = offset_items
        else:
            # 单次 API 调用
            messages_payload = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": b64_url}},
                        {"type": "text", "text": _PROMPT_TEMPLATE},
                    ],
                }
            ]

            response = None
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    response = client.chat.completions.create(
                        model=self._model,
                        messages=messages_payload,
                        temperature=self._temperature,
                        top_p=0.9,
                        max_tokens=self._max_tokens,
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "Qwen-VL 第 %d 次调用异常: %s，%s",
                        attempt + 1, exc, "重试..." if attempt == 0 else "放弃",
                    )

            if response is None:
                raise QwenVLAPIError(f"Qwen-VL API 调用失败: {last_exc}")

            try:
                text = response.choices[0].message.content or ""
            except Exception as exc:
                logger.warning("提取 Qwen-VL 响应文本失败，返回 []: %s", exc)
                return []

            # _parse_response 已做 scale_ratio 还原和 DPI 转换
            raw_items = self._parse_response(text)

            # 叠加 crop_offset
            offset_items = []
            for item in raw_items:
                x, y, w, h = item.bbox
                new_bbox = (x + crop_offset_x, y + crop_offset_y, w, h)
                offset_items.append(VisionFileItem(
                    name=item.name,
                    file_type=item.file_type,
                    bbox=new_bbox,
                    confidence=item.confidence,
                    icon_appearance=item.icon_appearance,
                ))
            items = offset_items

        # 6. NMS 去重
        before_nms = len(items)
        items = self.apply_nms(items, self._nms_iou_threshold)
        logger.info(
            "recognize_file_icons: NMS 前 %d 个，NMS 后 %d 个（iou_threshold=%.2f）",
            before_nms, len(items), self._nms_iou_threshold,
        )

        # 7. Task 10.4: 智能重试
        if min_expected is not None and len(items) < min_expected:
            first_count = len(items)
            logger.info(
                "recognize_file_icons: 首次识别 %d 个 < min_expected=%d，触发智能重试",
                first_count, min_expected,
            )
            enhanced_prompt = _build_enhanced_prompt(first_count)

            # 重新预处理裁剪图（重置 scale_ratio）
            processed_retry = self._preprocess_screenshot(cropped)
            b64_url_retry = self._encode_to_base64(processed_retry)

            retry_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": b64_url_retry}},
                        {"type": "text", "text": enhanced_prompt},
                    ],
                }
            ]
            try:
                retry_response = client.chat.completions.create(
                    model=self._model,
                    messages=retry_messages,
                    temperature=self._temperature,
                    top_p=0.9,
                    max_tokens=self._max_tokens,
                )
                retry_text = retry_response.choices[0].message.content or ""

                retry_raw = self._parse_response(retry_text)
                retry_offset: list[VisionFileItem] = []
                for item in retry_raw:
                    x, y, w, h = item.bbox
                    new_bbox = (x + crop_offset_x, y + crop_offset_y, w, h)
                    retry_offset.append(VisionFileItem(
                        name=item.name,
                        file_type=item.file_type,
                        bbox=new_bbox,
                        confidence=item.confidence,
                        icon_appearance=item.icon_appearance,
                    ))
                retry_items = self.apply_nms(retry_offset, self._nms_iou_threshold)
                retry_count = len(retry_items)

                if retry_count > first_count:
                    logger.info(
                        "recognize_file_icons: 智能重试改善结果 %d -> %d，使用重试结果",
                        first_count, retry_count,
                    )
                    items = retry_items
                else:
                    logger.warning(
                        "recognize_file_icons: 智能重试未改善结果（重试=%d，首次=%d），保留首次结果",
                        retry_count, first_count,
                    )
            except Exception as exc:
                logger.warning("recognize_file_icons: 智能重试失败，保留首次结果: %s", exc)

        # 8. 写入 DetectionCache
        if self._detection_cache is not None and self._vision_box_enabled:
            from automation.vision_box_drawer import BoundingBoxDict  # noqa: PLC0415
            boxes = [
                BoundingBoxDict(
                    bbox=[
                        item.bbox[0],
                        item.bbox[1],
                        item.bbox[0] + item.bbox[2],
                        item.bbox[1] + item.bbox[3],
                    ],
                    label=item.name or item.file_type,
                    confidence=item.confidence,
                )
                for item in items
            ]
            self._detection_cache.update(boxes)
            logger.debug("写入 DetectionCache: %d 个识别框", len(boxes))

        logger.info("Qwen-VL 识别完成，共 %d 个文件项", len(items))
        return items
