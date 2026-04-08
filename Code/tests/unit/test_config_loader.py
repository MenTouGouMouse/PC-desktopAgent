"""config_loader 单元测试。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from config.config_loader import (
    DEFAULTS,
    REQUIRED_ENV_VARS,
    AppConfig,
    ConfigMissingError,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_env(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(content, encoding="utf-8")
    return p


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# ConfigMissingError tests
# ---------------------------------------------------------------------------

class TestConfigMissingError:
    def test_raises_when_api_key_missing(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "")  # empty .env
        yaml_path = _write_yaml(tmp_path, {})

        # Ensure the env var is not set in the process environment
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHSCOPE_API_KEY", None)
            with pytest.raises(ConfigMissingError) as exc_info:
                load_config(env_path=env_path, yaml_path=yaml_path)

        assert "DASHSCOPE_API_KEY" in str(exc_info.value)

    def test_error_message_contains_var_name(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "")
        yaml_path = _write_yaml(tmp_path, {})

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHSCOPE_API_KEY", None)
            with pytest.raises(ConfigMissingError, match="DASHSCOPE_API_KEY"):
                load_config(env_path=env_path, yaml_path=yaml_path)

    def test_no_error_when_api_key_present(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=test-key-123")
        yaml_path = _write_yaml(tmp_path, {})

        cfg = load_config(env_path=env_path, yaml_path=yaml_path)
        assert isinstance(cfg, AppConfig)
        assert cfg.dashscope_api_key == "test-key-123"


# ---------------------------------------------------------------------------
# Default values tests
# ---------------------------------------------------------------------------

class TestDefaultValues:
    def _load_empty(self, tmp_path: Path) -> AppConfig:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=key")
        yaml_path = _write_yaml(tmp_path, {})  # all sections missing
        return load_config(env_path=env_path, yaml_path=yaml_path)

    def test_capture_defaults(self, tmp_path: Path) -> None:
        cfg = self._load_empty(tmp_path)
        assert cfg.capture.fps == DEFAULTS["capture"]["fps"]
        assert cfg.capture.default_monitor == DEFAULTS["capture"]["default_monitor"]

    def test_retry_defaults(self, tmp_path: Path) -> None:
        cfg = self._load_empty(tmp_path)
        assert cfg.retry.max_attempts == DEFAULTS["retry"]["max_attempts"]
        assert cfg.retry.initial_wait_sec == DEFAULTS["retry"]["initial_wait_sec"]
        assert cfg.retry.jitter_max_sec == DEFAULTS["retry"]["jitter_max_sec"]
        assert cfg.retry.element_timeout_sec == DEFAULTS["retry"]["element_timeout_sec"]

    def test_agent_defaults(self, tmp_path: Path) -> None:
        cfg = self._load_empty(tmp_path)
        assert cfg.agent.model == DEFAULTS["agent"]["model"]
        assert cfg.agent.max_iterations == DEFAULTS["agent"]["max_iterations"]
        assert cfg.agent.memory_max_tokens == DEFAULTS["agent"]["memory_max_tokens"]

    def test_ui_defaults(self, tmp_path: Path) -> None:
        cfg = self._load_empty(tmp_path)
        assert cfg.ui.preview_fps == DEFAULTS["ui"]["preview_fps"]
        assert cfg.ui.queue_timeout_sec == DEFAULTS["ui"]["queue_timeout_sec"]

    def test_partial_section_uses_defaults_for_missing_keys(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=key")
        yaml_path = _write_yaml(tmp_path, {"capture": {"fps": 30}})  # default_monitor missing
        cfg = load_config(env_path=env_path, yaml_path=yaml_path)
        assert cfg.capture.fps == 30
        assert cfg.capture.default_monitor == DEFAULTS["capture"]["default_monitor"]


# ---------------------------------------------------------------------------
# Full settings.yaml load
# ---------------------------------------------------------------------------

class TestFullYamlLoad:
    def test_values_from_yaml_override_defaults(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=key")
        data = {
            "capture": {"fps": 30, "default_monitor": 1},
            "retry": {
                "max_attempts": 5,
                "initial_wait_sec": 2,
                "jitter_max_sec": 2,
                "element_timeout_sec": 20,
            },
            "agent": {"model": "qwen-max", "max_iterations": 10, "memory_max_tokens": 1000},
            "ui": {"preview_fps": 30, "queue_timeout_sec": 60},
        }
        yaml_path = _write_yaml(tmp_path, data)
        cfg = load_config(env_path=env_path, yaml_path=yaml_path)

        assert cfg.capture.fps == 30
        assert cfg.capture.default_monitor == 1
        assert cfg.retry.max_attempts == 5
        assert cfg.agent.model == "qwen-max"
        assert cfg.ui.queue_timeout_sec == 60

    def test_missing_yaml_file_uses_all_defaults(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=key")
        yaml_path = tmp_path / "nonexistent.yaml"
        cfg = load_config(env_path=env_path, yaml_path=yaml_path)
        assert cfg.capture.fps == DEFAULTS["capture"]["fps"]

    def test_api_key_loaded_from_env_file(self, tmp_path: Path) -> None:
        env_path = _write_env(tmp_path, "DASHSCOPE_API_KEY=from-dotenv")
        yaml_path = _write_yaml(tmp_path, {})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHSCOPE_API_KEY", None)
            cfg = load_config(env_path=env_path, yaml_path=yaml_path)
        assert cfg.dashscope_api_key == "from-dotenv"


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

# All settings keys with their section and field names
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


class TestPropertyBasedConfigLoader:
    # Feature: cv-desktop-automation-agent, Property 20: 缺失必需环境变量时启动报错
    @given(
        missing_vars=st.sets(
            st.sampled_from(REQUIRED_ENV_VARS),
            min_size=1,
        )
    )
    @settings(max_examples=100)
    def test_property_20_missing_required_env_vars_raises_error(
        self, missing_vars: set[str]
    ) -> None:
        """Property 20: 缺失必需环境变量时启动报错
        Validates: Requirements 13.4
        For any environment missing required env vars, the system must raise
        ConfigMissingError with the missing variable name in the message.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            env_path = tmp / ".env"
            env_path.write_text("", encoding="utf-8")
            yaml_path = tmp / "settings.yaml"
            yaml_path.write_text(yaml.dump({}), encoding="utf-8")

            # Build env dict without the missing vars
            base_env = {var: "dummy-value" for var in REQUIRED_ENV_VARS}
            for var in missing_vars:
                base_env.pop(var, None)

            with patch.dict(os.environ, base_env, clear=True):
                with pytest.raises(ConfigMissingError) as exc_info:
                    load_config(env_path=env_path, yaml_path=yaml_path)

            error_msg = str(exc_info.value)
            # At least one of the missing vars must appear in the error message
            assert any(var in error_msg for var in missing_vars), (
                f"Error message '{error_msg}' does not mention any of the missing vars: {missing_vars}"
            )

    # Feature: cv-desktop-automation-agent, Property 21: settings.yaml 参数缺失时使用预定义默认值
    @given(
        missing_keys=st.sets(
            st.sampled_from(_ALL_SETTINGS_KEYS),
            min_size=1,
            max_size=len(_ALL_SETTINGS_KEYS),
        )
    )
    @settings(max_examples=100)
    def test_property_21_missing_settings_use_defaults_and_log_warning(
        self, missing_keys: set[tuple[str, str]]
    ) -> None:
        """Property 21: settings.yaml 参数缺失时使用预定义默认值
        Validates: Requirements 13.5
        For any settings.yaml missing some fields, after loading, all missing fields
        must equal predefined default values, and WARNING logs must be recorded.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            env_path = tmp / ".env"
            env_path.write_text("DASHSCOPE_API_KEY=test-key", encoding="utf-8")

            # Build a partial settings dict with missing_keys removed
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

            # Capture WARNING logs via a log handler
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

            # Verify all missing fields have the correct default values
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

            # Verify WARNING was logged for each missing field
            warning_messages = [r.getMessage() for r in log_records if r.levelno == logging.WARNING]
            for section, key in missing_keys:
                assert any(key in msg for msg in warning_messages), (
                    f"No WARNING logged for missing {section}.{key}. Warnings: {warning_messages}"
                )
