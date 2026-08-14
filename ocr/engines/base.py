"""最小OCR engine abstraction。"""

from abc import ABC, abstractmethod

from PIL import Image

from ..models import EngineRequest, EngineResult


class OcrEngine(ABC):
    @abstractmethod
    def recognize(self, image: Image.Image, request: EngineRequest) -> EngineResult:
        """前処理済み1ページをOCRする。"""
