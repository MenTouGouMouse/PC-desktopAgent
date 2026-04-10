"""OCR 辅助模块：封装 Tesseract OCR 调用，提供全图文本提取与目标文本区域定位功能。

预处理流程：灰度化 → 2x 放大（cv2.INTER_CUBIC）→ Otsu 二值化，再调用 pytesseract。
所有返回坐标均为逻辑坐标（原始图像空间，非预处理后的 2x 空间）。

注意：ElementResult 定义在 perception.element_locator 中，本模块直接导入使用，
避免重复定义导致类型不兼容。
"""

from __future__ import annotations

import logging
import os

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from perception.element_locator import ElementResult

logger = logging.getLogger(__name__)


def _edit_distance(a: str, b: str) -> int:
    """计算两个短字符串的编辑距离（仅对 len <= 8 的字符串调用，避免性能问题）。

    Args:
        a: 第一个字符串。
        b: 第二个字符串。

    Returns:
        编辑距离（整数）。
    """
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _fuzzy_match(word: str, target: str) -> bool:
    """去空格后精确匹配，或编辑距离 <= 2。"""
    w = word.replace(" ", "").lower()
    t = target.replace(" ", "").lower()
    if t in w or w in t:
        return True
    if len(w) <= 8 and len(t) <= 8:
        return _edit_distance(w, t) <= 2
    return False


def _exact_button_match(word: str, target: str) -> bool:
    """按钮文字精确匹配：要求识别词与目标词高度相似，防止子串误匹配。

    规则（按优先级）：
    1. 去空格后完全相等
    2. 识别词以目标词开头，后缀仅为括号内容（如"下一步(N)"匹配"下一步"）
    3. 编辑距离 <= 1，且两词长度相同（仅允许替换，不允许插入/删除）

    不允许：
    - "同意"匹配"我同意"（子串，但识别词比目标词短）
    - "立即安装"匹配"安装"（识别词比目标词长且有前缀）

    Args:
        word: OCR 识别的词。
        target: 目标按钮文字。

    Returns:
        True 表示匹配，False 表示不匹配。
    """
    import re as _re
    w = word.replace(" ", "").lower()
    t = target.replace(" ", "").lower()

    # 规则1：完全相等
    if w == t:
        return True

    # 规则2：识别词以目标词开头，后缀仅为括号内容（如"下一步(n)"、"安装(i)"）
    if w.startswith(t) and _re.fullmatch(r'\([a-z]\)', w[len(t):]):
        return True

    # 规则3：编辑距离 <= 1，且长度完全相同（只允许字符替换，处理 OCR 单字符误识别）
    if len(w) == len(t) and len(w) <= 8:
        return _edit_distance(w, t) <= 1

    return False

_OCR_LANG = "chi_sim+eng"
_OCR_CONFIG = "--psm 6"


