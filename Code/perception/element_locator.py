"""感知层：GUI 元素定位模块，实现多策略优先级降级链。"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 阿里云视觉策略已永久禁用：DetectImageElements API 已下线，对应 SDK 不再维护。
# 降级链直接从 Qwen-VL 开始。
_ALIYUN_SDK_AVAILABLE: bool = False


@dataclass
class ElementResult:
    """成功识别的 GUI 元素结果。

    Attributes:
        name: 元素名称或文本标签
        bbox: 边界框 (x, y, width, height)，逻辑坐标
        confidence: 识别置信度，范围 0.0 ~ 1.0
        strategy: 使用的识别策略名称
    """

    name: str
    bbox: tuple[int, int, int, int]
    confidence: float
    strategy: str


class ElementNotFoundError(Exception):
    """所有识别策略均失败时抛出。

    Attributes:
        message: 失败原因描述
        tried_strategies: 已尝试的策略列表
    """

    def __init__(self, message: str, tried_strategies: list[str] | None = None) -> None:
        super().__init__(message)
        self.tried_strategies: list[str] = tried_strategies or []

    def __str__(self) -> str:
        base = super().__str__()
        if self.tried_strategies:
            return f"{base} (tried: {', '.join(self.tried_strategies)})"
        return base


class ElementLocator:
    """GUI 元素定位器，按优先级降级链识别屏幕元素。

    降级链顺序（优先级从高到低）：
    1. 阿里云视觉智能平台 DetectImageElements
    2. 通义千问 Qwen-VL 多模态理解
    3. Tesseract OCR
    4. OpenCV 模板匹配
    5. 经验坐标偏移（兜底）
    """

    def __init__(self) -> None:
        self._access_key_id: str = os.environ.get("ALIYUN_ACCESS_KEY_ID", "")
        self._access_key_secret: str = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")
        # 复用 DPIAdapter 实例，避免每次定位都重新枚举显示器
        from perception.dpi_adapter import DPIAdapter as _DPIAdapter
        self._dpi = _DPIAdapter()

    # ------------------------------------------------------------------
    # 策略 0：pywinauto 控件 API（仅用于标准 Win32 安装窗口）
    # ------------------------------------------------------------------

    def _locate_by_pywinauto(
        self,
        element_description: str,
        window_title_hint: str = "",
    ) -> ElementResult | None:
        """使用 pywinauto 枚举 Win32 控件，精确定位按钮（优先级 0）。

        直接读取控件的屏幕物理坐标，不依赖视觉识别，精度最高。
        仅适用于标准 Win32/MFC 安装窗口（NSIS、Inno Setup 等）。
        Electron/自定义渲染窗口不适用，失败时静默返回 None 触发降级。

        Args:
            element_description: 目标按钮文字（支持部分匹配，如"下一步"匹配"下一步(N)"）。
            window_title_hint: 安装窗口标题关键词，用于快速定位窗口。

        Returns:
            识别成功时返回 :class:`ElementResult`（strategy="pywinauto"，逻辑坐标）；
            失败时返回 ``None``。
        """
        try:
            from pywinauto import Application  # type: ignore[import-untyped]

            title_re = f".*{window_title_hint}.*" if window_title_hint else ".*安装.*|.*Setup.*|.*Install.*"
            app = Application(backend="win32").connect(title_re=title_re, timeout=2)
            win = app.top_window()

            for ctrl in win.descendants():
                try:
                    if ctrl.friendly_class_name() != "Button":
                        continue
                    txt = ctrl.window_text().strip()
                    if not txt:
                        continue
                    # 部分匹配：支持"下一步"匹配"下一步(&N) >"等变体
                    if element_description not in txt:
                        continue

                    rect = ctrl.rectangle()
                    # 屏幕物理坐标 → 逻辑坐标
                    cx_phys = (rect.left + rect.right) // 2
                    cy_phys = (rect.top + rect.bottom) // 2
                    lx, ly = self._dpi.to_logical(cx_phys, cy_phys)
                    w_phys = rect.right - rect.left
                    h_phys = rect.bottom - rect.top
                    lw = max(1, int(round(w_phys / self._dpi.scale_factor)))
                    lh = max(1, int(round(h_phys / self._dpi.scale_factor)))

                    bbox: tuple[int, int, int, int] = (
                        lx - lw // 2,
                        ly - lh // 2,
                        lw,
                        lh,
                    )
                    logger.info(
                        "pywinauto 策略：识别成功。element=%s, text=%r, phys=(%d,%d) -> logical=(%d,%d)",
                        element_description, txt, cx_phys, cy_phys, lx, ly,
                    )
                    return ElementResult(
                        name=txt,
                        bbox=bbox,
                        confidence=1.0,
                        strategy="pywinauto",
                    )
                except Exception:  # noqa: BLE001
                    continue

            logger.debug("pywinauto 策略：未找到按钮 %r，触发降级", element_description)
            return None

        except Exception as exc:  # noqa: BLE001
            logger.debug("pywinauto 策略：不可用，触发降级。error=%s", exc)
            return None

    # ------------------------------------------------------------------
    # 策略 1：阿里云视觉智能平台 DetectImageElements
    # ------------------------------------------------------------------

    def _locate_by_aliyun_vision(
        self,
        screenshot: np.ndarray,
        element_description: str,
    ) -> ElementResult | None:
        """阿里云视觉策略已永久禁用（DetectImageElements API 已下线）。

        直接返回 None，降级到 Qwen-VL 策略。
        """
        return None

    def _call_aliyun_detect_api(
        self,
        b64_image: str,
        element_description: str,
    ) -> dict[str, Any]:
        """调用阿里云视觉智能平台 DetectImageElements API。

        使用阿里云 SDK（alibabacloud-viapi-20230117）进行鉴权和调用。
        若 SDK 未安装，抛出 RuntimeError 触发降级。

        Args:
            b64_image: Base64 编码的 PNG 图像字符串。
            element_description: 目标元素描述。

        Returns:
            包含 ``found``、``coords``（可选）、``confidence``（可选）字段的字典。

        Raises:
            RuntimeError: SDK 未安装、鉴权信息缺失或 API 调用失败时抛出。
        """
        if not self._access_key_id or not self._access_key_secret:
            raise RuntimeError(
                "ALIYUN_ACCESS_KEY_ID 或 ALIYUN_ACCESS_KEY_SECRET 未配置，"
                "无法调用阿里云视觉 API。"
            )

        try:
            # 使用阿里云官方 SDK 进行签名鉴权
            from alibabacloud_viapi20230117 import client as viapi_client  # type: ignore[import-untyped]
            from alibabacloud_viapi20230117 import models as viapi_models  # type: ignore[import-untyped]
            from alibabacloud_tea_openapi import models as open_api_models  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "阿里云视觉 SDK 未安装（alibabacloud-viapi-20230117），"
                "请执行 pip install alibabacloud-viapi-20230117 后重试。"
            ) from exc

        config = open_api_models.Config(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            endpoint="viapi.cn-shanghai.aliyuncs.com",
        )
        sdk_client = viapi_client.Client(config)

        request = viapi_models.DetectImageElementsRequest(
            image_url=f"data:image/png;base64,{b64_image}",
        )

        try:
            response = sdk_client.detect_image_elements(request)
        except Exception as exc:
            raise RuntimeError(f"阿里云 DetectImageElements API 调用失败：{exc}") from exc

        # 解析响应，统一映射为内部格式
        body = response.body
        data = getattr(body, "data", None) or {}
        elements = []
        if hasattr(data, "elements"):
            elements = data.elements or []
        elif isinstance(data, dict):
            elements = data.get("Elements") or data.get("elements") or []

        if not elements:
            return {"found": False, "coords": None}

        first = elements[0]
        # 兼容 SDK 对象属性和字典两种格式
        if hasattr(first, "box"):
            box = first.box
        elif isinstance(first, dict):
            box = first.get("Box") or first.get("box") or first.get("bbox")
        else:
            box = None

        if box is not None:
            if hasattr(box, "x"):
                # SDK 对象格式
                x, y = int(box.x), int(box.y)
                w = int(getattr(box, "width", 1))
                h = int(getattr(box, "height", 1))
            else:
                # 列表格式 [x, y, w, h]
                x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            cx = x + w // 2
            cy = y + h // 2
            score = getattr(first, "score", None) or (
                first.get("Score") or first.get("score") if isinstance(first, dict) else None
            ) or 1.0
            return {
                "found": True,
                "coords": [cx, cy],
                "bbox": [x, y, w, h],
                "confidence": float(score),
            }

        return {"found": True, "coords": None}

    # ------------------------------------------------------------------
    # 策略 2：通义千问 Qwen-VL 多模态理解
    # ------------------------------------------------------------------

    def _locate_by_qwen_vl(
        self,
        screenshot: np.ndarray,
        element_description: str,
    ) -> ElementResult | None:
        """使用 Qwen-VL 多模态模型定位元素（优先级 2）。

        将截图 base64 内联编码后调用 OpenAI 兼容接口，不使用临时文件。
        对响应做双重校验：``found=True`` 且 ``coords is not None``。
        API 异常或校验失败时记录 WARNING 并返回 ``None`` 触发降级。

        重要：Qwen-VL 返回的坐标是图像像素坐标（物理坐标）。
        截图本身是物理像素，所以坐标直接对应物理像素，需要转换为逻辑坐标后再返回。

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组（物理像素）。
            element_description: 目标元素的自然语言描述。

        Returns:
            识别成功时返回 :class:`ElementResult`（逻辑坐标）；失败时返回 ``None``。
        """
        try:
            h_img, w_img = screenshot.shape[:2]

            # 图像预处理：确保分辨率不低于 800x600，提升模型感知细节能力
            processed = screenshot
            scale_ratio = 1.0
            if w_img < 800 or h_img < 600:
                scale_ratio = max(800 / w_img, 600 / h_img)
                new_w = int(w_img * scale_ratio)
                new_h = int(h_img * scale_ratio)
                processed = cv2.resize(screenshot, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                logger.debug(
                    "Qwen-VL 策略：图像放大 %dx%d -> %dx%d (ratio=%.2f)",
                    w_img, h_img, new_w, new_h, scale_ratio,
                )

            success, buf = cv2.imencode(".png", processed)
            if not success:
                logger.warning(
                    "Qwen-VL 策略：图像编码失败，触发降级。element=%s",
                    element_description,
                )
                return None

            b64_image: str = base64.b64encode(buf.tobytes()).decode("utf-8")

            # P7: 传处理后图像的实际尺寸，让模型知道坐标范围
            processed_h, processed_w = processed.shape[:2]
            raw_result = self._call_qwen_vl_api(b64_image, element_description,
                                                img_w=processed_w, img_h=processed_h)

            def _parse_coords(result: dict[str, Any]) -> tuple[int, int] | None:
                """从 API 响应中提取坐标，支持 coords/center/bbox 多种格式。"""
                # 优先取 coords 或 center
                for key in ("coords", "center"):
                    val = result.get(key)
                    if isinstance(val, (list, tuple)) and len(val) >= 2:
                        try:
                            return int(val[0]), int(val[1])
                        except (TypeError, ValueError):
                            pass
                # 从 bbox 推算中心点
                bbox_val = result.get("bbox")
                if isinstance(bbox_val, (list, tuple)) and len(bbox_val) == 4:
                    try:
                        x1, y1, x2, y2 = [int(v) for v in bbox_val]
                        return (x1 + x2) // 2, (y1 + y2) // 2
                    except (TypeError, ValueError):
                        pass
                return None

            def _build_result(cx_phys: int, cy_phys: int, confidence: float) -> ElementResult:
                """将物理坐标中心点还原 scale_ratio 后转换为逻辑坐标，构造 ElementResult。

                步骤：
                1. 除以 scale_ratio 还原图像预处理放大比，得到原始截图物理坐标
                2. 调用 DPIAdapter.to_logical() 将物理坐标转换为逻辑坐标
                   （符合层间逻辑坐标契约：感知层返回值必须为逻辑坐标）
                """
                cx_orig = int(cx_phys / scale_ratio)
                cy_orig = int(cy_phys / scale_ratio)
                # 将物理坐标转换为逻辑坐标，符合层间逻辑坐标契约
                lx, ly = self._dpi.to_logical(cx_orig, cy_orig)
                _DEFAULT_SIZE = 40
                bbox: tuple[int, int, int, int] = (
                    lx - _DEFAULT_SIZE // 2,
                    ly - _DEFAULT_SIZE // 2,
                    _DEFAULT_SIZE,
                    _DEFAULT_SIZE,
                )
                logger.info(
                    "Qwen-VL 策略：识别成功。element=%s, phys=(%d,%d) -> orig=(%d,%d) -> logical=(%d,%d), confidence=%.3f",
                    element_description, cx_phys, cy_phys, cx_orig, cy_orig, lx, ly, confidence,
                )
                return ElementResult(
                    name=element_description,
                    bbox=bbox,
                    confidence=confidence,
                    strategy="qwen_vl",
                )

            # 首次尝试
            if raw_result.get("found"):
                coords = _parse_coords(raw_result)
                if coords is not None:
                    return _build_result(coords[0], coords[1], float(raw_result.get("confidence", 0.9)))

                # found=True 但无坐标 — 重试最多 3 次
                for attempt in range(1, 4):
                    logger.warning(
                        "Qwen-VL 第 %d 次重试（coords=None），element=%s",
                        attempt,
                        element_description,
                    )
                    time.sleep(1)
                    retry_prompt = (
                        f'你是一个精准的UI元素定位模型。截图尺寸为 {w_img}x{h_img} 像素。\n'
                        f'请找到文字为"{element_description}"的按钮。\n\n'
                        f'【严格要求】上次你返回了 found=true 但没有提供坐标，这是不允许的。\n'
                        f'如果元素存在，必须提供像素坐标，不得省略。\n\n'
                        f'只返回一个 JSON 对象，格式如下：\n'
                        f'找到时：{{"found": true, "center": [x, y], "confidence": 0.95}}\n'
                        f'未找到时：{{"found": false, "reason": "原因"}}\n'
                        f'坐标 x 范围 0-{w_img}，y 范围 0-{h_img}，必须为整数。'
                    )
                    retry_result = self._call_qwen_vl_api(b64_image, element_description,
                                                          prompt_override=retry_prompt,
                                                          img_w=w_img, img_h=h_img)
                    if retry_result.get("found"):
                        retry_coords = _parse_coords(retry_result)
                        if retry_coords is not None:
                            logger.info("Qwen-VL 第 %d 次重试成功。element=%s", attempt, element_description)
                            return _build_result(
                                retry_coords[0], retry_coords[1],
                                float(retry_result.get("confidence", 0.9)),
                            )

                logger.warning(
                    "Qwen-VL 策略：3 次重试后仍无坐标，触发降级。element=%s",
                    element_description,
                )
                return None
            else:
                logger.warning(
                    "Qwen-VL 策略：API 返回 found=False，触发降级。element=%s, raw=%s",
                    element_description,
                    raw_result,
                )
                return None

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Qwen-VL 策略：API 调用异常，触发降级。element=%s, error=%s",
                element_description,
                exc,
            )
            return None

    def _call_qwen_vl_api(
        self,
        b64_image: str,
        element_description: str,
        prompt_override: str | None = None,
        img_w: int = 0,
        img_h: int = 0,
    ) -> dict[str, Any]:
        """调用 Qwen-VL 多模态 API（OpenAI 兼容接口）。

        Args:
            b64_image: Base64 编码的 PNG 图像字符串（不含 data URI 前缀）。
            element_description: 目标元素描述（用于构造标准提示词）。
            prompt_override: 若提供，直接使用此提示词，忽略 element_description。

        Returns:
            包含 ``found``、``center``/``coords``（可选）、``confidence``（可选）字段的字典。

        Raises:
            RuntimeError: API 调用失败或响应解析错误时抛出。
        """
        import json
        import re as _re

        from openai import OpenAI

        api_key: str = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法调用 Qwen-VL API。")

        if prompt_override is not None:
            prompt = prompt_override
        else:
            w_str = str(img_w) if img_w > 0 else "未知"
            h_str = str(img_h) if img_h > 0 else "未知"
            x_range = f"0-{img_w}" if img_w > 0 else "图像宽度范围"
            y_range = f"0-{img_h}" if img_h > 0 else "图像高度范围"
            prompt = (
                f'你是一个精准的UI元素定位模型，专门用于定位安装向导中的可点击按钮。\n'
                f'当前截图尺寸：{w_str}x{h_str} 像素（坐标基于此尺寸）。\n'
                f'任务：在截图中找到文字为"{element_description}"的【可点击按钮控件】。\n\n'
                f'重要区分规则：\n'
                f'- 只定位外观为按钮的控件（有边框、背景色、或明显的矩形区域）\n'
                f'- 不要匹配正文段落、说明文字、标题、链接中出现的相同文字\n'
                f'- 按钮通常位于窗口底部或右下角区域\n'
                f'- 如果同一文字在正文和按钮中都出现，只返回按钮的坐标\n\n'
                f'输出规则：\n'
                f'- 只返回一个 JSON 对象，不要任何额外文字或 Markdown\n'
                f'- 找到按钮时：{{"found": true, "center": [x, y], "confidence": 0.95}}\n'
                f'- 未找到按钮时：{{"found": false, "reason": "未找到"}}\n'
                f'- center 是按钮中心点的整数像素坐标，x 范围 {x_range}，y 范围 {y_range}\n\n'
                f'示例输出（找到"下一步"按钮）：\n'
                f'{{"found": true, "center": [743, 512], "confidence": 0.97}}\n\n'
                f'示例输出（未找到）：\n'
                f'{{"found": false, "reason": "截图中没有该按钮"}}'
            )

        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        response = client.chat.completions.create(
            model="qwen3-vl-plus",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0.1,
            top_p=0.9,
            max_tokens=512,
        )

        output_text: str = response.choices[0].message.content or ""
        output_text = output_text.strip()

        # 清理 Markdown 代码块包裹
        if output_text.startswith("```"):
            output_text = _re.sub(r"^```(?:json)?\s*", "", output_text, flags=_re.MULTILINE)
            output_text = _re.sub(r"\s*```$", "", output_text, flags=_re.MULTILINE)
            output_text = output_text.strip()

        # 提取第一个 JSON 对象（防止模型在 JSON 前后输出多余文字）
        json_match = _re.search(r"\{.*\}", output_text, _re.DOTALL)
        if json_match:
            output_text = json_match.group(0)

        try:
            parsed: dict[str, Any] = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Qwen-VL 响应 JSON 解析失败：{exc}，原始输出：{output_text!r}"
            ) from exc

        return parsed

    # ------------------------------------------------------------------
    # 策略 3：Tesseract OCR
    # ------------------------------------------------------------------

    def _locate_by_ocr(
        self,
        screenshot: np.ndarray,
        element_description: str,
    ) -> ElementResult | None:
        """使用 Tesseract OCR 定位元素（优先级 3）。

        在所有匹配项中优先返回"按钮区域"的结果：
        - 优先选屏幕下半部分的匹配（按钮通常在底部）
        - 过滤掉文字块过高的匹配（大段正文，非按钮）
        - 若下半区无匹配，再考虑全屏匹配

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组。
            element_description: 目标元素的自然语言描述（用作 OCR 搜索词）。

        Returns:
            识别成功时返回 :class:`ElementResult`（strategy="ocr"）；
            失败时返回 ``None``。
        """
        try:
            from perception.ocr_helper import OCRHelper
            ocr = OCRHelper()
            # 收集所有匹配项，按钮区域优先
            result = ocr.find_button_bbox(screenshot, element_description)
            if result is not None:
                logger.info(
                    "OCR 策略：识别成功。element=%s, bbox=%s, confidence=%.3f",
                    element_description,
                    result.bbox,
                    result.confidence,
                )
                return ElementResult(
                    name=result.name,
                    bbox=result.bbox,
                    confidence=result.confidence,
                    strategy="ocr",
                )
            logger.warning(
                "OCR 策略：未找到目标按钮，触发降级。element=%s",
                element_description,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "OCR 策略：调用异常，触发降级。element=%s, error=%s",
                element_description,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # 策略 4：OpenCV 模板匹配
    # ------------------------------------------------------------------

    def _locate_by_template(
        self,
        screenshot: np.ndarray,
        template: np.ndarray,
        element_description: str,
        threshold: float = 0.8,
    ) -> ElementResult | None:
        """使用 OpenCV 模板匹配定位元素（优先级 4）。

        使用 ``cv2.matchTemplate`` 在截图中搜索模板图像，置信度低于
        ``threshold`` 时返回 ``None``。

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组。
            template: 模板图像，BGR numpy 数组。
            element_description: 目标元素描述（用于日志）。
            threshold: 最低置信度阈值，默认 0.8。

        Returns:
            匹配成功时返回 :class:`ElementResult`（strategy="template"）；
            置信度不足或异常时返回 ``None``。
        """
        try:
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                logger.warning(
                    "模板匹配策略：置信度 %.3f 低于阈值 %.3f，触发降级。element=%s",
                    max_val,
                    threshold,
                    element_description,
                )
                return None

            h, w = template.shape[:2]
            x, y = int(max_loc[0]), int(max_loc[1])
            bbox: tuple[int, int, int, int] = (x, y, w, h)

            logger.info(
                "模板匹配策略：识别成功。element=%s, bbox=%s, confidence=%.3f",
                element_description,
                bbox,
                max_val,
            )
            return ElementResult(
                name=element_description,
                bbox=bbox,
                confidence=float(max_val),
                strategy="template",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "模板匹配策略：调用异常，触发降级。element=%s, error=%s",
                element_description,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # 策略 5：经验坐标偏移（兜底）
    # ------------------------------------------------------------------

    def _locate_by_experience(
        self,
        element_description: str,
        experience_coords: tuple[int, int],
    ) -> ElementResult | None:
        """使用经验坐标偏移作为兜底策略（优先级 5）。

        当所有其他策略均失败时，使用预先记录的经验坐标直接返回结果。
        置信度固定为 0.3，表示低可信度。

        Args:
            element_description: 目标元素描述。
            experience_coords: 经验坐标 (x, y)，逻辑坐标。

        Returns:
            始终返回 :class:`ElementResult`（strategy="experience"）。
        """
        x, y = experience_coords
        bbox: tuple[int, int, int, int] = (x, y, 1, 1)
        logger.info(
            "经验坐标策略：使用兜底坐标。element=%s, coords=(%d, %d)",
            element_description,
            x,
            y,
        )
        return ElementResult(
            name=element_description,
            bbox=bbox,
            confidence=0.3,
            strategy="experience",
        )

    # ------------------------------------------------------------------
    # 公共接口：降级链编排
    # ------------------------------------------------------------------

    def locate_by_text(
        self,
        screenshot: np.ndarray,
        element_description: str,
        experience_coords: tuple[int, int] | None = None,
    ) -> ElementResult:
        """按优先级降级链定位文本描述的 GUI 元素（视觉模式）。

        依次尝试：阿里云视觉 → Qwen-VL → Tesseract OCR → 经验坐标（若提供）。
        高优先级策略成功时立即返回，不调用后续策略。
        全部失败时抛出 :class:`ElementNotFoundError`。

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组。
            element_description: 目标元素的自然语言描述。
            experience_coords: 可选的经验坐标 (x, y)，作为最终兜底。

        Returns:
            识别成功的 :class:`ElementResult`。

        Raises:
            ElementNotFoundError: 所有策略均失败且无经验坐标时抛出。
        """
        tried: list[str] = []

        # 策略 1：阿里云视觉
        tried.append("aliyun_vision")
        result = self._locate_by_aliyun_vision(screenshot, element_description)
        if result is not None:
            return result

        # 策略 2：Qwen-VL
        tried.append("qwen_vl")
        result = self._locate_by_qwen_vl(screenshot, element_description)
        if result is not None:
            return result

        # 策略 3：Tesseract OCR
        tried.append("ocr")
        result = self._locate_by_ocr(screenshot, element_description)
        if result is not None:
            return result

        # 策略 5：经验坐标（兜底）
        if experience_coords is not None:
            tried.append("experience")
            return self._locate_by_experience(element_description, experience_coords)

        raise ElementNotFoundError(
            f"无法定位元素：{element_description!r}",
            tried_strategies=tried,
        )

    def locate_by_text_silent(
        self,
        element_description: str,
        window_title_hint: str = "",
    ) -> ElementResult:
        """静默模式：仅用 pywinauto 控件 API 定位，不调用视觉 API。

        适用于静默安装场景，速度最快，精度最高，无 API 费用。
        仅支持标准 Win32 窗口；不支持时抛出 ElementNotFoundError。

        Args:
            element_description: 目标按钮文字。
            window_title_hint: 安装窗口标题关键词。

        Returns:
            识别成功的 :class:`ElementResult`（strategy="pywinauto"）。

        Raises:
            ElementNotFoundError: pywinauto 不可用或未找到按钮时抛出。
        """
        result = self._locate_by_pywinauto(element_description, window_title_hint)
        if result is not None:
            return result
        raise ElementNotFoundError(
            f"静默模式：无法通过控件 API 定位元素 {element_description!r}",
            tried_strategies=["pywinauto"],
        )

    def locate_by_text_visual_with_fallback(
        self,
        screenshot: np.ndarray,
        element_description: str,
        window_title_hint: str = "",
        experience_coords: tuple[int, int] | None = None,
    ) -> ElementResult:
        """视觉优先 + pywinauto 兜底模式（展示模式）。

        流程：
        1. 先尝试纯视觉（Qwen-VL / OCR）
        2. 视觉失败时，用 pywinauto 获取精确坐标，strategy 标记为 "pywinauto_fallback"
        3. 全部失败时抛出 ElementNotFoundError

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组。
            element_description: 目标按钮文字。
            window_title_hint: 安装窗口标题关键词（用于 pywinauto 兜底）。
            experience_coords: 最终兜底坐标。

        Returns:
            识别成功的 :class:`ElementResult`。

        Raises:
            ElementNotFoundError: 所有策略均失败时抛出。
        """
        tried: list[str] = []

        # 阶段1：纯视觉
        tried.append("aliyun_vision")
        result = self._locate_by_aliyun_vision(screenshot, element_description)
        if result is not None:
            return result

        tried.append("qwen_vl")
        result = self._locate_by_qwen_vl(screenshot, element_description)
        if result is not None:
            return result

        tried.append("ocr")
        result = self._locate_by_ocr(screenshot, element_description)
        if result is not None:
            return result

        # 阶段2：pywinauto 兜底（坐标精确，但 strategy 标记为 fallback 供 UI 区分显示）
        tried.append("pywinauto_fallback")
        pw_result = self._locate_by_pywinauto(element_description, window_title_hint)
        if pw_result is not None:
            logger.info(
                "视觉降级到 pywinauto：element=%s, bbox=%s",
                element_description, pw_result.bbox,
            )
            return ElementResult(
                name=pw_result.name,
                bbox=pw_result.bbox,
                confidence=pw_result.confidence,
                strategy="pywinauto_fallback",
            )

        if experience_coords is not None:
            tried.append("experience")
            return self._locate_by_experience(element_description, experience_coords)

        raise ElementNotFoundError(
            f"无法定位元素：{element_description!r}",
            tried_strategies=tried,
        )

    def locate_by_template(
        self,
        screenshot: np.ndarray,
        template: np.ndarray,
        element_description: str,
        experience_coords: tuple[int, int] | None = None,
        threshold: float = 0.8,
    ) -> ElementResult:
        """按优先级降级链定位模板图像对应的 GUI 元素。

        依次尝试：阿里云视觉 → Qwen-VL → OpenCV 模板匹配 → 经验坐标（若提供）。
        高优先级策略成功时立即返回，不调用后续策略。
        全部失败时抛出 :class:`ElementNotFoundError`。

        Args:
            screenshot: 当前屏幕截图，BGR numpy 数组。
            template: 模板图像，BGR numpy 数组。
            element_description: 目标元素描述（用于日志和 API 调用）。
            experience_coords: 可选的经验坐标 (x, y)，作为最终兜底。
            threshold: 模板匹配最低置信度阈值，默认 0.8。

        Returns:
            识别成功的 :class:`ElementResult`。

        Raises:
            ElementNotFoundError: 所有策略均失败且无经验坐标时抛出。
        """
        tried: list[str] = []

        # 策略 1：阿里云视觉
        tried.append("aliyun_vision")
        result = self._locate_by_aliyun_vision(screenshot, element_description)
        if result is not None:
            return result

        # 策略 2：Qwen-VL
        tried.append("qwen_vl")
        result = self._locate_by_qwen_vl(screenshot, element_description)
        if result is not None:
            return result

        # 策略 4：OpenCV 模板匹配
        tried.append("template")
        result = self._locate_by_template(screenshot, template, element_description, threshold)
        if result is not None:
            return result

        # 策略 5：经验坐标（兜底）
        if experience_coords is not None:
            tried.append("experience")
            return self._locate_by_experience(element_description, experience_coords)

        raise ElementNotFoundError(
            f"无法定位元素：{element_description!r}",
            tried_strategies=tried,
        )
