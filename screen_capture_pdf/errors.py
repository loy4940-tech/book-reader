"""screen_capture_pdf モジュールの例外定義。"""


class ScreenCaptureError(Exception):
    """本モジュール共通の基底例外。"""


class WindowNotFoundError(ScreenCaptureError):
    """対象ウィンドウが見つからない。"""


class PdfBuildError(ScreenCaptureError):
    """PDF生成に失敗した。"""
