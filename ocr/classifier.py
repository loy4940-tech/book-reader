"""書籍単位の言語とページ単位の組方向を判定する。"""

import unicodedata
from dataclasses import dataclass

from PIL import Image

from .errors import ClassifierError
from .models import ClassificationResult

_BAND_THRESHOLD = 0.2
_MIN_BANDS = 3
LANGUAGES = frozenset({"jpn", "eng", "unknown"})
ORIENTATIONS = frozenset({"vertical", "horizontal", "unknown"})


@dataclass(frozen=True)
class _ProfileStats:
    bands: int
    blank_ratio: float


def _is_cjk(character: str) -> bool:
    if character in "、。「」『』（）・ー":
        return True
    try:
        name = unicodedata.name(character)
    except ValueError:
        return False
    return name.startswith(("CJK UNIFIED", "HIRAGANA", "KATAKANA"))


def detect_language(text: str) -> str:
    letters = [character for character in text if character.isalpha() or _is_cjk(character)]
    if not letters:
        return "unknown"
    cjk_ratio = sum(1 for character in letters if _is_cjk(character)) / len(letters)
    return "jpn" if cjk_ratio >= 0.15 else "eng"


def _ink_profile(binary: Image.Image, axis: str) -> list[float]:
    width, height = binary.size
    size = (1, height) if axis == "row" else (width, 1)
    reduced = binary.convert("L").resize(size, Image.Resampling.BOX)
    return [(255 - value) / 255.0 for value in reduced.tobytes()]


def _profile_stats(profile: list[float]) -> _ProfileStats:
    if not profile:
        return _ProfileStats(0, 0.0)
    ordered = sorted(profile)
    low = ordered[int(len(ordered) * 0.05)]
    high = ordered[int(len(ordered) * 0.90)]
    if high - low <= 0:
        return _ProfileStats(0, 0.0)
    threshold = low + (high - low) * _BAND_THRESHOLD
    bands = 0
    in_band = False
    ink = 0
    for value in profile:
        if value > threshold:
            ink += 1
            if not in_band:
                bands += 1
                in_band = True
        else:
            in_band = False
    return _ProfileStats(bands, 1.0 - ink / len(profile))


def detect_orientation(binary: Image.Image) -> tuple[str, float, str]:
    try:
        row = _profile_stats(_ink_profile(binary, "row"))
        col = _profile_stats(_ink_profile(binary, "col"))
    except Exception as exc:
        raise ClassifierError("組方向判定に失敗しました") from exc
    row_ok = row.bands >= _MIN_BANDS
    col_ok = col.bands >= _MIN_BANDS
    if row_ok and (not col_ok or row.blank_ratio >= col.blank_ratio):
        gap = max(0.0, row.blank_ratio - col.blank_ratio)
        return "horizontal", min(1.0, 0.5 + gap), "row blank bands"
    if col_ok:
        gap = max(0.0, col.blank_ratio - row.blank_ratio)
        return "vertical", min(1.0, 0.5 + gap), "column blank bands"
    return "unknown", 0.0, "insufficient bands"


def classify_page(
    binary: Image.Image,
    book_identifier: str,
    *,
    language_override: str | None = None,
    orientation_override: str | None = None,
) -> ClassificationResult:
    language = language_override or detect_language(book_identifier)
    if language not in LANGUAGES:
        raise ClassifierError(f"未対応の言語指定です: {language}")
    if orientation_override:
        if orientation_override not in ORIENTATIONS:
            raise ClassifierError(f"未対応の組方向指定です: {orientation_override}")
        orientation, confidence, reason = orientation_override, 1.0, "manual override"
    else:
        orientation, confidence, reason = detect_orientation(binary)
    return ClassificationResult(language, orientation, confidence, reason)
