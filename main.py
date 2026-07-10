"""自動ページめくりプログラム エントリーポイント（Phase 2: コアロジック）。"""
import time

import pyautogui

from config_loader import load_config
from logger_setup import setup_logger
from timing import calc_wait_time
from window_utils import is_target_window_active

pyautogui.FAILSAFE = True

logger = setup_logger()


def turn_page(turn_key: str) -> None:
    """指定キーを送信してページをめくる。"""
    pyautogui.press(turn_key)


def run_loop(config: dict) -> None:
    """メインループ。設定に従ってランダム待機・フォーカス確認・キー送信を繰り返す。"""
    target_title = config["target_window_title"]
    turn_key = config["turn_key"]
    min_interval = config["min_interval"]
    max_interval = config["max_interval"]
    distribution = config.get("jitter_distribution", "uniform")
    max_turns = config.get("max_turns")

    logger.info(
        "ループを開始します（対象='%s', キー='%s', 間隔=%s〜%s秒, 分布=%s, 最大=%s）",
        target_title, turn_key, min_interval, max_interval, distribution,
        max_turns if max_turns is not None else "無制限",
    )

    turn_count = 0
    while max_turns is None or turn_count < max_turns:
        wait_time = calc_wait_time(min_interval, max_interval, distribution)
        logger.info("待機: %.2f秒", wait_time)
        time.sleep(wait_time)

        if not is_target_window_active(target_title):
            logger.warning(
                "対象ウィンドウ '%s' が非アクティブのため、ページめくりをスキップしました",
                target_title,
            )
            continue

        turn_page(turn_key)
        turn_count += 1
        logger.info("ページをめくりました（%d回目）", turn_count)

    logger.info("最大ターン数（%d）に到達したため終了します", max_turns)


def main() -> None:
    config = load_config()
    logger.info("設定を読み込みました: %s", config)
    try:
        run_loop(config)
    except KeyboardInterrupt:
        logger.info("ユーザーによって中断されました（Ctrl+C）")
    except pyautogui.FailSafeException:
        logger.warning("フェイルセーフ（マウス四隅移動）により緊急停止しました")


if __name__ == "__main__":
    main()
