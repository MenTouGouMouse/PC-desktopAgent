"""automation.vision_diagnose — 视觉识别诊断模块。

在智能安装流程中，当 DEBUG_VISION=True 时，对关键按钮执行 Qwen-VL 识别，
生成带红框标注的截图并记录日志，不影响主安装流程。

使用方式：
    在 config/settings.yaml 中设置 debug_vision: true，
    或在 config/.env 中设置 DEBUG_VISION=true。
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 诊断目标按钮
_DIAGNOSE_BUTTONS: list[str] = ["下一步", "我同意", "安装", "完成"]

# 输出目录
_DEBUG_DIR = Path("debug")


def _is_debug_vision_enabled() -> bool:
    """检查 DEBUG_VISION 开关是否开启。

    优先级：环境变量 DEBUG_VISION > settings.yaml debug_vision。
    """
    env_val = os.environ.get("DEBUG_VISION", "").lower()
    if env_val in ("1", "true", "yes"):
        return True
    if env_val in ("0", "false", "no"):
        return False

    try:
        import yaml
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}
        return bool(settings.get("debug_vision", False))
    except Exception:  # noqa: BLE001
        return False


def _draw_diagnosis_boxes(
    image: np.ndarray,
    results: list[dict],
) -> np.ndarray:
    """在图像副本上绘制所有识别结果的红框标注。

    Args:
        image: BGR numpy 数组（原图）。
        results: 每项包含 button_text、bbox (x,y,w,h)、confidence。

    Returns:
        绘制了标注的图像副本。
    """
    from automation.vision_box_drawer import BoundingBoxDict, draw_boxes_on_image

    boxes: list[BoundingBoxDict] = []
    for r in results:
        x, y, w, h = r["bbox"]
        boxes.append(BoundingBoxDict(
            bbox=[x, y, x + w, y + h],
            label=r["button_text"],
            confidence=r["confidence"],
        ))
    return draw_boxes_on_image(image, boxes, confidence_threshold=0.0, show_confidence=True)


def diagnose_vision_for_buttons(
    screenshot: np.ndarray,
    buttons: list[str] | None = None,
) -> None:
    """对指定按钮列表执行 Qwen-VL 识别，生成标注截图并记录日志。

    此函数应在独立线程中调用，不阻塞主安装流程。
    识别失败时仅记录 WARNING，不抛出异常。

    Args:
        screenshot: 当前屏幕截图（BGR numpy 数组）。
        buttons: 要诊断的按钮文字列表，默认使用 _DIAGNOSE_BUTTONS。
    """
    if not _is_debug_vision_enabled():
        logger.debug("DEBUG_VISION 未开启，跳过视觉诊断")
        return

    if buttons is None:
        buttons = _DIAGNOSE_BUTTONS

    _DEBUG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("视觉诊断开始，目标按钮：%s", buttons)

    from perception.element_locator import ElementLocator
    locator = ElementLocator()

    results: list[dict] = []

    for button_text in buttons:
        try:
            result = locator._locate_by_qwen_vl(screenshot, button_text)
            if result is not None:
                x, y, w, h = result.bbox
                logger.info(
                    "诊断：按钮 %r 识别成功 bbox=(%d,%d,%d,%d) confidence=%.3f strategy=%s",
                    button_text, x, y, w, h, result.confidence, result.strategy,
                )
                results.append({
                    "button_text": button_text,
                    "bbox": (x, y, w, h),
                    "confidence": result.confidence,
                })
            else:
                logger.warning("诊断：按钮 %r 未识别到（返回 None）", button_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("诊断：按钮 %r 识别异常：%s", button_text, exc)

    if not results:
        logger.warning("诊断：所有按钮均未识别到，跳过截图保存")
        return

    # 生成标注截图
    try:
        annotated = _draw_diagnosis_boxes(screenshot, results)
        out_path = _DEBUG_DIR / f"vision_diagnose_{ts}.png"
        cv2.imwrite(str(out_path), annotated)
        logger.info("诊断截图已保存：%s（识别到 %d/%d 个按钮）", out_path, len(results), len(buttons))
    except Exception as exc:  # noqa: BLE001
        logger.warning("诊断截图保存失败：%s", exc)


def diagnose_vision_async(
    screenshot: np.ndarray,
    buttons: list[str] | None = None,
) -> threading.Thread:
    """在后台线程中执行视觉诊断，立即返回线程对象。

    Args:
        screenshot: 当前屏幕截图的副本（调用方应传入 .copy()，避免并发修改）。
        buttons: 要诊断的按钮文字列表。

    Returns:
        已启动的后台线程（daemon=True）。
    """
    t = threading.Thread(
        target=diagnose_vision_for_buttons,
        args=(screenshot, buttons),
        daemon=True,
        name="vision-diagnose",
    )
    t.start()
    return t
