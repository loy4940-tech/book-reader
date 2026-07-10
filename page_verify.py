"""ページ遷移検証。キー送信の前後でスクリーンショットを比較し、
本文領域が実際に変化したか（＝ページがめくれたか）を判定する。
"""
from PIL import Image, ImageChops

# この値より差分が小さければ「ページが変化していない」と判定する（0.0〜1.0）
DEFAULT_DIFF_THRESHOLD = 0.01


def diff_ratio(before: Image.Image, after: Image.Image) -> float:
    """2枚の画像の差分の大きさを 0.0〜1.0 の比率で返す。

    0.0 = 完全に同一、値が大きいほど変化が大きい。
    サイズが異なる場合は after を before のサイズに合わせる。
    """
    if before.size != after.size:
        after = after.resize(before.size)

    before_gray = before.convert("L")
    after_gray = after.convert("L")

    diff = ImageChops.difference(before_gray, after_gray)
    histogram = diff.histogram()

    # 各輝度差（0〜255）× そのピクセル数 の総和を、最大可能差分で正規化
    total_diff = sum(i * count for i, count in enumerate(histogram))
    num_pixels = before_gray.width * before_gray.height
    max_diff = num_pixels * 255

    if max_diff == 0:
        return 0.0
    return total_diff / max_diff


def page_changed(
    before: Image.Image,
    after: Image.Image,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
) -> bool:
    """差分が閾値を超えていれば「ページが変化した」と判定する。"""
    return diff_ratio(before, after) > threshold
