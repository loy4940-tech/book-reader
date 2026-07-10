"""待機時間の算出ロジック。固定値ではなく範囲内のランダム値を毎回算出する。"""
import random


def calc_wait_time(
    min_interval: float,
    max_interval: float,
    distribution: str = "uniform",
) -> float:
    """min_interval〜max_intervalの範囲でランダムな待機時間（秒）を算出する。

    distribution:
      - "uniform": 一様分布（範囲内で均等）
      - "gaussian": 正規分布（範囲の中央付近に集中しやすい）。範囲外は丸める。
    """
    if min_interval < 0 or max_interval < 0:
        raise ValueError("待機時間は0以上である必要があります")
    if min_interval > max_interval:
        raise ValueError("min_intervalはmax_interval以下である必要があります")

    if distribution == "gaussian":
        mean = (min_interval + max_interval) / 2
        # 範囲の約99.7%（±3σ）が収まるようにσを設定
        sigma = (max_interval - min_interval) / 6
        value = random.gauss(mean, sigma)
        return max(min_interval, min(max_interval, value))

    return random.uniform(min_interval, max_interval)
