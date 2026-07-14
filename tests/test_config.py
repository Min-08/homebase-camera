from __future__ import annotations

import pytest

from homebase_camera.config import ConfigError, load_settings


def test_invalid_numeric_setting_raises_config_error(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('[detection]\ndiff_interval_seconds = "fast"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="diff_interval_seconds must be an integer"):
        load_settings(settings)


def test_invalid_camera_dimensions_raise_config_error(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('[camera]\nframe_width = 0\nframe_height = 720\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="frame_width and frame_height"):
        load_settings(settings)
