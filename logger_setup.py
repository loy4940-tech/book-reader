"""ロギング設定モジュール。コンソールとファイルの両方にログを出力する。"""
import logging
import sys

from app_paths import base_dir

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOG_DIR = base_dir() / "logs"
LOG_FILE = LOG_DIR / "app.log"


def setup_logger(name: str = "book_reader", level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
