"""キャプチャ済みページ画像を解析し、OCR適性を判定する。

解像度・推定文字サイズ・組方向（縦書き/横書き）・言語を推定して、
どのOCR設定を適用すべきかを提示する。Pillow以外の依存を持たない。

判定の考え方:
  - 組方向: 行と行の間には必ず空白帯ができる。行方向にインク量を集計して
    空白帯が並べば横書き、列方向に並べば縦書き。自己相関では横書きの
    「文字ピッチ」も周期として拾ってしまうため、空白帯の割合で判定する。
  - 文字サイズ: 検出した各帯の幅がそのまま文字の高さ（縦書きなら幅）になる。
  - 言語: パス（書名）に含まれるCJK文字の比率で判定する。フォルダ名は
    ウィンドウタイトル由来なので、OCR前からエンジンを選択できる。

使い方:
    python tools/page_analyze.py <画像ファイル or フォルダ> [...] [--limit N]
"""
import argparse
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# 解析対象から除外する外周の比率（ウィンドウ枠・ツールバー・ページ番号を落とす）
_CROP_RATIO = 0.86
# 空白帯とインク帯を分けるしきい値（プロファイルの振れ幅に対する割合）
_BAND_THRESHOLD = 0.2
# 行として認めるのに必要な最小の帯数
_MIN_BANDS = 3

# OCRに必要な文字サイズ（px）。CJKは画数が多くラテン文字より高い解像度を要する。
_THRESHOLDS = {"jpn": (32, 24), "eng": (22, 16)}


@dataclass
class ProfileStats:
    """1方向のインク量プロファイルから得た統計。"""
    bands: int          # 検出した帯（＝行）の数
    blank_ratio: float  # 空白が占める割合
    pitch: float        # 帯の間隔（行送り）
    glyph: float        # 帯の幅（＝文字サイズ）


def _is_cjk(ch: str) -> bool:
    """漢字・かな（CJK圏の表意/音節文字）かどうかを返す。"""
    if ch in "、。「」『』（）・ー":
        return True
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return name.startswith(("CJK UNIFIED", "HIRAGANA", "KATAKANA"))


def detect_language(text: str) -> str:
    """書名等の文字列から言語を推定する。jpn / eng / unknown を返す。"""
    letters = [c for c in text if c.isalpha() or _is_cjk(c)]
    if not letters:
        return "unknown"
    ratio = sum(1 for c in letters if _is_cjk(c)) / len(letters)
    # 和書は英単語を含みがちなので、しきい値は低めに取る
    return "jpn" if ratio >= 0.15 else "eng"


def _otsu_threshold(hist: list) -> int:
    """256階調ヒストグラムから大津の二値化しきい値を求める。"""
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = 0
    weight_b = 0
    best_t, best_var = 0, -1.0
    for t in range(256):
        weight_b += hist[t]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += t * hist[t]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        var = weight_b * weight_f * (mean_b - mean_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def _ink_profile(binary: Image.Image, axis: str) -> list:
    """行方向/列方向のインク量プロファイルを返す。

    BOXフィルタでの1px縮小は各行（列）の平均値そのものなので、
    numpyなしでも1回のリサイズで集計できる。
    """
    width, height = binary.size
    size = (1, height) if axis == "row" else (width, 1)
    reduced = binary.resize(size, Image.BOX)
    return [(255 - v) / 255.0 for v in reduced.tobytes()]


def _profile_stats(profile: list) -> ProfileStats:
    """プロファイルからインク帯を切り出し、帯数・空白率・行送り・文字幅を求める。"""
    # 見出しや図版が1行だけ極端に濃いと最大値が跳ねるため、分位点を基準にする
    ordered = sorted(profile)
    low = ordered[int(len(ordered) * 0.05)]
    high = ordered[int(len(ordered) * 0.90)]
    if high - low <= 0:
        return ProfileStats(0, 0.0, 0.0, 0.0)

    threshold = low + (high - low) * _BAND_THRESHOLD
    bands, start = [], None
    for i, value in enumerate(profile):
        if value > threshold and start is None:
            start = i
        elif value <= threshold and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(profile)))

    if not bands:
        return ProfileStats(0, 1.0, 0.0, 0.0)

    ink = sum(end - begin for begin, end in bands)
    blank_ratio = 1.0 - ink / len(profile)
    glyph = ink / len(bands)

    if len(bands) >= 2:
        centers = [(begin + end) / 2 for begin, end in bands]
        pitch = (centers[-1] - centers[0]) / (len(centers) - 1)
    else:
        pitch = 0.0

    return ProfileStats(len(bands), blank_ratio, pitch, glyph)


def _longest_run(profile: list, min_ratio: float = 0.5) -> tuple:
    """しきい値以上の値が最も長く続く区間を返す。"""
    best = (0, 0)
    start = None
    for i, value in enumerate(profile):
        if value >= min_ratio:
            if start is None:
                start = i
        elif start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if start is not None and len(profile) - start > best[1] - best[0]:
        best = (start, len(profile))
    return best