def _configure_tesseract() -> None:
    """从 settings.yaml 或环境变量读取 tesseract 路径并配置 pytesseract。"""
    # 优先读取环境变量，方便 CI/CD 覆盖
    cmd = os.environ.get("TESSERACT_CMD", "")
    if not cmd:
        try:
            import yaml
            _settings_path = os.path.join(
                os.path.dirname(__file__), "..", "config", "settings.yaml"
            )
            with open(_settings_path, encoding="utf-8") as f:
                settings = yaml.safe_load(f) or {}
            cmd = settings.get("ocr", {}).get("tesseract_cmd", "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("无法读取 settings.yaml 中的 tesseract_cmd: %s", exc)

    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
        logger.debug("tesseract_cmd 已设置为: %s", cmd)


_configure_tesseract()


def _preprocess(image: np.ndarray) -> np.ndarray:
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


class OCRHelper:
    """封装 Tesseract OCR 调用，提供文本提取与文本区域定位功能。"""

    def extract_text(self, image: np.ndarray) -> str:
        """全图 OCR，返回识别文本。

        Args:
            image: BGR uint8 numpy 数组（原始截图）。

        Returns:
            识别出的文本字符串；失败时返回空字符串。
        """
        try:
            preprocessed = _preprocess(image)
            text: str = pytesseract.image_to_string(
                preprocessed, lang=_OCR_LANG, config=_OCR_CONFIG
            )
            logger.debug("extract_text: recognized %d chars", len(text))
            return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("extract_text failed: %s", exc)
            return ""

    def find_text_bbox(self, image: np.ndarray, target: str) -> ElementResult | None:
        """在图像中定位包含 target 文本的区域。

        使用 pytesseract.image_to_data() 获取每个识别词的边界框，
        在结果中搜索包含 target 的文本（大小写不敏感），返回第一个匹配项。

        Args:
            image: BGR uint8 numpy 数组（原始截图）。
            target: 要搜索的目标文本。

        Returns:
            匹配到目标文本的 ElementResult（strategy="ocr"），未找到时返回 None。
        """
        if not target:
            logger.warning("find_text_bbox: empty target string")
            return None

        try:
            preprocessed = _preprocess(image)
            data: dict = pytesseract.image_to_data(
                preprocessed, lang=_OCR_LANG, config=_OCR_CONFIG, output_type=Output.DICT
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_text_bbox: pytesseract failed: %s", exc)
            return None

        n_boxes = len(data.get("text", []))
        texts = data.get("text", [])

        # Collect valid (non-empty) word entries with their indices
        valid_indices = [
            i for i in range(n_boxes)
            if isinstance(texts[i], str) and texts[i].strip()
        ]

        def _get_result(i: int, matched_word: str) -> ElementResult:
            raw_conf = data["conf"][i]
            try:
                conf_int = int(raw_conf)
            except (ValueError, TypeError):
                conf_int = -1
            confidence = max(0.0, conf_int / 100.0) if conf_int >= 0 else 0.0

            # Coordinates are in the 2x preprocessed image space; divide by 2 for original
            x_scaled: int = int(data["left"][i])
            y_scaled: int = int(data["top"][i])
            w_scaled: int = int(data["width"][i])
            h_scaled: int = int(data["height"][i])

            x = x_scaled // 2
            y = y_scaled // 2
            w = max(1, w_scaled // 2)
            h = max(1, h_scaled // 2)

            logger.debug(
                "find_text_bbox: found %r at bbox=(%d,%d,%d,%d) conf=%.2f",
                matched_word, x, y, w, h, confidence,
            )
            return ElementResult(
                name=matched_word.strip(),
                bbox=(x, y, w, h),
                confidence=confidence,
                strategy="ocr",
            )

        # Pass 1: single-word fuzzy match
        for i in valid_indices:
            word = texts[i]
            if _fuzzy_match(word, target):
                return _get_result(i, word)

        # Pass 2: sliding window multi-word concatenation (window size 2-3)
        # Handles Chinese multi-character buttons split across adjacent words
        for window in (2, 3):
            for pos in range(len(valid_indices) - window + 1):
                idx_slice = valid_indices[pos:pos + window]
                combined = "".join(texts[j] for j in idx_slice)
                if _fuzzy_match(combined, target):
                    # Use the first word's position as anchor
                    anchor = idx_slice[0]
                    return _get_result(anchor, combined)

        logger.debug("find_text_bbox: target %r not found in OCR results", target)
        return None

    def find_button_bbox(
        self,
        image: np.ndarray,
        target: str,
        window_bbox: tuple[int, int, int, int] | None = None,
    ) -> ElementResult | None:
        """在图像中定位包含 target 文本的【按钮控件】区域。

        与 find_text_bbox 的区别：优先返回屏幕下半部分的匹配项，
        并过滤掉文字块过高（大段正文）的匹配，避免误点正文中的相同文字。

        过滤规则：
        - 优先：y 中心点在图像下半部分（y_center > img_height * 0.4）
        - 过滤：文字块高度 > img_height * 0.08（超过 8% 屏高，判定为正文段落）
        - 降级：若下半区无匹配，返回全屏第一个匹配（高度过滤仍然生效）

        Args:
            image: BGR uint8 numpy 数组（原始截图）。
            target: 要搜索的目标按钮文字。
            window_bbox: 可选的安装窗口客户区边界框 (x, y, w, h)，逻辑坐标。
                当提供时，OCR 仅在该区域内执行，避免误匹配窗口外的正文文字。
                返回坐标已还原为原始截图坐标系。

        Returns:
            最可能是按钮的 ElementResult，未找到时返回 None。
        """
        if not target:
            return None

        # 当提供 window_bbox 时，裁剪图像到窗口区域，记录偏移量用于坐标还原
        offset_x, offset_y = 0, 0
        if window_bbox is not None:
            wx, wy, ww, wh = window_bbox
            image = image[wy:wy + wh, wx:wx + ww]
            offset_x, offset_y = wx, wy
            logger.debug(
                "find_button_bbox: cropped to window_bbox=(%d,%d,%d,%d), offset=(%d,%d)",
                wx, wy, ww, wh, offset_x, offset_y,
            )

        img_h, img_w = image.shape[:2]
        # 按钮文字块高度上限：超过屏高 8% 认为是正文段落
        max_btn_h = img_h * 0.08
        # 下半区起始 y（中心点超过此值优先）
        lower_half_y = img_h * 0.4

        try:
            preprocessed = _preprocess(image)
            data: dict = pytesseract.image_to_data(
                preprocessed, lang=_OCR_LANG, config=_OCR_CONFIG, output_type=Output.DICT
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_button_bbox: pytesseract failed: %s", exc)
            return None

        texts = data.get("text", [])
        n_boxes = len(texts)
        valid_indices = [
            i for i in range(n_boxes)
            if isinstance(texts[i], str) and texts[i].strip()
        ]

        def _to_result(i: int, matched_word: str) -> ElementResult:
            raw_conf = data["conf"][i]
            try:
                conf_int = int(raw_conf)
            except (ValueError, TypeError):
                conf_int = -1
            confidence = max(0.0, conf_int / 100.0) if conf_int >= 0 else 0.0
            x = int(data["left"][i]) // 2 + offset_x
            y = int(data["top"][i]) // 2 + offset_y
            w = max(1, int(data["width"][i]) // 2)
            h = max(1, int(data["height"][i]) // 2)
            return ElementResult(
                name=matched_word.strip(),
                bbox=(x, y, w, h),
                confidence=confidence,
                strategy="ocr",
            )

        def _is_button_sized(i: int) -> bool:
            """文字块高度在按钮合理范围内（不是大段正文）。"""
            h = int(data["height"][i]) // 2
            return h <= max_btn_h

        def _in_lower_half(i: int) -> bool:
            """文字块中心点在屏幕下半部分。"""
            y = int(data["top"][i]) // 2
            h = int(data["height"][i]) // 2
            y_center = y + h / 2
            return y_center > lower_half_y

        # 收集所有匹配项（单词 + 滑动窗口），分为下半区和全屏两组
        lower_candidates: list[ElementResult] = []
        all_candidates: list[ElementResult] = []

        # Pass 1: 单词匹配
        for i in valid_indices:
            word = texts[i]
            # 精确匹配：目标词必须完整出现在识别词中（不允许子串误匹配）
            if _exact_button_match(word, target) and _is_button_sized(i):
                r = _to_result(i, word)
                all_candidates.append(r)
                if _in_lower_half(i):
                    lower_candidates.append(r)

        # Pass 2: 滑动窗口多词拼接（处理中文按钮被分词的情况）
        for window in (2, 3):
            for pos in range(len(valid_indices) - window + 1):
                idx_slice = valid_indices[pos:pos + window]
                combined = "".join(texts[j] for j in idx_slice)
                anchor = idx_slice[0]
                if _exact_button_match(combined, target) and _is_button_sized(anchor):
                    # 合并所有词的 bbox，取最左到最右、最上到最下
                    x_min = min(int(data["left"][j]) // 2 for j in idx_slice)
                    y_min = min(int(data["top"][j]) // 2 for j in idx_slice)
                    x_max = max((int(data["left"][j]) + int(data["width"][j])) // 2 for j in idx_slice)
                    y_max = max((int(data["top"][j]) + int(data["height"][j])) // 2 for j in idx_slice)
                    merged_w = max(1, x_max - x_min)
                    merged_h = max(1, y_max - y_min)
                    raw_conf = data["conf"][anchor]
                    try:
                        conf_int = int(raw_conf)
                    except (ValueError, TypeError):
                        conf_int = -1
                    confidence = max(0.0, conf_int / 100.0) if conf_int >= 0 else 0.0
                    r = ElementResult(
                        name=combined.strip(),
                        bbox=(x_min + offset_x, y_min + offset_y, merged_w, merged_h),
                        confidence=confidence,
                        strategy="ocr",
                    )
                    all_candidates.append(r)
                    if _in_lower_half(anchor):
                        lower_candidates.append(r)

        if lower_candidates:
            # 下半区有匹配，取 y 坐标最大的（最靠近底部，最像按钮）
            best = max(lower_candidates, key=lambda r: r.bbox[1])
            logger.debug(
                "find_button_bbox: found %r in lower half at bbox=%s",
                target, best.bbox,
            )
            return best

        if all_candidates:
            # 下半区无匹配，退而求其次取全屏第一个
            best = all_candidates[0]
            logger.debug(
                "find_button_bbox: found %r (full screen fallback) at bbox=%s",
                target, best.bbox,
            )
            return best

        logger.debug("find_button_bbox: target %r not found", target)
        return None
