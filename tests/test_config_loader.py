"""config_loader.py のユニットテスト。"""
import json

import pytest

from config_loader import load_config, validate_config


def _valid_config() -> dict:
    return {
        "target_window_title": "Legacy Kindle for PC",
        "turn_key": "right",
        "min_interval": 8,
        "max_interval": 14,
        "jitter_distribution": "uniform",
        "max_turns": None,
    }


def test_valid_config_passes():
    validate_config(_valid_config())


def test_missing_required_key_raises():
    config = _valid_config()
    del config["turn_key"]
    with pytest.raises(ValueError, match="必須項目"):
        validate_config(config)


def test_min_greater_than_max_raises():
    config = _valid_config()
    config["min_interval"] = 20
    with pytest.raises(ValueError):
        validate_config(config)


def test_negative_interval_raises():
    config = _valid_config()
    config["min_interval"] = -1
    with pytest.raises(ValueError):
        validate_config(config)


def test_invalid_distribution_raises():
    config = _valid_config()
    config["jitter_distribution"] = "poisson"
    with pytest.raises(ValueError):
        validate_config(config)


def test_invalid_max_turns_raises():
    config = _valid_config()
    config["max_turns"] = 0
    with pytest.raises(ValueError):
        validate_config(config)


def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_valid_config()), encoding="utf-8")
    loaded = load_config(config_file)
    assert loaded["target_window_title"] == "Legacy Kindle for PC"
