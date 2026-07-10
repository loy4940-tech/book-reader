"""対象ウィンドウの探索・アクティブ状態確認ユーティリティ。"""
import pygetwindow as gw


def is_target_window_active(target_title_substring: str) -> bool:
    """現在アクティブなウィンドウのタイトルに、指定した部分文字列が含まれるか確認する。"""
    active_window = gw.getActiveWindow()
    if active_window is None or not active_window.title:
        return False
    return target_title_substring in active_window.title


def find_target_window(target_title_substring: str):
    """タイトルに部分一致するウィンドウを探す。見つからなければNoneを返す。"""
    for window in gw.getAllWindows():
        if target_title_substring in window.title:
            return window
    return None
