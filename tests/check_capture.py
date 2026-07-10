"""方式A用のPrintWindowキャプチャが、Kindleを裏に隠したままでも
中身を撮れるか検証する。撮影結果をPNGに保存し、目視確認できるようにする。

使い方:
  1. Kindle for PC で本を開く。
  2. Kindleを他ウィンドウの「裏」に隠す（前面にしない）。
  3. このスクリプトを実行し、保存されたPNGにKindleの本文が写っていれば成功。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from screen_capture import capture_hwnd  # noqa: E402
from window_utils import find_target_window  # noqa: E402

TARGET = "Legacy Kindle for PC"
OUT = Path(__file__).parent.parent / "logs" / "capture_test.png"


def main() -> None:
    window = find_target_window(TARGET)
    if window is None:
        print(f"対象ウィンドウ '{TARGET}' が見つかりません。")
        return

    img = capture_hwnd(window._hWnd)
    if img is None:
        print("キャプチャに失敗しました（最小化中の可能性）。")
        return

    OUT.parent.mkdir(exist_ok=True)
    img.save(OUT)
    print(f"キャプチャ成功: {OUT}")
    print("→ このPNGにKindleの本文が写っていれば、裏に隠れていても検証できます。")


if __name__ == "__main__":
    main()
