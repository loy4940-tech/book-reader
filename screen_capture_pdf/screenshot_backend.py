"""指定ウィンドウ領域のみの撮影バックエンド。

実証済みの PrintWindow 方式（screen_capture.capture_hwnd）を流用する。
これにより、対象ウィンドウが他ウィンドウの裏に隠れていても中身だけを撮影でき、
画面全体や他ウィンドウの映り込みを避けられる。
"""
from screen_capture import capture_hwnd


def capture_window(hwnd: int):
    """指定ウィンドウハンドルの内容をPIL Imageで返す。失敗時はNone。"""
    return capture_hwnd(hwnd)
