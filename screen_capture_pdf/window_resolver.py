"""対象ウィンドウの特定。window_title_keyword（主）＋ process_name（任意）の
二段階で対象を絞り、表示状態・最小化状態を判定する。
"""
import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

import pygetwindow as gw

# 共有 windll を汚染しないよう独立インスタンスを使う
_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# capture_once から参照するスキップ理由
SKIP_NOT_FOUND = "not_found"
SKIP_MINIMIZED = "minimized"
SKIP_NOT_VISIBLE = "not_visible"


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int


@dataclass
class ResolveResult:
    window: Optional[WindowInfo]
    skip_reason: Optional[str]  # 成功時はNone


def get_process_name(hwnd: int) -> Optional[str]:
    """ウィンドウを所有するプロセスの実行ファイル名を返す。取得失敗時はNone。"""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return None
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value)
    finally:
        _kernel32.CloseHandle(handle)


def resolve_target(
    title_keyword: str,
    process_name: Optional[str] = None,
    *,
    require_visible: bool = True,
    allow_minimized: bool = False,
) -> ResolveResult:
    """対象ウィンドウを特定する。見つからない/最小化/非表示ならスキップ理由を返す。"""
    candidates = [w for w in gw.getAllWindows() if title_keyword in (w.title or "")]

    if process_name is not None:
        want = process_name.lower()
        candidates = [w for w in candidates if (get_process_name(w._hWnd) or "").lower() == want]

    if not candidates:
        return ResolveResult(None, SKIP_NOT_FOUND)

    window = candidates[0]
    hwnd = window._hWnd

    if _user32.IsIconic(hwnd):
        if not allow_minimized:
            return ResolveResult(None, SKIP_MINIMIZED)
    elif require_visible and not _user32.IsWindowVisible(hwnd):
        return ResolveResult(None, SKIP_NOT_VISIBLE)

    info = WindowInfo(
        hwnd=hwnd,
        title=window.title or "",
        left=window.left,
        top=window.top,
        width=window.width,
        height=window.height,
    )
    return ResolveResult(info, None)
