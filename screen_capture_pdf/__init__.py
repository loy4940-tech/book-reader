"""指定業務アプリ（本プロジェクトではKindle）のウィンドウをバックグラウンドで
撮影し、撮影終了後にPDF化するモジュール。
"""
from .capture_service import CaptureService
from .interval_adapter import IntervalAdapter

__all__ = ["CaptureService", "IntervalAdapter"]
