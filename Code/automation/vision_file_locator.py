"""视觉文件定位模块：截图 + 模板匹配 + OCR，识别桌面文件图标并返回逻辑坐标结果。

本模块提供 FileIconResult 数据结构和 VisionFileLocator 类，
作为 FileOrganizer 视觉优先模式的感知层组件。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

import cv2
import numpy as np
import pyautogui
import pytesseract
import yaml

from perception.dpi_adapter import DPIAdapter
from perception.screen_capturer import ScreenCapturer

logger = logging.getLogger(__name__)

# Hardcoded defaults used when settings.yaml cannot be read
_DEFAULT_OCR_CONFIDENCE_THRESHOLD: float = 60.0
_DEFAULT_TEMPLATE_MATCH_THRESHOLD: float = 0.8
_DEFAULT_ICON_OCR_Y_OFFSET: int = 40
_DEFAULT_ICON_OCR_HEIGHT: int = 20

_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "file_icon.png"


@dataclass
class FileIconResult:
    """单个已识别文件的视觉定位结果。

    Attributes:
        name: OCR 识别的文件名；置信度不足时为 None。
        bbox: 图标边界框 (x, y, width, height)，逻辑坐标。
        center: 图标中心点 (cx, cy)，逻辑坐标；由 __post_init__ 根据 bbox 自动计算。
        ocr_confidence: OCR 置信度，范围 0.0～100.0；name 为 None 时仍保留原始值。
        source_path: 对应的源文件路径（由 FileOrganizer 在匹配后填充）。
    """

    name: str | None
    bbox: tuple[int, int, int, int]
    center: tuple[int, int] = field(default_factory=lambda: (0, 0))
    ocr_confidence: float = 0.0
    source_path: str = ""

    def __post_init__(self) -> None:
        x, y, w, h = self.bbox
        self.center = (x + w // 2, y + h // 2)


def _load_vision_settings() -> dict:
    """从 config/settings.yaml 读取 vision 配置块。

    Returns:
        vision 配置字典；读取失败时返回空字典。
    """
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}
        return settings.get("vision", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("无法读取 settings.yaml 中的 vision 配置，将使用硬编码默认值: %s", exc)
        return {}


def _preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """对图像执行 OCR 预处理：灰度化 → 2x 放大 → Otsu 二值化。

    Args:
        image: BGR uint8 numpy 数组。

    Returns:
        预处理后的二值化灰度图像。
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


