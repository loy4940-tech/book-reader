"""Deterministic synthetic OCR engine for E2E testing without quality judgment."""

import hashlib
import time
from pathlib import Path

from PIL import Image

from ..config import OcrConfig
from ..models import EngineRequest, EngineResult
from .base import OcrEngine


SYNTHETIC_CANDIDATE_PREFIX = "synthetic-"


class SyntheticEngine(OcrEngine):
    """Deterministic E2E engine that returns stable text based on image content hash.

    Purpose: Enable OCR quality-independent E2E verification without real OCR engines.
    Determinism: Same input image always produces same text.
    Dependencies: None (except PIL, which is already required).
    """

    def __init__(self, config: OcrConfig) -> None:
        self.config = config

    def recognize(self, image: Image.Image, request: EngineRequest) -> EngineResult:
        """Return deterministic text derived from image content."""
        image_bytes = image.tobytes()
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

        started = time.perf_counter()
        text = f"[Synthetic OCR]\nImage: {content_hash}\nLanguage: {request.language}\n"
        elapsed = time.perf_counter() - started

        return EngineResult(
            text=text,
            engine="synthetic",
            engine_version=self.config.engine_version,
            elapsed_seconds=elapsed,
        )
