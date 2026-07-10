"""自動ページめくりプログラム GUI版。

開始/一時停止/終了ボタンと、状態・ページ数・ログ表示を持つ小さな窓。
ページめくりループはバックグラウンドスレッドで実行し、UIをブロックしない。
ホットキー（F9/F10）も併用可能。
"""
import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

import keyboard

import main as core
from logger_setup import setup_logger

logger = setup_logger()


class QueueLogHandler(logging.Handler):
    """ログレコードをキューに積む。GUI側がポーリングして表示する。"""

    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


class App:
    def __init__(self, root: tk.Tk, config: dict) -> None:
        self.root = root
        self.config = config
        self.controller = core.Controller()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title("自動ページめくり")
        root.geometry("560x420")
        root.minsize(460, 340)

        self._build_widgets()
        self._attach_log_handler()
        self._setup_hotkeys()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_logs()
        self._refresh_status()

    # --- UI構築 -------------------------------------------------------------
    def _build_widgets(self) -> None:
        info = (
            f"対象: {self.config['target_window_title']}   "
            f"キー: {self.config['turn_key']}   "
            f"間隔: {self.config['min_interval']}〜{self.config['max_interval']}秒"
        )
        tk.Label(self.root, text=info, anchor="w", fg="#555").pack(fill="x", padx=10, pady=(10, 4))

        status_frame = tk.Frame(self.root)
        status_frame.pack(fill="x", padx=10)
        self.status_var = tk.StringVar(value="状態: 一時停止中")
        self.count_var = tk.StringVar(value="ページ: 0")
        tk.Label(status_frame, textvariable=self.status_var, font=("", 12, "bold")).pack(side="left")
        tk.Label(status_frame, textvariable=self.count_var, font=("", 12)).pack(side="right")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=8)
        self.start_btn = tk.Button(
            btn_frame, text="開始 (F9)", width=12, height=2, command=self.on_toggle
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.stop_btn = tk.Button(
            btn_frame, text="終了 (F10)", width=12, height=2, command=self.on_stop
        )
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        tk.Label(self.root, text="ログ:", anchor="w").pack(fill="x", padx=10)
        self.log_view = scrolledtext.ScrolledText(self.root, height=12, state="disabled", wrap="word")
        self.log_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _attach_log_handler(self) -> None:
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)

    def _setup_hotkeys(self) -> None:
        try:
            keyboard.add_hotkey("F9", self.on_toggle)
            keyboard.add_hotkey("F10", self.on_stop)
        except Exception as e:  # 権限不足等
            logger.warning("ホットキー登録に失敗しました（ボタンで操作してください）: %s", e)

    # --- 動作 ---------------------------------------------------------------
    def _ensure_worker(self) -> None:
        """ループスレッドが未起動なら起動する。"""
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(
                target=core.run_loop, args=(self.config, self.controller), daemon=True
            )
            self.worker.start()

    def on_toggle(self) -> None:
        if self.controller.stopped:
            return
        self.controller.toggle_pause()
        if not self.controller.paused:
            self._ensure_worker()

    def on_stop(self) -> None:
        self.controller.stop()
        self.start_btn.config(state="disabled")

    def on_close(self) -> None:
        self.controller.stop()
        keyboard.unhook_all_hotkeys()
        self.root.after(200, self.root.destroy)

    # --- 定期更新 -----------------------------------------------------------
    def _poll_logs(self) -> None:
        while not self.log_queue.empty():
            line = self.log_queue.get_nowait()
            self.log_view.config(state="normal")
            self.log_view.insert("end", line + "\n")
            self.log_view.see("end")
            self.log_view.config(state="disabled")
        self.root.after(150, self._poll_logs)

    def _refresh_status(self) -> None:
        self.status_var.set(f"状態: {self.controller.status}")
        self.count_var.set(f"ページ: {self.controller.turn_count}")
        self.start_btn.config(text="一時停止 (F9)" if not self.controller.paused else "開始 (F9)")
        self.root.after(200, self._refresh_status)


def run() -> None:
    config = core._load_config_safely()
    if config is None:
        # 設定エラー時は最小限のメッセージ窓を出す
        root = tk.Tk()
        root.title("自動ページめくり - 設定エラー")
        tk.Label(
            root,
            text="config.json の読み込みに失敗しました。\nlogs/app.log を確認してください。",
            padx=20, pady=20, justify="left",
        ).pack()
        root.mainloop()
        return

    root = tk.Tk()
    App(root, config)
    root.mainloop()


if __name__ == "__main__":
    run()
