"""Explicit candidate-to-engine dispatch shared by page and Gate 1 workers."""

from pathlib import Path

from .config import load_ocr_config, load_yomitoku_config
from .engines import (
    SYNTHETIC_CANDIDATE_PREFIX,
    SyntheticEngine,
    TesseractEngine,
    YOMITOKU_CANDIDATE_ID,
    YomiTokuEngine,
)
from .errors import EngineUnavailableError


TESSERACT_CANDIDATE_PREFIX = "tesseract-"


def create_candidate(candidate_id: str, *, manifest_path: Path | None = None):
    if candidate_id.startswith(SYNTHETIC_CANDIDATE_PREFIX):
        config = load_ocr_config(manifest_path)
        return config, SyntheticEngine(config)
    if candidate_id.startswith(TESSERACT_CANDIDATE_PREFIX):
        config = load_ocr_config(manifest_path)
        return config, TesseractEngine(config)
    if candidate_id == YOMITOKU_CANDIDATE_ID:
        config = load_yomitoku_config(manifest_path)
        return config, YomiTokuEngine(config)
    raise EngineUnavailableError(f"unknown OCR candidate: {candidate_id}")
