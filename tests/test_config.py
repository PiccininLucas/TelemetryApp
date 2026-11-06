"""Tests for loading the configuration, and for the user file merged over it."""

from __future__ import annotations

import pytest

from lmu_telemetry.domain.analysis.corners import CornerDetectionSettings
from lmu_telemetry.shared import config as config_module
from lmu_telemetry.shared.config import ENV_CONFIG_PATH, load_config
from lmu_telemetry.shared.errors import ConfigError
from lmu_telemetry.infrastructure.storage import paths


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keep the developer's own `~/.lmu-telemetry/config.toml` out of the tests."""
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    monkeypatch.delenv(ENV_CONFIG_PATH, raising=False)


def write_user_config(tmp_path, text: str):
    target = tmp_path / "data" / config_module.USER_CONFIG_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_defaults_load_without_a_user_file():
    assert load_config().get("laps.max_time_mismatch_s") == 0.5


def test_a_user_file_overrides_only_what_it_names(tmp_path):
    write_user_config(tmp_path, "[laps]\nmax_time_mismatch_s = 0.25\n")

    config = load_config()

    assert config.get("laps.max_time_mismatch_s") == 0.25
    assert config.get("laps.boundary_match_tolerance_s") == 0.01  # untouched
    assert config.get("ingest.target_hz") == 100.0                # other section


def test_the_environment_can_name_the_user_file(tmp_path, monkeypatch):
    elsewhere = tmp_path / "mine.toml"
    elsewhere.write_text("[ingest]\ntarget_hz = 50.0\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CONFIG_PATH, str(elsewhere))

    assert load_config().get("ingest.target_hz") == 50.0


def test_an_unknown_key_is_an_error_not_silently_ignored(tmp_path):
    """A mistyped threshold that fell back to its default is a setting the user
    believes is applied and is not."""
    write_user_config(tmp_path, "[laps]\nmax_time_mismach_s = 0.25\n")

    with pytest.raises(ConfigError, match="laps.max_time_mismach_s"):
        load_config()


def test_an_unknown_section_is_an_error(tmp_path):
    write_user_config(tmp_path, "[nonsense]\nx = 1\n")

    with pytest.raises(ConfigError, match="nonsense"):
        load_config()


def test_a_value_where_a_section_belongs_is_an_error(tmp_path):
    write_user_config(tmp_path, "laps = 3\n")

    with pytest.raises(ConfigError, match="section"):
        load_config()


def test_invalid_toml_is_reported_with_the_file_name(tmp_path):
    target = write_user_config(tmp_path, "[laps\n")

    with pytest.raises(ConfigError, match=target.name):
        load_config()


def test_editing_the_user_file_takes_effect_without_restarting(tmp_path):
    target = write_user_config(tmp_path, "[ingest]\ntarget_hz = 50.0\n")
    assert load_config().get("ingest.target_hz") == 50.0

    target.write_text("[ingest]\ntarget_hz = 200.0\n", encoding="utf-8")

    assert load_config().get("ingest.target_hz") == 200.0


def test_an_explicit_path_ignores_the_user_file(tmp_path):
    write_user_config(tmp_path, "[ingest]\ntarget_hz = 50.0\n")

    assert load_config(config_module.DEFAULT_CONFIG_PATH).get("ingest.target_hz") == 100.0


# --------------------------------------------------------------------------- #
# The corner section is passed to a dataclass, so the two have to agree
# --------------------------------------------------------------------------- #

def test_every_shipped_corner_setting_is_a_field_of_the_settings():
    section = load_config().section("analysis")["corners"]

    settings = CornerDetectionSettings.from_config(section)

    assert settings.apex_plateau_fraction == section["apex_plateau_fraction"]


def test_an_unknown_corner_key_names_itself():
    with pytest.raises(ValueError, match="made_up_key"):
        CornerDetectionSettings.from_config({"made_up_key": 1.0})
