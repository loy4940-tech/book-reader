"""自動ページめくりプログラム エントリーポイント（方式A: 真のバックグラウンド）。

対象ウィンドウをアクティブにせず、PostMessageで直接キーを送る。
ページ遷移検証はPrintWindowで隠れたウィンドウでも撮影して行う。
"""
import json
import time

import keyboard

from config_loader import load_config
from input_sender import send_key_to_hwnd
from keys import opposite_key
from logger_setup import setup_logger
from page_verify import page_changed
from screen_capture import capture_hwnd
from timing import calc_wait_time
from window_utils import find_target_window

logger = setup_logger()


class Controller:
    """ホットキーで操作する実行状態を保持する。"""

    def __init__(self) -> None:
        self.paused = True  # 起動直後は一時停止（F9で開始）
        self.stopped = False
        # GUIから参照する状態（コンソール版では未使用）
        self.turn_count = 0
        self.current_key = None

    @property
    def status(self) -> str:
        if self.stopped:
            return "停止"
        return "一時停止中" if self.paused else "実行中"

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        logger.info("[F9] %s しました", "一時停止" if self.paused else "再開")

    def stop(self) -> None:
        self.stopped = True
        logger.info("[F10] 終了します")


def interruptible_sleep(seconds: float, controller: Controller) -> None:
    """待機中もホットキー（停止）に反応できるよう、小刻みにsleepする。"""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if controller.stopped:
            return
        time.sleep(min(0.1, max(0.0, end - time.monotonic())))


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
    auto_flip = config.get("auto_flip_on_no_change", True)

    logger.info(
        "準備完了。F9で開始/一時停止、F10で終了"
        "（対象='%s', キー='%s', 間隔=%s〜%s秒, 分布=%s, 最大=%s, 遷移検証=%s, 自動反転=%s）",
        target_title, turn_key, min_interval, max_interval, distribution,
        max_turns if max_turns is not None else "無制限",
        "有効" if verify else "無効", "有効" if auto_flip else "無効",
    )

    current_key = turn_key
    flipped_once = False
    turn_count = 0
    consecutive_no_change = 0
    controller.current_key = current_key

    while not controller.stopped and (max_turns is None or turn_count < max_turns):
        if controller.paused:
            time.sleep(0.2)
            continue

        wait_time = calc_wait_time(min_interval, max_interval, distribution)
        logger.info("待機: %.2f秒", wait_time)
        interruptible_sleep(wait_time, controller)

        if controller.stopped or controller.paused:
            continue

        window = find_target_window(target_title)
        if window is None:
            logger.warning(
                "対象ウィンドウ '%s' が見つかりません。自動的に一時停止します。"
                "アプリを開いてF9で再開してください。",
                target_title,
            )
            controller.paused = True
            continue
        hwnd = window._hWnd

        before = capture_hwnd(hwnd) if verify else None

        send_key_to_hwnd(hwnd, current_key)
        turn_count += 1
        controller.turn_count = turn_count
        logger.info("ページをめくりました（%d回目, キー=%s）", turn_count, current_key)

        if not verify:
            continue

        time.sleep(0.4)  # 描画反映を待つ
        after = capture_hwnd(hwnd)
        if before is not None and after is not None and page_changed(before, after, threshold):
            consecutive_no_change = 0
            continue

        consecutive_no_change += 1
        logger.warning("ページが変化していない可能性があります（連続%d回）", consecutive_no_change)
        if consecutive_no_change < max_no_change:
            continue

        # ③保険：起動直後に空振りが続く場合、一度だけ左右を自動反転する
        flip_target = opposite_key(current_key)
        if auto_flip and not flipped_once and flip_target is not None:
            current_key = flip_target
            controller.current_key = current_key
            flipped_once = True
            consecutive_no_change = 0
            logger.warning(
                "%d回連続で変化を検出できなかったため、ページめくり方向を自動反転しました → キー=%s"
                "（設定が逆だった可能性があります）",
                max_no_change, current_key,
            )
        else:
            controller.paused = True
            consecutive_no_change = 0
            logger.warning(
                "%d回連続で変化を検出できなかったため自動的に一時停止しました。"
                "対象アプリの状態を確認し、F9で再開してください。",
                max_no_change,
            )

    if controller.stopped:
        logger.info("ホットキー操作により終了しました")
    else:
        logger.info("最大ターン数（%s）に到達したため終了します", max_turns)


def _load_config_safely():
    """設定を読み込み、異常時は種類別にログを出してNoneを返す。"""
    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("設定ファイル config.json が見つかりません。ファイルを配置してください。")
        return None
    except json.JSONDecodeError as e:
        logger.error("config.json の書式が不正です（JSONとして読めません）: %s", e)
        return None
    except ValueError as e:
        logger.error("config.json の設定内容が不正です: %s", e)
        return None
    logger.info("設定を読み込みました: %s", config)
    return config


def _setup_hotkeys(controller: Controller) -> bool:
    """ホットキーを登録する。権限不足等で失敗した場合はFalseを返す。"""
    try:
        keyboard.add_hotkey("F9", controller.toggle_pause)
        keyboard.add_hotkey("F10", controller.stop)
    except Exception as e:  # keyboardの権限エラー等（OS/環境依存で型が一定しない）
        logger.error(
            "ホットキーの登録に失敗しました（%s）。"
            "管理者権限でPowerShellを起動して再実行してください。", e,
        )
        return False
    return True


def main() -> None:
    config = _load_config_safely()
    if config is None:
        return

    controller = Controller()
    if not _setup_hotkeys(controller):
        return

    try:
        run_loop(config, controller)
    except KeyboardInterrupt:
        logger.info("ユーザーによって中断されました（Ctrl+C）")
    except Exception:
        logger.exception("予期しないエラーが発生したため終了します")
    finally:
        keyboard.unhook_all_hotkeys()


if __name__ == "__main__":
    main()
