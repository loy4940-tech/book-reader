"""方式A（PostMessage）が対象アプリに効くかを検証する最小スクリプト。

使い方:
  1. Kindle for PC で本を開いておく。
  2. Kindleを「アクティブにしない」状態にする（このPowerShellや別ウィンドウを前面に）。
  3. このスクリプトを実行し、Kindleがアクティブでないまま
     ページがめくれるかを目視で確認する。

PostMessage が効けば → 方式Aで本実装に進める。
効かなければ    → 子ウィンドウ探索 or 方式Bへの切り替えを検討する。
"""
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from window_utils import find_target_window  # noqa: E402

user32 = ctypes.windll.user32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_LEFT = 0x25  # 縦書き（右→左）の本では左キーが「次ページ」
MAPVK_VK_TO_VSC = 0

TARGET = "Legacy Kindle for PC"


def build_lparam(scan_code: int, *, key_up: bool, extended: bool) -> int:
    """WM_KEYDOWN/WM_KEYUP用のlParamを組み立てる。"""
    lparam = 1  # repeat count
    lparam |= (scan_code & 0xFF) << 16
    if extended:
        lparam |= 1 << 24  # 拡張キー（矢印キー等）
    if key_up:
        lparam |= 1 << 30  # previous key state
        lparam |= 1 << 31  # transition state
    return lparam


def post_key(hwnd: int, vk: int, *, extended: bool = True) -> None:
    scan_code = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    down = build_lparam(scan_code, key_up=False, extended=extended)
    up = build_lparam(scan_code, key_up=True, extended=extended)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, down)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, up)


def main() -> None:
    window = find_target_window(TARGET)
    if window is None:
        print(f"対象ウィンドウ '{TARGET}' が見つかりません。Kindleで本を開いていますか？")
        return

    hwnd = window._hWnd
    print(f"対象ウィンドウを検出: hwnd={hwnd}, title='{window.title}'")
    print("Kindleをアクティブにせず、5秒後にPostMessageで左キー（次ページ）を3回送ります…")
    print("（Kindleのページがめくれるか目視で確認してください）")

    for remaining in range(5, 0, -1):
        print(f"  {remaining}...", end="", flush=True)
        time.sleep(1)
    print()

    for i in range(1, 4):
        post_key(hwnd, VK_LEFT)
        print(f"  左キー送信 {i}回目")
        time.sleep(2)

    print("完了。ページがめくれましたか？（めくれた=方式A成功）")


if __name__ == "__main__":
    main()
