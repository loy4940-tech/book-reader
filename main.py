"""自動ページめくりプログラム エントリーポイント（Phase 3: ホットキー・遷移検証）。"""
import time

import keyboard
import pyautogui

from config_loader import load_config
from logger_setup import setup_logger
from page_verify import page_changed
from timing import calc_wait_time
from window_utils import capture_window, find_target_window, is_target_window_active

pyautogui.FAILSAFE = True

logger = setup_logger()


class Controller:
    """ホットキーで操作する実行状態を保持する。"""

    def __init__(self) -> None:
        self.paused = True  # 起動直後は一時停止（F9で開始）
        self.stopped = False

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        state = "一時停止" if self.paused else "再開"
        logger.info("[F9] %s しました", state)

    def stop(self) -> None:
        self.stopped = True
        logger.info("[F10] 終了します")


def interruptible_sleep(seconds: float, controller: Controller) -> None:
    """待機中もホットキー（停止）に反応できるよう、小刻みにsleepする。"""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if controller.stopped:
            return
        time.sleep(min(0.1, end - time.monotonic()))


def turn_page(turn_key: str) -> None:
    pyautogui.press(turn_key)


def run_loop(config: dict, controller: Controller) -> None:
    target_title = config["target_window_title"]
    turn_key = config["turn_key"]
    min_interval = config["min_interval"]
    max_interval = config["max_interval"]
    distribution = config.get("jitter_distribution", "uniform")
    max_turns = config.get("max_turns")
    verify = config.get("verify_page_change", True)
    threshold = config.get("diff_threshold", 0.01)
    max_no_change = config.get("max_consecutive_no_change", 3)

    logger.info(
        "準備完了。F9で開始/一時停止、F10で終了（対象='%s', キー='%s', 間隔=%s〜%s秒, 分布=%s, 最大=%s, 遷移検証=%s）",
        target_title, turn_key, min_interval, max_interval, distribution,
        max_turns if max_turns is not None else "無制限", "有効" if verify else "無効",
    )

    turn_count = 0
    consecutive_no_change = 0

    while not controller.stopped and (max_turns is None or turn_count < max_turns):
        if controller.paused:
            time.sleep(0.2)
            continue

        wait_time = calc_wait_time(min_interval, max_interval, distribution)
        logger.info("待機: %.2f秒", wait_time)
        interruptible_sleep(wait_time, controller)

        if controller.stopped or controller.paused:
            continue

        if not is_target_window_active(target_title):
            logger.warning(
                "対象ウィンドウ '%s' が非アクティブのため、ページめくりをスキップしました",
                target_title,
            )
            continue

        window = find_target_window(target_title)
        before = capture_window(window) if verify else None

        turn_page(turn_key)
        turn_count += 1
        logger.info("ページをめくりました（%d回目）", turn_count)

        if verify and before is not None:
            time.sleep(0.4)  # 描画反映を待つ
            after = capture_window(find_target_window(target_title))
            if after is not None and not page_changed(before, after, threshold):
                consecutive_no_change += 1
                logger.warning(
                    "ページが変化していない可能性があります（連続%d回）",
                    consecutive_no_change,
                )
                if consecutive_no_change >= max_no_change:
                    controller.paused = True
                    consecutive_no_change = 0
                    logger.warning(
                        "%d回連続で変化を検出できなかったため自動的に一時停止しました。"
                        "対象アプリの状態を確認し、F9で再開してください。",
                        max_no_change,
                    )
            else:
                consecutive_no_change = 0

    if controller.stopped:
        logger.info("ホットキー操作により終了しました")
    else:
        logger.info("最大ターン数（%s）に到達したため終了します", max_turns)


def main() -> None:
    config = load_config()
    logger.info("設定を読み込みました: %s", config)

    controller = Controller()
    keyboard.add_hotkey("F9", controller.toggle_pause)
    keyboard.add_hotkey("F10", controller.stop)

    try:
        run_loop(config, controller)
    except KeyboardInterrupt:
        logger.info("ユーザーによって中断されました（Ctrl+C）")
    except pyautogui.FailSafeException:
        logger.warning("フェイルセーフ（マウス四隅移動）により緊急停止しました")
    finally:
        keyboard.unhook_all_hotkeys()


if __name__ == "__main__":
    main()
