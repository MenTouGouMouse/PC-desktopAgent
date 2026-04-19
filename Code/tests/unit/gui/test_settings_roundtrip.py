"""
Property-based tests for PythonAPI settings save/load round-trip.

# Feature: liquid-glass-gui, Property 8: settings save/load round-trip
Validates: Requirements 10.1, 10.4
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gui.app import PythonAPI, UserSettings


# ---------------------------------------------------------------------------
# Strategy: arbitrary path strings without null bytes
# ---------------------------------------------------------------------------

path_text = st.text(min_size=0, max_size=200).filter(lambda s: "\x00" not in s)


# ---------------------------------------------------------------------------
# Property 8: settings save/load round-trip
# ---------------------------------------------------------------------------

@given(
    source=path_text,
    target=path_text,
    installer_dir=path_text,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_settings_round_trip(
    source: str,
    target: str,
    installer_dir: str,
) -> None:
    """
    # Feature: liquid-glass-gui, Property 8: settings save/load round-trip

    For any triple of path strings (source, target, installerDir),
    calling _save_user_settings followed by _load_user_settings SHALL
    return the same three path values unchanged.

    Validates: Requirements 10.1, 10.4
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings_file = Path(tmp_dir) / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_file):
            api = PythonAPI.__new__(PythonAPI)

            data: UserSettings = {
                "organize_source": source,
                "organize_target": target,
                "installer_default_dir": installer_dir,
            }
            api._save_user_settings(data)
            loaded = api._load_user_settings()

    assert loaded["organize_source"] == source
    assert loaded["organize_target"] == target
    assert loaded["installer_default_dir"] == installer_dir
