"""Explicit candidate-to-engine dispatch shared by page and Gate 1 workers."""

from pathlib import Path

from .config import load_ocr_config, load_paddleocr_config, load_paddleocr_mobile_config, load_yomitoku_config
from .engines import (
    PADDLEOCR_CANDIDATE_ID,
    PADDLEOCR_MOBILE_CANDIDATE_ID,
    SYNTHETIC_CANDIDATE_PREFIX,
    PaddleOcrEngine,
    SyntheticEngine,
    TesseractEngine,
    YOMITOKU_CANDIDATE_ID,
    YomiTokuEngine,
)
from .errors import EngineUnavailableError


TESSERACT_CANDIDATE_PREFIX = "tesseract-"


def create_candidate(candidate_id: str, *, manifest_path: Path | str | None = None):
    manifest = Path(manifest_path) if isinstance(manifest_path, str) else manifest_path
    if candidate_id.startswith(SYNTHETIC_CANDIDATE_PREFIX):
        config = load_ocr_config(manifest)
        return config, SyntheticEngine(config)
    if candidate_id.startswith(TESSERACT_CANDIDATE_PREFIX):
        config = load_ocr_config(manifest)
        return config, TesseractEngine(config)
    if candidate_id == YOMITOKU_CANDIDATE_ID:
        config = load_yomitoku_config(manifest)
        return config, YomiTokuEngine(config)
    if candidate_id == PADDLEOCR_CANDIDATE_ID:
        config = load_paddleocr_config(manifest)
        return config, PaddleOcrEngine(config)
    if candidate_id == PADDLEOCR_MOBILE_CANDIDATE_ID:
        config = load_paddleocr_mobile_config(manifest)
        return config, PaddleOcrEngine(config)
    raise EngineUnavailableError(f"unknown OCR candidate: {candidate_id}")
