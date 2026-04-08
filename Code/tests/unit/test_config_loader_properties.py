"""config_loader 属性测试（Property-Based Tests）。

Feature: cv-desktop-automation-agent
Properties 20 & 21: 配置加载的属性验证
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from config.config_loader import (
    DEFAULTS,
    REQUIRED_ENV_VARS,
    ConfigMissingError,
    load_config,
)

# ---------------------------------------------------------------------------
# All settings keys as (section, field) tuples
# ---------------------------------------------------------------------------

_ALL_SETTINGS_KEYS: list[tuple[str, str]] = [
    ("capture", "fps"),
    ("capture", "default_monitor"),
    ("retry", "max_attempts"),
    ("retry", "initial_wait_sec"),
    ("retry", "jitter_max_sec"),
    ("retry", "element_timeout_sec"),
    ("agent", "model"),
    ("agent", "max_iterations"),
    ("agent", "memory_max_tokens"),
    ("ui", "preview_fps"),
    ("ui", "queue_timeout_sec"),
]


# ---------------------------------------------------------------------------
# Property 20: 缺失必需环境变量时启动报错
# ---------------------------------------------------------------------------

# Feature: cv-desktop-automation-agent, Property 20: 缺失必需环境变量时启动报错
@settings(max_examples=100)
@given(
    missing_vars=st.sets(
        st.sampled_from(REQUIRED_ENV_VARS),
        min_size=1,
    )
)
def test_missing_required_env_var_raises_error(missing_vars: set[str]) -> None:
    """Property 20: 缺失必需环境变量时启动报错
    Validates: Requirements 13.4

    For any environment missing DASHSCOPE_API_KEY, the system must raise
    ConfigMissingError containing the missing variable name and terminate,
    rather than continuing with undefined behavior.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        env_path = tmp / ".env"
        env_path.write_text("", encoding="utf-8")
        yaml_path = tmp / "settings.yaml"
        yaml_path.write_text(yaml.dump({}), encoding="utf-8")

        # Build env dict that has all required vars except the missing ones
        base_env = {var: "dummy-value" for var in REQUIRED_ENV_VARS}
        for var in missing_vars:
            base_env.pop(var, None)

        with patch.dict(os.environ, base_env, clear=True):
            with pytest.raises(ConfigMissingError) as exc_info:
                load_config(env_path=env_path, yaml_path=yaml_path)

        error_msg = str(exc_info.value)
        # The error message must contain at least one of the missing variable names
        assert any(var in error_msg for var in missing_vars), (
            f"Error message '{error_msg}' does not mention any missing var from: {missing_vars}"
        )


# ---------------------------------------------------------------------------
# Property 21: settings.yaml 参数缺失时使用预定义默认值
# ---------------------------------------------------------------------------

# Feature: cv-desktop-automation-agent, Property 21: settings.yaml 参数缺失时使用预定义默认值
@settings(max_examples=100)
@given(
    missing_keys=st.sets(
        st.sampled_from(_ALL_SETTINGS_KEYS),
        min_size=1,
        max_size=len(_ALL_SETTINGS_KEYS),
    )
)
def test_missing_yaml_fields_use_defaults(missing_keys: set[tuple[str, str]]) -> None:
    """Property 21: settings.yaml 参数缺失时使用预定义默认值
    Validates: Requirements 13.5

    For any settings.yaml missing some fields, after config loading all missing
    fields must equal predefined default values (e.g., fps=15, max_attempts=3,
    element_timeout_sec=10), and WARNING logs must be recorded.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        env_path = tmp / ".env"
        env_path.write_text("DASHSCOPE_API_KEY=test-key", encoding="utf-8")

        # Start with a full settings dict, then remove the missing keys
        full_settings: dict[str, dict] = {
            "capture": {"fps": 15, "default_monitor": 0},
            "retry": {
                "max_attempts": 3,
                "initial_wait_sec": 1,
                "jitter_max_sec": 1,
                "element_timeout_sec": 10,
            },
            "agent": {"model": "qwen-plus", "max_iterations": 20, "memory_max_tokens": 2000},
            "ui": {"preview_fps": 15, "queue_timeout_sec": 30},
        }
        for section, key in missing_keys:
            full_settings[section].pop(key, None)

        yaml_path = tmp / "settings.yaml"
        yaml_path.write_text(yaml.dump(full_settings), encoding="utf-8")

        # Capture WARNING logs from the config_loader logger
        config_logger = logging.getLogger("config.config_loader")
        log_records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = _ListHandler(level=logging.WARNING)
        config_logger.addHandler(handler)
        original_level = config_logger.level
        config_logger.setLevel(logging.WARNING)
        try:
            with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}, clear=True):
                cfg = load_config(env_path=env_path, yaml_path=yaml_path)
        finally:
            config_logger.removeHandler(handler)
            config_logger.setLevel(original_level)

        # Verify all missing fields equal the predefined default values
        for section, key in missing_keys:
            expected = DEFAULTS[section][key]
            if section == "capture":
                actual = getattr(cfg.capture, key)
            elif section == "retry":
                actual = getattr(cfg.retry, key)
            elif section == "agent":
                actual = getattr(cfg.agent, key)
            elif section == "ui":
                actual = getattr(cfg.ui, key)
            else:
                raise AssertionError(f"Unknown section: {section}")

            assert actual == expected, (
                f"cfg.{section}.{key} = {actual!r}, expected default {expected!r}"
            )

        # Verify a WARNING was logged for each missing field
        warning_messages = [r.getMessage() for r in log_records if r.levelno == logging.WARNING]
        for section, key in missing_keys:
            assert any(key in msg for msg in warning_messages), (
                f"No WARNING logged for missing {section}.{key}. "
                f"Warnings recorded: {warning_messages}"
            )
