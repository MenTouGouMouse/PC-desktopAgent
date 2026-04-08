"""视觉文件移动模块：通过模拟鼠标拖拽将文件移动到目标文件夹。

优先使用 ActionEngine.drag() 执行拖拽；拖拽失败时降级为右键菜单"剪切 → 打开目标 → 粘贴"方案。
坐标转换完全由 ActionEngine 内部负责，本模块只传递逻辑坐标。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pyautogui
import yaml

from execution.action_engine import ActionEngine

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_DEFAULT_DRAG_DURATION_SEC = 0.5


def _load_drag_duration_from_yaml() -> float:
    """从 config/settings.yaml 读取 vision.drag_duration_sec，缺失时返回默认值 0.5。"""
    try:
        with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("vision", {}).get("drag_duration_sec")
        if value is not None:
            return float(value)
    except Exception as exc:
        logger.warning("读取 settings.yaml 失败，使用默认 drag_duration_sec=%.1f: %s", _DEFAULT_DRAG_DURATION_SEC, exc)
    return _DEFAULT_DRAG_DURATION_SEC


class VisionFileMover:
    """通过模拟鼠标拖拽将文件移动到目标文件夹。

    优先调用 ActionEngine.drag() 执行拖拽；若拖拽返回 False 或抛出异常，
    则降级为右键菜单"剪切 → 双击打开目标文件夹 → Ctrl+V 粘贴"方案。

    坐标约定：所有坐标参数均为逻辑坐标，物理坐标转换由 ActionEngine 内部完成。
    """

    def __init__(
        self,
        action_engine: ActionEngine,
        drag_duration_sec: float | None = None,
    ) -> None:
        """初始化 VisionFileMover。

        Args:
            action_engine: 执行层动作引擎实例。
            drag_duration_sec: 拖拽持续时间（秒）。为 None 时从 settings.yaml 读取，
                               yaml 中也缺失则使用默认值 0.5。
        """
        self._action_engine = action_engine
        yaml_value = _load_drag_duration_from_yaml()
        self._drag_duration_sec = drag_duration_sec if drag_duration_sec is not None else yaml_value
        logger.info("VisionFileMover 初始化完成，drag_duration_sec=%.2f", self._drag_duration_sec)

    def drag_file_to_folder(
        self,
        file_center: tuple[int, int],
        folder_center: tuple[int, int],
        duration: float | None = None,
    ) -> bool:
        """模拟拖拽将文件移动到目标文件夹。

        优先通过 ActionEngine.drag() 执行拖拽；失败时降级为右键菜单备选方案。

        Args:
            file_center: 文件图标中心点逻辑坐标 (x, y)。
            folder_center: 目标文件夹中心点逻辑坐标 (x, y)。
            duration: 拖拽持续时间（秒）；为 None 时使用 self._drag_duration_sec。

        Returns:
            True 表示移动成功（拖拽或右键菜单任一成功），False 表示全部失败。

        Raises:
            ValueError: file_center 或 folder_center 中存在负数坐标。
        """
        # 验证坐标非负
        for coord_name, coord in (("file_center", file_center), ("folder_center", folder_center)):
            axis_names = ("x", "y")
            for axis, val in zip(axis_names, coord):
                if val < 0:
                    raise ValueError(f"{coord_name} {axis}={val} 为负数")

        effective_duration = duration if duration is not None else self._drag_duration_sec
        start_time = time.monotonic()

        # --- 主路径：拖拽 ---
        try:
            result = self._action_engine.drag(
                file_center[0],
                file_center[1],
                folder_center[0],
                folder_center[1],
                effective_duration,
            )
            if result:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                logger.info(
                    "drag_file_to_folder: 拖拽成功 %s → %s，耗时 %.1f ms",
                    file_center,
                    folder_center,
                    elapsed_ms,
                )
                return True
            else:
                logger.warning(
                    "drag_file_to_folder: drag() 返回 False，尝试右键菜单备选方案 %s → %s",
                    file_center,
                    folder_center,
                )
        except Exception as exc:
            logger.warning(
                "drag_file_to_folder: drag() 抛出异常，尝试右键菜单备选方案 %s → %s: %s",
                file_center,
                folder_center,
                exc,
            )

        # --- 备选路径：右键菜单剪切 → 双击目标文件夹 → Ctrl+V 粘贴 ---
        try:
            self._action_engine.click(file_center[0], file_center[1], "right")
            time.sleep(0.5)
            self._action_engine.key_press("x")
            self._action_engine.click(folder_center[0], folder_center[1], "double")
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "v")

            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "drag_file_to_folder: 右键菜单备选方案成功 %s → %s，耗时 %.1f ms",
                file_center,
                folder_center,
                elapsed_ms,
            )
            return True
        except Exception as exc:
            logger.error(
                "drag_file_to_folder: 右键菜单备选方案也失败 %s → %s: %s",
                file_center,
                folder_center,
                exc,
            )
            return False
