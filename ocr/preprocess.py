"""決定論的な本文領域切り出しと二値化。"""

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .errors import InputImageError, PreprocessError
from .models import PreprocessResult

_CROP_RATIO = 0.86


def _longest_run(profile: list[float], min_ratio: float = 0.5) -> tuple[int, int]:
    best = (0, 0)
    start = None
    for index, value in enumerate(profile):
        if value >= min_ratio and start is None:
            start = index
        elif value < min_ratio and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    if start is not None and len(profile) - start > best[1] - best[0]:
        best = (start, len(profile))
    return best


def content_box(gray: Image.Image) -> tuple[int, int, int, int]:
    width, height = gray.size
    white = gray.point(lambda value: 255 if value > 235 else 0)
    rows = [value / 255 for value in white.resize((1, height), Image.Resampling.BOX).tobytes()]
    cols = [value / 255 for value in white.resize((width, 1), Image.Resampling.BOX).tobytes()]
    top, bottom = _longest_run(rows)
    left, right = _longest_run(cols)
    if bottom - top < height * 0.2 or right - left < width * 0.2:
        margin_x = int(width * (1 - _CROP_RATIO) / 2)
        margin_y = int(height * (1 - _CROP_RATIO) / 2)
        return margin_x, margin_y, width - margin_x, height - margin_y
    inset_x = int((right - left) * 0.02)
    inset_y = int((bottom - top) * 0.02)
    return left + inset_x, top + inset_y, right - inset_x, bottom - inset_y


def otsu_threshold(histogram: list[int]) -> int:
    total = sum(histogram)
    if total <= 0:
        raise PreprocessError("空の画像histogramです")
    sum_all = sum(index * count for index, count in enumerate(histogram))
    sum_background = 0
    weight_background = 0
    best_threshold, best_variance = 0, -1.0
    for threshold in range(256):
        weight_background += histogram[threshold]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += threshold * histogram[threshold]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def preprocess_page(path: Path) -> PreprocessResult:
    if not path.is_file():
        raise InputImageError(f"入力画像が見つかりません: {path}")
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            original_size = source.size
            gray = source.convert("L")
    except (OSError, UnidentifiedImageError) as exc:
        raise InputImageError(f"入力を画像として読めません: {path}") from exc

    try:
        box = content_box(gray)
        cropped = gray.crop(box)
        threshold = otsu_threshold(cropped.histogram())
        binary = cropped.point(lambda value: 0 if value <= threshold else 255, mode="1")
    except InputImageError:
        raise
    except Exception as exc:
        raise PreprocessError(f"画像前処理に失敗しました: {path.name}") from exc
    return PreprocessResult(binary, original_size, box, binary.size, threshold)
