"""方式A：PostMessageで対象ウィンドウのハンドルに直接キーを送る。
対象ウィンドウをアクティブ（前面）にせずにページめくりできる。
"""
import ctypes

from keys import EXTENDED_KEYS, VK_MAP

user32 = ctypes.windll.user32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MAPVK_VK_TO_VSC = 0


def _build_lparam(scan_code: int, *, key_up: bool, extended: bool) -> int:
    """WM_KEYDOWN/WM_KEYUP用のlParamを組み立てる。"""
    lparam = 1  # repeat count
    lparam |= (scan_code & 0xFF) << 16
    if extended:
        lparam |= 1 << 24  # 拡張キー
    if key_up:
        lparam |= 1 << 30  # previous key state
        lparam |= 1 << 31  # transition state
    return lparam


def send_key_to_hwnd(hwnd: int, key_name: str) -> None:
    """指定ウィンドウハンドルにキー押下→離上を送信する。"""
    name = key_name.lower()
    if name not in VK_MAP:
        raise ValueError(f"未対応のキーです: {key_name}")
    vk = VK_MAP[name]
    scan_code = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    extended = name in EXTENDED_KEYS
    down = _build_lparam(scan_code, key_up=False, extended=extended)
    up = _build_lparam(scan_code, key_up=True, extended=extended)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, down)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, up)
