"""OCR実行環境を検証し、ocr_environment.json を生成する。

Phase 7A の導入確認と、Phase 7B の環境固定に使う。
`requirements-ocr.txt` はpipパッケージしか固定できないため、pip管理外の
Tesseract本体と traineddata のバージョン・チェックサムをここで記録する。

標準ライブラリのみで動作するため、キャプチャ側（Python 3.14）からも実行できる。

使い方:
    python tools/ocr_env_check.py            # 検証のみ
    python tools/ocr_env_check.py --write    # ocr_environment.json を生成
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _ROOT / "ocr_environment.json"

# Phase 8A の初期候補設定で必要になる言語データ
_REQUIRED_TRAINEDDATA = ("jpn", "jpn_vert", "eng")
# OCR用venvの想定バージョン（PyTorch系の対応状況から3.12を選択）
_EXPECTED_PYTHON = (3, 12)
# requirements-ocr.txt に直接記載しているPythonパッケージ
_REQUIRED_PACKAGES = ("Pillow", "pytesseract", "pytest")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tesseract_path() -> str:
    """tesseract実行ファイルのパスを返す。見つからなければ空文字。"""
    found = shutil.which("tesseract")
    if found:
        return found
    # PATHに通っていない場合の既定インストール先を探す
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return ""


def _tesseract_version(exe: str) -> str:
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    # 1行目が "tesseract v5.3.3.20231005" のような形式
    first = (result.stdout or result.stderr or "").splitlines()
    return first[0].strip() if first else ""


def _tessdata_dir(exe: str) -> Path:
    """traineddataの格納先を推定する。"""
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        directory = Path(env)
        # TESSDATA_PREFIX は tessdata の親を指す運用と、tessdata 自体を指す運用がある
        return directory if directory.name == "tessdata" else directory / "tessdata"
    if exe:
        return Path(exe).parent / "tessdata"
    return Path()


def collect() -> dict:
    """環境情報を収集する。"""
    exe = _tesseract_path()
    tessdata = _tessdata_dir(exe)

    traineddata = {}
    for name in _REQUIRED_TRAINEDDATA:
        path = tessdata / f"{name}.traineddata"
        if path.exists():
            traineddata[name] = {"path": str(path), "sha256": _sha256(path),
                                 "size_bytes": path.stat().st_size}
        else:
            traineddata[name] = None

    packages = {}
    for name in _REQUIRED_PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "python_packages": packages,
        "os": f"{platform.system()} {platform.release()}",
        "engine": "tesseract",
        "engine_path": exe,
        "engine_version": _tesseract_version(exe) if exe else "",
        "tessdata_dir": str(tessdata),
        "traineddata": traineddata,
        # Gate 1 の出発点。確定値ではない
        "candidate_parameters": {
            "ja_vertical": {"lang": "jpn_vert", "psm": 5},
            "ja_horizontal": {"lang": "jpn", "psm": 6},
            "en_horizontal": {"lang": "eng", "psm": 6},
        },
        "preprocess_version": "1",
        "classifier_version": "1",
        "pipeline_version": "1",
    }


def report(env: dict) -> bool:
    """検証結果を表示し、Phase 7A の完了条件を満たすかを返す。"""
    ok = True

    version = tuple(int(p) for p in env["python"].split(".")[:2])
    mark = "OK" if version == _EXPECTED_PYTHON else "要確認"
    if version != _EXPECTED_PYTHON:
        print(f"  Python {env['python']} → {mark}"
              f"（OCR用venvは {'.'.join(map(str, _EXPECTED_PYTHON))} を想定）")
    else:
        print(f"  Python {env['python']} → OK")

    print("  Python packages:")
    for name, version in env["python_packages"].items():
        if version is None:
            print(f"      ✕ {name} が見つかりません")
            ok = False
        else:
            print(f"      OK {name} {version}")

    if not env["engine_path"]:
        print("  ✕ tesseract が見つかりません")
        print("      PATHを通すか、既定の場所にインストールしてください")
        return False
    print(f"  {env['engine_version']}")
    print(f"      {env['engine_path']}")

    print(f"  tessdata: {env['tessdata_dir']}")
    for name, info in env["traineddata"].items():
        if info is None:
            print(f"      ✕ {name}.traineddata が見つかりません")
            ok = False
        else:
            print(f"      OK {name}.traineddata  "
                  f"{info['size_bytes'] // 1024} KB  sha256={info['sha256'][:16]}…")

    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR実行環境を検証する")
    parser.add_argument("--write", action="store_true",
                        help="ocr_environment.json を生成する")
    args = parser.parse_args(argv)

    print("=== OCR実行環境 ===")
    env = collect()
    ok = report(env)

    if args.write:
        if not ok:
            print("\n環境が不完全なため ocr_environment.json は生成しませんでした。")
            return 1
        _OUTPUT.write_text(json.dumps(env, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        print(f"\n生成しました: {_OUTPUT}")

    print(f"\n判定: {'OK（Phase 7A の完了条件を満たします）' if ok else '要対応'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
