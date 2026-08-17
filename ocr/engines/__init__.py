"""OCR engine implementations。"""

from .base import OcrEngine
from .paddleocr import PADDLEOCR_CANDIDATE_ID, PADDLEOCR_MOBILE_CANDIDATE_ID, PaddleOcrEngine
from .synthetic import SYNTHETIC_CANDIDATE_PREFIX, SyntheticEngine
from .tesseract import TesseractEngine
from .yomitoku import YOMITOKU_CANDIDATE_ID, YomiTokuEngine

__all__ = [
    "OcrEngine",
    "PaddleOcrEngine",
    "PADDLEOCR_CANDIDATE_ID",
    "PADDLEOCR_MOBILE_CANDIDATE_ID",
    "SyntheticEngine",
    "SYNTHETIC_CANDIDATE_PREFIX",
    "TesseractEngine",
    "YomiTokuEngine",
    "YOMITOKU_CANDIDATE_ID",
]
