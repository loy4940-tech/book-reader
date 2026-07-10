"""設定ファイルの読み込みと検証。"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

REQUIRED_KEYS = ("target_window_title", "turn_key", "min_interval", "max_interval")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """config.jsonを読み込み、必須項目と値の妥当性を検証して返す。"""
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    """設定内容の妥当性を検証する。不正なら ValueError を送出する。"""
    for key in REQUIRED_KEYS:
        if key not in config:
            raise ValueError(f"設定に必須項目がありません: {key}")

    min_interval = config["min_interval"]
    max_interval = config["max_interval"]

    if not isinstance(min_interval, (int, float)) or not isinstance(max_interval, (int, float)):
        raise ValueError("min_interval / max_interval は数値である必要があります")
    if min_interval < 0 or max_interval < 0:
        raise ValueError("待機時間は0以上である必要があります")
    if min_interval > max_interval:
        raise ValueError("min_intervalはmax_interval以下である必要があります")

    distribution = config.get("jitter_distribution", "uniform")
    if distribution not in ("uniform", "gaussian"):
        raise ValueError(f"jitter_distributionは 'uniform' または 'gaussian' である必要があります: {distribution}")

    max_turns = config.get("max_turns")
    if max_turns is not None and (not isinstance(max_turns, int) or max_turns <= 0):
        raise ValueError("max_turns は null または正の整数である必要があります")

    threshold = config.get("diff_threshold", 0.01)
    if not isinstance(threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
        raise ValueError("diff_threshold は 0.0〜1.0 の数値である必要があります")

    max_no_change = config.get("max_consecutive_no_change", 3)
    if not isinstance(max_no_change, int) or max_no_change <= 0:
        raise ValueError("max_consecutive_no_change は正の整数である必要があります")