def _content_box(gray: Image.Image) -> tuple:
    """白いページ領域を検出して矩形を返す。

    Kindleのウィンドウにはタイトルバー・ツールバー・サイドバー・
    ステータスバーが含まれる。これらは暗色なので、白画素が占める割合が
    高い行・列の最長区間を取れば本文の表示領域だけを切り出せる。
    """
    width, height = gray.size
    white = gray.point(lambda v: 255 if v > 235 else 0)
    rows = [v / 255 for v in white.resize((1, height), Image.BOX).tobytes()]
    cols = [v / 255 for v in white.resize((width, 1), Image.BOX).tobytes()]

    top, bottom = _longest_run(rows)
    left, right = _longest_run(cols)

    # 検出できなければ中央を切り出すだけに留める
    if bottom - top < height * 0.2 or right - left < width * 0.2:
        margin_x = int(width * (1 - _CROP_RATIO) / 2)
        margin_y = int(height * (1 - _CROP_RATIO) / 2)
        return margin_x, margin_y, width - margin_x, height - margin_y

    # ページ端の罫線や影を避けるため、内側にわずかに寄せる
    inset_x = int((right - left) * 0.02)
    inset_y = int((bottom - top) * 0.02)
    return left + inset_x, top + inset_y, right - inset_x, bottom - inset_y


def analyze_image(path: Path, language: str) -> dict:
    """1枚のページ画像を解析して指標をまとめる。"""
    with Image.open(path) as im:
        width, height = im.size
        gray = im.convert("L")

    box = _content_box(gray)
    gray = gray.crop(box)
    content_size = (box[2] - box[0], box[3] - box[1])

    threshold = _otsu_threshold(gray.histogram())
    binary = gray.point(lambda v: 0 if v <= threshold else 255)

    row = _profile_stats(_ink_profile(binary, "row"))
    col = _profile_stats(_ink_profile(binary, "col"))

    # 行間の空白が多く現れた方向を「行が並ぶ方向」とみなす
    row_ok = row.bands >= _MIN_BANDS
    col_ok = col.bands >= _MIN_BANDS
    if row_ok and (not col_ok or row.blank_ratio >= col.blank_ratio):
        direction, stats = "horizontal", row
    elif col_ok:
        direction, stats = "vertical", col
    else:
        direction, stats = "unknown", ProfileStats(0, 0.0, 0.0, 0.0)

    glyph_px = round(stats.glyph, 1)
    good, fair = _THRESHOLDS.get(language, _THRESHOLDS["eng"])
    if direction == "unknown" or glyph_px <= 0:
        verdict = "判定不能"
    elif glyph_px >= good:
        verdict = "良好"
    elif glyph_px >= fair:
        verdict = "やや不足"
    else:
        verdict = "不足"

    return {
        "path": path,
        "size": (width, height),
        "content": content_size,
        "direction": direction,
        "row_blank": round(row.blank_ratio, 3),
        "col_blank": round(col.blank_ratio, 3),
        "lines": stats.bands,
        "pitch": round(stats.pitch, 1),
        "glyph_px": glyph_px,
        "verdict": verdict,
    }


def recommend(language: str, direction: str) -> str:
    """言語と組方向からTesseractの推奨設定を返す。"""
    if language == "jpn":
        if direction == "vertical":
            return "tesseract -l jpn_vert --psm 5   （縦書き日本語）"
        return "tesseract -l jpn --psm 6        （横書き日本語）"
    if language == "eng":
        return "tesseract -l eng --psm 6        （英語）"
    return "（言語が特定できないため要指定）"


def _collect(target: Path, limit: int) -> list:
    """解析対象の画像を集める。フォルダの場合は均等に間引く。"""
    if target.is_file():
        return [target]
    images = sorted(target.rglob("*.png"))
    if len(images) <= limit:
        return images
    step = len(images) / limit
    return [images[int(i * step)] for i in range(limit)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ページ画像のOCR適性を解析する")
    parser.add_argument("targets", nargs="+", help="画像ファイルまたはフォルダ")
    parser.add_argument("--limit", type=int, default=5,
                        help="フォルダ指定時に解析する枚数（既定: 5）")
    args = parser.parse_args(argv)

    for target_arg in args.targets:
        target = Path(target_arg)
        if not target.exists():
            print(f"[skip] 見つかりません: {target}")
            continue

        images = _collect(target, args.limit)
        if not images:
            print(f"[skip] PNGがありません: {target}")
            continue

        # 書名はフォルダ名に含まれるため、パス全体から言語を推定する
        language = detect_language(str(target.resolve()))
        title = target.name if target.is_dir() else target.parent.parent.name

        print(f"\n=== {title[:70]} ===")
        print(f"言語判定: {language} / 解析枚数: {len(images)}")
        print(f"{'ファイル':<18}{'本文領域':>13}{'組方向':>11}{'行数':>6}"
              f"{'送り':>7}{'文字px':>8}  判定")
        print("-" * 78)

        directions, glyphs = [], []
        for image_path in images:
            r = analyze_image(image_path, language)
            directions.append(r["direction"])
            if r["glyph_px"]:
                glyphs.append(r["glyph_px"])
            print(f"{image_path.name:<18}"
                  f"{r['content'][0]:>6}x{r['content'][1]:<6}"
                  f"{r['direction']:>11}{r['lines']:>6}{r['pitch']:>7}"
                  f"{r['glyph_px']:>8}  {r['verdict']}")

        major = max(set(directions), key=directions.count)
        print("-" * 96)
        if glyphs:
            print(f"推定文字サイズ 中央値: {sorted(glyphs)[len(glyphs) // 2]} px")
        print(f"推奨設定: {recommend(language, major)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
