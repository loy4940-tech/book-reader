"""対象ウィンドウを実測し、キャプチャ解像度がOCRに足りるかを診断する。

Step 1（解像度の実測）用。DPI設定の実効値・モニタ解像度・ウィンドウサイズを表示し、
実際に1枚キャプチャして page_analyze で文字サイズを推定する。
--maximize を付けると最大化前後を撮り比べ、改善幅を数値で示す。

使い方:
    python tools/capture_probe.py                # 現状のまま診断
    python tools/capture_probe.py --maximize     # 最大化前後を比較
"""
import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# screen_capture は import 時に DPI Awareness を設定するため、最初に読み込む
from screen_capture import capture_hwnd  # noqa: E402
from screen_capture_pdf.window_resolver import resolve_target  # noqa: E402
from tools.page_analyze import analyze_image, detect_language, recommend  # noqa: E402

_user32 = ctypes.WinDLL("user32")
_shcore = ctypes.WinDLL("shcore")

_AWARENESS = {0: "UNAWARE（論理px）", 1: "SYSTEM_AWARE", 2: "PER_MONITOR_AWARE（物理px）"}
_SM_CXSCREEN, _SM_CYSCREEN = 0, 1


def _dpi_awareness() -> str:
    """このプロセスに実際に適用されているDPI Awarenessを返す。"""
    value = ctypes.c_int()
    try:
        if _shcore.GetProcessDpiAwareness(None, ctypes.byref(value)) != 0:
            return "取得失敗"
    except (OSError, AttributeError):
        return "取得不可"
    return _AWARENESS.get(value.value, f"不明({value.value})")


def _window_dpi(hwnd: int) -> int:
    """ウィンドウが属するモニタのDPIを返す（96 = 100%）。"""
    try:
        _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        return int(_user32.GetDpiForWindow(hwnd))
    except (OSError, AttributeError):
        return 0


def _target_keyword() -> str:
    """config.json からキャプチャ対象のウィンドウタイトルキーワードを読む。"""
    for candidate in (_ROOT / "config.json", _ROOT / "dist" / "config.json"):
        if candidate.exists():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            target = data.get("screen_capture", {}).get("target", {})
            keyword = target.get("window_title_keyword")
            if keyword:
                return keyword
    return "Legacy Kindle for PC"


def _shoot(hwnd: int, out_path: Path, label: str):
    """1枚キャプチャして保存し、解析結果を返す。失敗時はNone。"""
    image = capture_hwnd(hwnd)
    if image is None:
        print(f"  [{label}] キャプチャに失敗しました")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"  [{label}] {image.size[0]}x{image.size[1]} → {out_path}")
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="キャプチャ解像度を実測する")
    parser.add_argument("--maximize", action="store_true",
                        help="最大化前後を撮り比べる")
    parser.add_argument("--out", default=str(_ROOT / "tools" / "_probe"),
                        help="キャプチャ画像の保存先")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    keyword = _target_keyword()

    print("=== 環境 ===")
    print(f"DPI Awareness : {_dpi_awareness()}")
    print(f"プライマリ画面 : {_user32.GetSystemMetrics(_SM_CXSCREEN)}"
          f"x{_user32.GetSystemMetrics(_SM_CYSCREEN)}")
    print(f"対象キーワード : {keyword}")

    result = resolve_target(keyword, None, require_visible=True, allow_minimized=False)
    if result.window is None:
        print(f"\n対象ウィンドウが見つかりません（理由: {result.skip_reason}）")
        print("Legacy Kindle for PC で書籍を開いた状態で再実行してください。")
        return 1

    win = result.window
    dpi = _window_dpi(win.hwnd)
    scale = f"{dpi / 96:.2%}" if dpi else "不明"
    language = detect_language(win.title)

    print("\n=== 対象ウィンドウ ===")
    print(f"タイトル   : {win.title[:70]}")
    print(f"ウィンドウ : {win.width}x{win.height} (left={win.left}, top={win.top})")
    print(f"モニタDPI  : {dpi}（スケーリング {scale}）")
    print(f"言語判定   : {language}")

    print("\n=== キャプチャ ===")
    shots = []
    before = _shoot(win.hwnd, out_dir / "before.png", "現状")
    if before:
        shots.append(("現状", before))

    if args.maximize:
        import pygetwindow as gw
        for window in gw.getAllWindows():
            if window._hWnd == win.hwnd:
                window.maximize()
                break
        # 最大化後のレイアウト確定を待つ
        import time
        time.sleep(1.5)
        after = _shoot(win.hwnd, out_dir / "maximized.png", "最大化")
        if after:
            shots.append(("最大化", after))

    print("\n=== 解析 ===")
    summary = []
    for label, path in shots:
        r = analyze_image(path, language)
        summary.append((label, r))
        print(f"[{label}] 全体 {r['size'][0]}x{r['size'][1]} / "
              f"本文 {r['content'][0]}x{r['content'][1]} / {r['direction']} / "
              f"{r['lines']}行 送り{r['pitch']}px / 推定文字 {r['glyph_px']}px → {r['verdict']}")

    if len(summary) == 2:
        base, best = summary[0][1]["glyph_px"], summary[1][1]["glyph_px"]
        if base:
            print(f"\n最大化による文字サイズ改善: {base}px → {best}px "
                  f"（{best / base:.2f}倍）")

    if summary:
        print(f"\n推奨設定: {recommend(language, summary[-1][1]['direction'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