class VisionFileLocator:
    """视觉文件定位器：截图 + 模板匹配 + OCR，识别桌面文件图标并返回逻辑坐标结果。

    从 config/settings.yaml 的 vision 块读取默认配置，支持构造参数覆盖。
    物理像素坐标通过 DPIAdapter 转换为逻辑坐标后填入 FileIconResult。
    """

    def __init__(
        self,
        ocr_confidence_threshold: float | None = None,
        template_match_threshold: float | None = None,
        icon_ocr_y_offset: int | None = None,
        icon_ocr_height: int | None = None,
        dpi_adapter: DPIAdapter | None = None,
    ) -> None:
        """初始化 VisionFileLocator。

        从 config/settings.yaml 的 vision 块读取默认值，构造参数优先级更高。
        若 yaml 读取失败，使用硬编码默认值：threshold=60.0, match=0.8, y_offset=40, height=20。

        Args:
            ocr_confidence_threshold: OCR 置信度阈值（0.0～100.0）。低于此值时 name 设为 None。
            template_match_threshold: OpenCV 模板匹配置信度阈值（0.0～1.0）。
            icon_ocr_y_offset: 图标下方 OCR 区域的 Y 偏移（物理像素）。
            icon_ocr_height: OCR 区域高度（物理像素）。
            dpi_adapter: DPI 适配器实例；为 None 时自动创建。
        """
        vision_cfg = _load_vision_settings()

        self._ocr_confidence_threshold: float = (
            ocr_confidence_threshold
            if ocr_confidence_threshold is not None
            else float(vision_cfg.get("ocr_confidence_threshold", _DEFAULT_OCR_CONFIDENCE_THRESHOLD))
        )
        self._template_match_threshold: float = (
            template_match_threshold
            if template_match_threshold is not None
            else float(vision_cfg.get("template_match_threshold", _DEFAULT_TEMPLATE_MATCH_THRESHOLD))
        )
        self._icon_ocr_y_offset: int = (
            icon_ocr_y_offset
            if icon_ocr_y_offset is not None
            else int(vision_cfg.get("icon_ocr_y_offset", _DEFAULT_ICON_OCR_Y_OFFSET))
        )
        self._icon_ocr_height: int = (
            icon_ocr_height
            if icon_ocr_height is not None
            else int(vision_cfg.get("icon_ocr_height", _DEFAULT_ICON_OCR_HEIGHT))
        )

        self._dpi: DPIAdapter = dpi_adapter if dpi_adapter is not None else DPIAdapter()
        self._capturer: ScreenCapturer = ScreenCapturer()

        logger.debug(
            "VisionFileLocator initialized: ocr_threshold=%.1f, match_threshold=%.2f, "
            "ocr_y_offset=%d, ocr_height=%d, scale_factor=%.2f",
            self._ocr_confidence_threshold,
            self._template_match_threshold,
            self._icon_ocr_y_offset,
            self._icon_ocr_height,
            self._dpi.scale_factor,
        )

    def _detect_icons_template(
        self, screenshot: np.ndarray, template: np.ndarray
    ) -> list[tuple[int, int, int, int]]:
        """使用模板匹配在截图中定位图标区域。

        Args:
            screenshot: BGR 截图（物理像素）。
            template: BGR 模板图像。

        Returns:
            检测到的图标区域列表，每项为 (x, y, w, h) 物理像素坐标。
        """
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        th, tw = template.shape[:2]

        # Threshold the match result map to find all matches above threshold
        _, thresh_map = cv2.threshold(
            result, self._template_match_threshold, 1.0, cv2.THRESH_BINARY
        )
        thresh_u8 = (thresh_map * 255).astype(np.uint8)
        contours, _ = cv2.findContours(thresh_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rects: list[tuple[int, int, int, int]] = []
        for cnt in contours:
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            # Each match point corresponds to the top-left of the template
            rects.append((cx, cy, tw, th))

        logger.debug("Template matching found %d icon region(s)", len(rects))
        return rects

    def _detect_icons_contour(self, screenshot: np.ndarray) -> list[tuple[int, int, int, int]]:
        """使用轮廓检测在截图中定位图标区域（模板不存在时的备选方案）。

        Args:
            screenshot: BGR 截图（物理像素）。

        Returns:
            检测到的图标区域列表，每项为 (x, y, w, h) 物理像素坐标。
        """
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rects: list[tuple[int, int, int, int]] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if 400 <= area <= 10000:
                rects.append((x, y, w, h))

        logger.debug("Contour detection found %d icon region(s)", len(rects))
        return rects

    def _run_ocr(self, ocr_region: np.ndarray) -> tuple[str | None, float]:
        """对图标下方区域执行 OCR，返回识别文本和置信度。

        Args:
            ocr_region: BGR 图像区域（图标下方的文件名区域）。

        Returns:
            (name, confidence) 元组。name 为 None 表示置信度不足或无文字。
        """
        preprocessed = _preprocess_for_ocr(ocr_region)
        data: dict = pytesseract.image_to_data(
            preprocessed,
            lang="chi_sim+eng",
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

        conf_values = []
        text_values = []
        for conf_raw, text_raw in zip(data["conf"], data["text"]):
            text_str = str(text_raw).strip()
            if not text_str:
                continue
            try:
                conf_int = int(conf_raw)
            except (ValueError, TypeError):
                continue
            if conf_int < 0:
                continue
            conf_values.append(conf_int)
            text_values.append(text_str)

        if not conf_values:
            return None, 0.0

        mean_conf = mean(conf_values)
        name = " ".join(text_values).strip() if text_values else None
        return name, mean_conf

    def get_file_icons_and_names(
        self,
        region: tuple[int, int, int, int],
        monitor_index: int = 0,
    ) -> list[FileIconResult]:
        """截取指定区域，定位文件图标并识别文件名。

        Args:
            region: (x, y, width, height) 逻辑坐标，指定截图区域。
            monitor_index: 目标显示器索引（0-based）。

        Returns:
            识别到的文件图标结果列表，坐标均为逻辑坐标。

        Raises:
            ValueError: region 坐标超出屏幕逻辑分辨率范围，或任意值为负数。
            Exception: mss 截图失败时向上重新抛出。
        """
        # Validate region against screen logical size
        sw, sh = pyautogui.size()
        rx, ry, rw, rh = region

        if rx < 0:
            raise ValueError(
                f"region x={rx} 为负数（屏幕逻辑尺寸: {sw}×{sh}）"
            )
        if ry < 0:
            raise ValueError(
                f"region y={ry} 为负数（屏幕逻辑尺寸: {sw}×{sh}）"
            )
        if rw < 0:
            raise ValueError(
                f"region width={rw} 为负数（屏幕逻辑尺寸: {sw}×{sh}）"
            )
        if rh < 0:
            raise ValueError(
                f"region height={rh} 为负数（屏幕逻辑尺寸: {sw}×{sh}）"
            )
        if rx + rw > sw:
            raise ValueError(
                f"region 右边界 {rx + rw}（x={rx}, width={rw}）超出屏幕宽度 {sw}"
                f"（屏幕逻辑尺寸: {sw}×{sh}）"
            )
        if ry + rh > sh:
            raise ValueError(
                f"region 下边界 {ry + rh}（y={ry}, height={rh}）超出屏幕高度 {sh}"
                f"（屏幕逻辑尺寸: {sw}×{sh}）"
            )

        # Capture screenshot — re-raise on failure
        try:
            screenshot = self._capturer.capture_region(rx, ry, rw, rh, monitor_index)
        except Exception as exc:
            logger.error(
                "capture_region 失败 region=(%d,%d,%d,%d) monitor=%d: %s",
                rx, ry, rw, rh, monitor_index, exc,
            )
            raise

        # Detect icon regions
        icon_rects: list[tuple[int, int, int, int]]
        if _TEMPLATE_PATH.exists():
            template = cv2.imread(str(_TEMPLATE_PATH))
            if template is not None:
                icon_rects = self._detect_icons_template(screenshot, template)
            else:
                logger.warning("无法加载模板图像 %s，退化为轮廓检测", _TEMPLATE_PATH)
                icon_rects = self._detect_icons_contour(screenshot)
        else:
            logger.debug("模板文件不存在 %s，使用轮廓检测", _TEMPLATE_PATH)
            icon_rects = self._detect_icons_contour(screenshot)

        results: list[FileIconResult] = []
        scale = self._dpi.scale_factor

        for ix, iy, iw, ih in icon_rects:
            # Convert physical pixel coords (relative to screenshot) to logical coords
            # The screenshot top-left corresponds to region (rx, ry) in logical coords.
            # Physical coords within screenshot: (ix, iy)
            # Physical absolute: (ix + rx * scale, iy + ry * scale) — but capture_region
            # already captures the physical pixels starting at the logical region offset.
            # DPIAdapter.to_logical expects absolute physical coords.
            phys_abs_x = ix + round(rx * scale)
            phys_abs_y = iy + round(ry * scale)
            lx, ly = self._dpi.to_logical(phys_abs_x, phys_abs_y, monitor_index)
            lw = max(1, round(iw / scale))
            lh = max(1, round(ih / scale))

            # Extract OCR region: area below the icon in physical pixel space
            ocr_y_start = iy + ih
            ocr_y_end = iy + ih + self._icon_ocr_y_offset + self._icon_ocr_height
            ocr_region = screenshot[ocr_y_start:ocr_y_end, ix: ix + iw]

            if ocr_region.size == 0 or ocr_y_start >= screenshot.shape[0]:
                logger.warning(
                    "图标 (%d,%d,%d,%d) 下方 OCR 区域为空或越界，name 设为 None",
                    ix, iy, iw, ih,
                )
                name: str | None = None
                conf: float = 0.0
            else:
                try:
                    raw_name, conf = self._run_ocr(ocr_region)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("OCR 失败 icon=(%d,%d,%d,%d): %s", ix, iy, iw, ih, exc)
                    raw_name, conf = None, 0.0

                if conf < self._ocr_confidence_threshold or raw_name is None:
                    logger.warning(
                        "OCR 置信度 %.1f 低于阈值 %.1f，图标坐标 (%d,%d,%d,%d)，name 设为 None",
                        conf, self._ocr_confidence_threshold, ix, iy, iw, ih,
                    )
                    name = None
                else:
                    name = raw_name
                    logger.info(
                        "识别文件: name=%r bbox=(%d,%d,%d,%d) ocr_confidence=%.1f",
                        name, lx, ly, lw, lh, conf,
                    )

            result = FileIconResult(
                name=name,
                bbox=(lx, ly, lw, lh),
                ocr_confidence=conf,
            )
            results.append(result)

        logger.debug(
            "get_file_icons_and_names: region=%s monitor=%d → %d result(s)",
            region, monitor_index, len(results),
        )
        return results
