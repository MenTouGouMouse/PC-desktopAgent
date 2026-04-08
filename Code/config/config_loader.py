"""配置加载模块：从 .env 和 settings.yaml 加载系统配置。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS: list[str] = ["DASHSCOPE_API_KEY"]

DEFAULTS: dict[str, Any] = {
    "capture": {"fps": 15, "default_monitor": 0},
    "retry": {
        "max_attempts": 3,
        "initial_wait_sec": 1,
        "jitter_max_sec": 1,
        "element_timeout_sec": 10,
    },
    "agent": {"model": "qwen-plus", "max_iterations": 20, "memory_max_tokens": 2000},
    "ui": {"preview_fps": 15, "queue_timeout_sec": 300},
    "vision_box": {
        "enabled": True,
        "color": "red",
        "show_confidence": True,
        "confidence_threshold": 0.5,
    },
}


class ConfigMissingError(Exception):
    """必需配置项缺失时抛出。"""


@dataclass
class CaptureConfig:
    fps: int = 15
    default_monitor: int = 0


@dataclass
class RetryConfig:
    max_attempts: int = 3
    initial_wait_sec: float = 1
    jitter_max_sec: float = 1
    element_timeout_sec: float = 10


@dataclass
class AgentConfig:
    model: str = "qwen-plus"
    max_iterations: int = 20
    memory_max_tokens: int = 2000


@dataclass
class UIConfig:
    preview_fps: int = 15
    queue_timeout_sec: float = 30


@dataclass
class VisionBoxConfig:
    enabled: bool = True
    color: str = "red"
    show_confidence: bool = True
    confidence_threshold: float = 0.5


@dataclass
class AppConfig:
    dashscope_api_key: str = ""
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _get_with_default(section: dict[str, Any], key: str, section_name: str) -> Any:
    """从 section 中取值，缺失时使用 DEFAULTS 并记录 WARNING。"""
    if key not in section:
        default_val = DEFAULTS[section_name][key]
        logger.warning(
            "settings.yaml 缺少 %s.%s，使用默认值: %s", section_name, key, default_val
        )
        return default_val
    return section[key]


def _build_capture(raw: dict[str, Any]) -> CaptureConfig:
    section = raw.get("capture", {})
    return CaptureConfig(
        fps=_get_with_default(section, "fps", "capture"),
        default_monitor=_get_with_default(section, "default_monitor", "capture"),
    )


def _build_retry(raw: dict[str, Any]) -> RetryConfig:
    section = raw.get("retry", {})
    return RetryConfig(
        max_attempts=_get_with_default(section, "max_attempts", "retry"),
        initial_wait_sec=_get_with_default(section, "initial_wait_sec", "retry"),
        jitter_max_sec=_get_with_default(section, "jitter_max_sec", "retry"),
        element_timeout_sec=_get_with_default(section, "element_timeout_sec", "retry"),
    )


def _build_agent(raw: dict[str, Any]) -> AgentConfig:
    section = raw.get("agent", {})
    return AgentConfig(
        model=_get_with_default(section, "model", "agent"),
        max_iterations=_get_with_default(section, "max_iterations", "agent"),
        memory_max_tokens=_get_with_default(section, "memory_max_tokens", "agent"),
    )


def _build_ui(raw: dict[str, Any]) -> UIConfig:
    section = raw.get("ui", {})
    return UIConfig(
        preview_fps=_get_with_default(section, "preview_fps", "ui"),
        queue_timeout_sec=_get_with_default(section, "queue_timeout_sec", "ui"),
    )


def load_config(
    env_path: Path | None = None,
    yaml_path: Path | None = None,
) -> AppConfig:
    """加载并返回完整应用配置。

    Args:
        env_path: .env 文件路径，默认为 config/.env（相对于项目根目录）。
        yaml_path: settings.yaml 文件路径，默认为 config/settings.yaml。

    Returns:
        填充完整的 AppConfig 实例。

    Raises:
        ConfigMissingError: 缺少必需环境变量时抛出，错误信息包含变量名。
    """
    # 确定默认路径（相对于本文件所在目录）
    config_dir = Path(__file__).parent
    if env_path is None:
        env_path = config_dir / ".env"
    if yaml_path is None:
        yaml_path = config_dir / "settings.yaml"

    # 加载 .env（override=False：不覆盖已存在的系统环境变量，系统变量优先）
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        logger.debug("已加载 .env 文件: %s", env_path)
    else:
        logger.warning(".env 文件不存在: %s，将仅使用系统环境变量", env_path)

    # 校验必需环境变量
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            raise ConfigMissingError(
                f"必需环境变量 '{var}' 未设置，请在 {env_path} 或系统环境中配置。"
            )

    # 加载 settings.yaml
    raw: dict[str, Any] = {}
    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        logger.debug("已加载 settings.yaml: %s", yaml_path)
    else:
        logger.warning("settings.yaml 文件不存在: %s，所有参数使用默认值", yaml_path)

    return AppConfig(
        dashscope_api_key=os.environ["DASHSCOPE_API_KEY"],
        capture=_build_capture(raw),
        retry=_build_retry(raw),
        agent=_build_agent(raw),
        ui=_build_ui(raw),
    )


def load_vision_box_config(
    yaml_path: Path | None = None,
) -> VisionBoxConfig:
    """从 settings.yaml 的 vision_box 块加载识别框叠加配置。

    Args:
        yaml_path: settings.yaml 文件路径，默认为 config/settings.yaml。

    Returns:
        填充完整的 VisionBoxConfig 实例；字段缺失时使用默认值并记录 WARNING。
    """
    config_dir = Path(__file__).parent
    if yaml_path is None:
        yaml_path = config_dir / "settings.yaml"

    raw: dict[str, Any] = {}
    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        logger.debug("已加载 settings.yaml: %s", yaml_path)
    else:
        logger.warning("settings.yaml 文件不存在: %s，vision_box 使用全部默认值", yaml_path)

    section: dict[str, Any] = raw.get("vision_box", {})
    if "vision_box" not in raw:
        logger.warning(
            "settings.yaml 缺少 vision_box 配置块，使用全部默认值"
        )

    defaults = DEFAULTS["vision_box"]

    def _get(key: str) -> Any:
        if key not in section:
            logger.warning(
                "settings.yaml 缺少 vision_box.%s，使用默认值: %s", key, defaults[key]
            )
            return defaults[key]
        return section[key]

    return VisionBoxConfig(
        enabled=_get("enabled"),
        color=_get("color"),
        show_confidence=_get("show_confidence"),
        confidence_threshold=_get("confidence_threshold"),
    )
