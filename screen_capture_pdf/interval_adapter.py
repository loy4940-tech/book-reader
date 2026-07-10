"""既存のランダム設定ロジックと撮影モジュールを接続する。

撮影モジュール側で独自にランダム間隔を決めず、既存の timing.calc_wait_time と
config の min_interval/max_interval から次回撮影までの秒数を取得する。
取得に失敗した場合のみ fallback_seconds を返す。
"""
from timing import calc_wait_time


class IntervalAdapter:
    def __init__(self, config: dict, fallback_seconds: int = 60) -> None:
        self._config = config
        self._fallback_seconds = fallback_seconds

    def get_next_interval_seconds(self) -> float:
        """次回撮影までの待機秒数を返す。既存ロジック失敗時はfallback。"""
        try:
            return calc_wait_time(
                self._config["min_interval"],
                self._config["max_interval"],
                self._config.get("jitter_distribution", "uniform"),
            )
        except Exception:
            return float(self._fallback_seconds)
