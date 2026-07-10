"""自動ページめくりプログラム エントリーポイント。"""
import json
from pathlib import Path

from logger_setup import setup_logger

CONFIG_PATH = Path(__file__).parent / "config.json"

logger = setup_logger()


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    logger.info("設定を読み込みました: %s", config)


if __name__ == "__main__":
    main()
