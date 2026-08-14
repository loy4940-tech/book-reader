"""キャプチャセッションの整合性と、2系統のconfigの差分を検証する。

Phase 6 の検証用。OCRに入る前に、原本が揃っているか・数が合っているかを確認する。

検証項目:
  - metadata.json の success 件数
  - images/ の実PNG枚数
  - PDFのページ数（success + 概要ページ と一致するか）
  - ユニークページ数（重複キャプチャの検出。PNGが残っている場合のみ）

使い方:
    python tools/verify_session.py                 # dist/output 配下を全件検証
    python tools/verify_session.py <セッションフォルダ>
    python tools/verify_session.py --config-diff   # config.json と dist/config.json の差分
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from config_defaults import DEFAULTS, known_keys  # noqa: E402
from config_loader import REQUIRED_KEYS  # noqa: E402

_DEFAULT_OUTPUT = _ROOT / "dist" / "output"

# 重複判定に使う縮小サイズ。これ以上細かくしてもページ差の検出精度は上がらない。
_HASH_SIZE = 16


def _page_hash(path: Path) -> str:
    """ページ画像の縮小グレースケールから簡易ハッシュを作る。"""
    with Image.open(path) as im:
        small = im.convert("L").resize((_HASH_SIZE, _HASH_SIZE), Image.BOX)
    data = small.tobytes()
    average = sum(data) / len(data)
    bits = "".join("1" if v > average else "0" for v in data)
    return f"{int(bits, 2):064x}"


def _pdf_page_count(pdf_path: Path) -> int:
    """PDFのページ数を読む。reportlab出力を前提とした軽量パース。"""
    data = pdf_path.read_bytes()
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(counts)
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def _summary_page_setting(meta: dict) -> tuple:
    """概要ページを付けたかどうかと、その情報の出典を返す。

    生成時点の値が metadata にあればそれを使う（設定は後から変わりうるため）。
    記録のない旧セッションのみ、現在の設定から推定する。
    """
    recorded = meta.get("pdf_summary_page")
    if recorded is not None:
        return bool(recorded), "metadata"

    runtime = _ROOT / "dist" / "config.json"
    path = runtime if runtime.exists() else _ROOT / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        value = config.get("screen_capture", {}).get("output", {}).get("add_summary_page")
    except (OSError, ValueError):
        value = None
    if value is None:
        value = DEFAULTS["screen_capture"]["output"]["add_summary_page"]
    return bool(value), "推定(現在の設定)"


def verify_session(session_dir: Path) -> bool:
    """1セッションを検証する。矛盾がなければ True を返す。"""
    print(f"\n=== {session_dir.name[:70]} ===")

    metadata_path = session_dir / "metadata.json"
    if not metadata_path.exists():
        print("  metadata.json がありません → 検証不能")
        return False

    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    captures = meta.get("captures", [])
    success = [c for c in captures if c.get("status") == "success"]
    skipped = len(captures) - len(success)
    print(f"  metadata : success {len(success)} 件 / skip {skipped} 件")

    images = sorted((session_dir / "images").glob("*.png")) \
        if (session_dir / "images").is_dir() else []
    deleted = meta.get("images_deleted_after_pdf", False)
    note = "（PDF生成後に削除済み）" if deleted and not images else ""
    print(f"  PNG      : {len(images)} 枚 {note}")

    pdfs = list(session_dir.glob("*.pdf"))
    ok = True
    if pdfs:
        pages = _pdf_page_count(pdfs[0])
        summary, source = _summary_page_setting(meta)
        expected = len(success) + (1 if summary else 0)
        mark = "OK" if pages == expected else "不一致"
        if pages != expected:
            ok = False
        print(f"  PDF      : {pages} ページ "
              f"(期待 {expected} = success {len(success)} + 概要 {int(bool(summary))}"
              f" / 概要有無の出典: {source}) → {mark}")

        recorded = meta.get("pdf_page_count")
        if recorded is not None and recorded != pages:
            print(f"  ⚠ metadata記録のページ数({recorded})とPDF実測({pages})が不一致")
            ok = False
    else:
        print("  PDF      : なし")

    if images:
        if len(images) != len(success):
            print(f"  ⚠ PNG枚数({len(images)})と success({len(success)}) が不一致")
            ok = False
        hashes = {}
        for path in images:
            hashes.setdefault(_page_hash(path), []).append(path.name)
        duplicates = {h: names for h, names in hashes.items() if len(names) > 1}
        print(f"  ユニーク  : {len(hashes)} ページ / 重複 {len(images) - len(hashes)} 枚")
        for names in list(duplicates.values())[:5]:
            print(f"      重複: {', '.join(names[:6])}")
    else:
        print("  ユニーク  : 判定不可（PNGなし）")

    state = "captured" if images else ("png_purged" if deleted else "unknown")
    print(f"  状態     : {state}")
    return ok


def _flatten(data: dict, prefix: str = "") -> dict:
    """ネストしたdictをドット区切りのフラットなdictに変換する。"""
    flat = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def check_config_schema() -> bool:
    """実行時設定がアプリのスキーマと互換かを検証する。

    値の違いはユーザーによる意図的な上書きなので正常。
    検出すべきは「必須項目の欠落」と「既定値に存在しない未知キー（綴り誤り）」。
    既定値にある項目が実行時設定に無いのは、起動時にマージで補われるため正常。
    """
    known = known_keys() | set(REQUIRED_KEYS)
    ok = True

    for label, path in (("正本テンプレート", _ROOT / "config.json"),
                        ("実行時設定", _ROOT / "dist" / "config.json")):
        print(f"\n--- {label}: {path} ---")
        if not path.exists():
            print("  ファイルがありません（build.bat 実行時に作成されます）")
            continue

        flat = _flatten(json.loads(path.read_text(encoding="utf-8")))

        missing = [k for k in REQUIRED_KEYS if k not in flat]
        if missing:
            print(f"  ✕ 必須項目の欠落: {', '.join(missing)}")
            ok = False

        unknown = sorted(k for k in flat if k not in known)
        if unknown:
            # 綴り誤りは既定値が採用されて設定が黙って無効になるためエラー扱い
            print("  ✕ 既定値に存在しない項目（綴り誤りの可能性）:")
            for key in unknown:
                print(f"      {key} = {flat[key]!r}")
            ok = False

        # 既定値から変更されている項目＝意図的な上書き（正常）
        defaults_flat = _flatten(DEFAULTS)
        overrides = sorted(k for k in flat if k in defaults_flat and flat[k] != defaults_flat[k])
        if overrides:
            print("  上書きされている項目（正常）:")
            for key in overrides:
                print(f"      {key}: 既定={defaults_flat[key]!r} → {flat[key]!r}")

        supplied = sorted(set(defaults_flat) - set(flat))
        if supplied:
            print(f"  既定値で補われる項目: {len(supplied)} 件（マージにより正常動作）")

        if not (missing or unknown):
            print("  スキーマ互換: OK")

    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="セッション整合性とconfig差分を検証する")
    parser.add_argument("targets", nargs="*", help="セッションフォルダ（省略時は全件）")
    parser.add_argument("--config-diff", action="store_true",
                        help="設定ファイルのスキーマ互換性のみ検証")
    args = parser.parse_args(argv)

    if args.config_diff:
        return 0 if check_config_schema() else 1

    if args.targets:
        sessions = [Path(t) for t in args.targets]
    else:
        if not _DEFAULT_OUTPUT.is_dir():
            print(f"出力フォルダがありません: {_DEFAULT_OUTPUT}")
            return 1
        sessions = sorted(d for d in _DEFAULT_OUTPUT.iterdir() if d.is_dir())

    all_ok = True
    for session in sessions:
        if not session.is_dir():
            print(f"[skip] フォルダがありません: {session}")
            continue
        if not verify_session(session):
            all_ok = False

    print(f"\n検証したセッション: {len(sessions)} 件 / "
          f"総合判定: {'OK' if all_ok else '要確認'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
