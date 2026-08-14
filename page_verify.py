"""ページ遷移検証。キー送信の前後で本文領域の変化を判定する。"""
from enum import Enum
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageChops

# この値より差分が小さければ「ページが変化していない」と判定する（0.0〜1.0）
DEFAULT_DIFF_THRESHOLD = 0.01

# Kindle の固定UIと広い余白による差分希釈を避ける既定領域。
# 正規化座標なのでwindow sizeには依存せず、呼出側から明示的に差し替え可能。
DEFAULT_CONTENT_ROI = (0.1, 0.1, 0.9, 0.9)
DEFAULT_BLOCK_CONTENT_ROI = (0.03, 0.10, 0.97, 0.95)
DEFAULT_BLOCK_GRID = (4, 4)
DEFAULT_BLOCK_TOP_K = 2

NormalizedRoi = Tuple[float, float, float, float]


class PageChangeState(str, Enum):
    CHANGE_CONFIRMED = "change_confirmed"
    NO_CHANGE_RETRY_EXHAUSTED = "no_change_retry_exhausted"


def _crop_roi(image: Image.Image, roi: Optional[NormalizedRoi]) -> Image.Image:
    if roi is None:
        return image
    if len(roi) != 4:
        raise ValueError("ROIは(left, top, right, bottom)の4要素で指定してください")
    left, top, right, bottom = roi
    if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
        raise ValueError("ROIは0.0〜1.0の範囲で正の面積を持つ必要があります")
    width, height = image.size
    box = (
        int(left * width),
        int(top * height),
        int(right * width),
        int(bottom * height),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("ROIをpixelへ変換した結果がzero-sizeです")
    return image.crop(box)


def diff_ratio(
    before: Image.Image,
    after: Image.Image,
    roi: Optional[NormalizedRoi] = None,
) -> float:
    """2枚の画像の差分の大きさを 0.0〜1.0 の比率で返す。

    0.0 = 完全に同一、値が大きいほど変化が大きい。
    サイズが異なる場合は after を before のサイズに合わせる。
    """
    if before.size != after.size:
        after = after.resize(before.size)

    before = _crop_roi(before, roi)
    after = _crop_roi(after, roi)

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
    roi: Optional[NormalizedRoi] = DEFAULT_BLOCK_CONTENT_ROI,
    block_grid: Optional[Tuple[int, int]] = DEFAULT_BLOCK_GRID,
    top_k: int = DEFAULT_BLOCK_TOP_K,
) -> bool:
    """ROI全体またはblock-wise集約が閾値を超えたか判定する。"""
    if block_grid is None:
        return diff_ratio(before, after, roi=roi) > threshold
    scores = block_diff_scores(before, after, roi=roi, grid=block_grid)
    return top_k_mean(scores, top_k) > threshold


def block_diff_scores(
    before: Image.Image,
    after: Image.Image,
    *,
    roi: NormalizedRoi = DEFAULT_BLOCK_CONTENT_ROI,
    grid: Tuple[int, int] = DEFAULT_BLOCK_GRID,
) -> List[float]:
    """content ROIをgrid分割し、各blockの既存diff metricを返す。"""
    _crop_roi(before, roi)  # ROI contractを先に検証する
    columns, rows = grid
    if columns <= 0 or rows <= 0:
        raise ValueError("block gridは正の列数・行数である必要があります")
    left, top, right, bottom = roi
    width = right - left
    height = bottom - top
    scores = []
    for row in range(rows):
        for column in range(columns):
            block_roi = (
                left + width * column / columns,
                top + height * row / rows,
                left + width * (column + 1) / columns,
                top + height * (row + 1) / rows,
            )
            scores.append(diff_ratio(before, after, roi=block_roi))
    return scores


def top_k_mean(scores: List[float], top_k: int = DEFAULT_BLOCK_TOP_K) -> float:
    """局所的だが複数blockへ分布する変化を拾うtop-k平均。"""
    if top_k <= 0:
        raise ValueError("top_kは正の整数である必要があります")
    if not scores or top_k > len(scores):
        raise ValueError("top_kはblock score数以下である必要があります")
    return sum(sorted(scores, reverse=True)[:top_k]) / top_k


def verify_page_change(
    before: Image.Image,
    capture_after: Callable[[], Optional[Image.Image]],
    *,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
    roi: Optional[NormalizedRoi] = DEFAULT_CONTENT_ROI,
    retry_count: int = 2,
    stabilization_wait: float = 0.4,
    sleep: Callable[[float], None],
) -> PageChangeState:
    """描画待ちと有限retryを行い、ページ変化の確認状態を返す。"""
    if retry_count < 0:
        raise ValueError("retry_countは0以上である必要があります")
    if stabilization_wait < 0:
        raise ValueError("stabilization_waitは0以上である必要があります")

    for _attempt in range(retry_count + 1):
        sleep(stabilization_wait)
        after = capture_after()
        if after is not None and page_changed(before, after, threshold, roi=roi):
            return PageChangeState.CHANGE_CONFIRMED
    return PageChangeState.NO_CHANGE_RETRY_EXHAUSTED
