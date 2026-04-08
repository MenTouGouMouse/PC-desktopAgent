"""vision_box_drawer — 纯函数绘制层。

负责在截图副本上用 OpenCV 绘制目标检测框和标签，不修改原图，无副作用。
按置信度三档显示不同颜色：
  - confidence >= 0.8：绿色  (0, 255, 0)   — 高可信
  - 0.6 <= confidence < 0.8：黄色 (0, 255, 255) — 中等可信
  - confidence < 0.6：红色  (0, 0, 255)   — 低可信
"""
from __future__ import annotations

import logging
from typing import TypedDict

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 三档颜色常量（BGR）
_COLOR_HIGH: tuple[int, int, int] = (0, 255, 0)      # 绿色：confidence >= 0.8
_COLOR_MID: tuple[int, int, int] = (0, 255, 255)     # 黄色：0.6 <= confidence < 0.8
_COLOR_LOW: tuple[int, int, int] = (0, 0, 255)       # 红色：confidence < 0.6

# 置信度分档阈值
_THRESHOLD_HIGH: float = 0.8
_THRESHOLD_MID: float = 0.6

# 绘制参数
_BOX_THICKNESS = 2
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.5
_FONT_THICKNESS = 1
_LABEL_PADDING = 4
_LABEL_BG_ALPHA = 0.6


class BoundingBoxDict(TypedDict):
    """单个目标检测结果。"""

    bbox: list[int]       # [x1, y1, x2, y2]，图像坐标
    label: str            # 目标名称，非空
    confidence: float     # 0.0 ~ 1.0


def _confidence_color(confidence: float) -> tuple[int, int, int]:
    """根据置信度返回对应的 BGR 颜色。

    三档规则：
    - >= 0.8 → 绿色（高可信）
    - >= 0.6 → 黄色（中等可信）
    - <  0.6 → 红色（低可信）

    Args:
        confidence: 置信度，范围 [0.0, 1.0]。

    Returns:
        BGR 颜色元组。
    """
    if confidence >= _THRESHOLD_HIGH:
        return _COLOR_HIGH
    if confidence >= _THRESHOLD_MID:
        return _COLOR_MID
    return _COLOR_LOW


def draw_boxes_on_image(
    image: np.ndarray,
    boxes: list[BoundingBoxDict],
    confidence_threshold: float = 0.0,
    show_confidence: bool = True,
) -> np.ndarray:
    """在 image 副本上绘制检测框和标签，返回副本，不修改原图。

    颜色按置信度三档区分：
    - >= 0.8：绿色（高可信）
    - >= 0.6：黄色（中等可信）
    - <  0.6：红色（低可信）

    Args:
        image: BGR uint8 numpy 数组，形状为 (H, W, 3)。
        boxes: 检测结果列表，每项包含 bbox、label、confidence。
        confidence_threshold: 低于此值的框将被跳过，默认 0.0（全部显示）。
        show_confidence: 为 True 时标签包含置信度数值（保留两位小数），否则仅显示 label。

    Returns:
        绘制了检测框和标签的图像副本，shape 与输入相同。
    """
    output = image.copy()

    if not boxes:
        return output

    h, w = output.shape[:2]

    for box in boxes:
        bbox = box["bbox"]
        label = box["label"]
        confidence = float(box["confidence"])

        # 跳过低于阈值的框
        if confidence < confidence_threshold:
            continue

        # 裁剪越界坐标
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
        clipped_x1 = max(0, min(x1, w - 1))
        clipped_y1 = max(0, min(y1, h - 1))
        clipped_x2 = max(0, min(x2, w - 1))
        clipped_y2 = max(0, min(y2, h - 1))

        if (clipped_x1, clipped_y1, clipped_x2, clipped_y2) != (x1, y1, x2, y2):
            logger.warning(
                "bbox [%d, %d, %d, %d] 超出图像边界 (%dx%d)，已裁剪至 [%d, %d, %d, %d]",
                x1, y1, x2, y2, w, h,
                clipped_x1, clipped_y1, clipped_x2, clipped_y2,
            )

        # 根据置信度选择颜色（三档）
        color = _confidence_color(confidence)

        # 绘制矩形框
        cv2.rectangle(output, (clipped_x1, clipped_y1), (clipped_x2, clipped_y2), color, _BOX_THICKNESS)

        # 构建标签文字
        if show_confidence:
            text = f"{label} {confidence:.2f}"
        else:
            text = label

        # 计算文字尺寸
        (text_w, text_h), baseline = cv2.getTextSize(text, _FONT, _FONT_SCALE, _FONT_THICKNESS)

        # 标签背景区域（位于矩形框上方，若空间不足则放在框内顶部）
        label_x1 = clipped_x1
        label_y2 = clipped_y1
        label_y1 = label_y2 - text_h - baseline - _LABEL_PADDING * 2

        if label_y1 < 0:
            # 空间不足，放在框内顶部
            label_y1 = clipped_y1
            label_y2 = clipped_y1 + text_h + baseline + _LABEL_PADDING * 2

        label_x2 = label_x1 + text_w + _LABEL_PADDING * 2

        # 半透明背景：先在 overlay 上绘制填充矩形，再与 output 混合
        overlay = output.copy()
        cv2.rectangle(overlay, (label_x1, label_y1), (label_x2, label_y2), color, cv2.FILLED)
        cv2.addWeighted(overlay, _LABEL_BG_ALPHA, output, 1 - _LABEL_BG_ALPHA, 0, output)

        # 绘制白色文字
        text_x = label_x1 + _LABEL_PADDING
        text_y = label_y2 - baseline - _LABEL_PADDING
        cv2.putText(output, text, (text_x, text_y), _FONT, _FONT_SCALE, (255, 255, 255), _FONT_THICKNESS, cv2.LINE_AA)

        logger.debug(
            "draw_boxes_on_image: label=%r confidence=%.2f color=%s bbox=[%d,%d,%d,%d]",
            label, confidence,
            "green" if confidence >= _THRESHOLD_HIGH else ("yellow" if confidence >= _THRESHOLD_MID else "red"),
            clipped_x1, clipped_y1, clipped_x2, clipped_y2,
        )

    return output
