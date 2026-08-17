"""PaddleOCR candidate engine adapter (Gate 1 reopened candidate evaluation)."""

import os
import time
from typing import Any

from PIL import Image

from ..config import PaddleOcrConfig
from ..errors import EngineProcessError, EngineUnavailableError
from ..models import EngineRequest, EngineResult
from .base import OcrEngine


PADDLEOCR_CANDIDATE_ID = "PADDLE-PPOCRV5-CPU-001"


class PaddleOcrEngine(OcrEngine):
    def __init__(self, config: PaddleOcrConfig) -> None:
        self.config = config

    def recognize(self, image: Image.Image, request: EngineRequest) -> EngineResult:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise EngineUnavailableError("PaddleOCR candidate environment が必要です") from exc
        try:
            import numpy as np
        except ImportError as exc:
            raise EngineUnavailableError("PaddleOCR candidate environment に numpy がありません") from exc

        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", self.config.paddlex_cache_home)
        started = time.perf_counter()
        try:
            engine = PaddleOCR(
                device=self.config.device,
                text_detection_model_name=self.config.text_detection_model_name,
                text_recognition_model_name=self.config.text_recognition_model_name,
                use_doc_orientation_classify=self.config.use_doc_orientation_classify,
                use_doc_unwarping=self.config.use_doc_unwarping,
                use_textline_orientation=self.config.use_textline_orientation,
            )
            rgb = np.asarray(image.convert("RGB"))
            native_pages = list(engine.predict(rgb))
            if len(native_pages) != 1:
                raise EngineProcessError(f"PaddleOCR expected one page result, got {len(native_pages)}")

            native_page = native_pages[0]
            texts = [item[1][0] for item in native_page] if native_page else []
            text = "\n".join(t for t in texts if t.strip())
            elapsed = time.perf_counter() - started
        except EngineUnavailableError:
            raise
        except EngineProcessError:
            raise
        except Exception as exc:
            raise EngineProcessError(f"PaddleOCR inference failed: {exc}") from exc

        return EngineResult(
            text=text,
            engine="paddleocr",
            engine_version=self.config.engine_version,
            elapsed_seconds=elapsed,
        )
