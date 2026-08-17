"""PaddleOCR adapter and engine dispatch tests."""

from pathlib import Path

import pytest
from PIL import Image

import ocr.engine_factory as factory
from ocr.config import PaddleOcrConfig
from ocr.engines.paddleocr import PADDLEOCR_CANDIDATE_ID, PaddleOcrEngine
from ocr.errors import EngineUnavailableError
from ocr.models import EngineRequest


REPO_ROOT = Path(__file__).resolve().parents[1]


def config() -> PaddleOcrConfig:
    parameters = {
        "ja_vertical": {
            "language": "jpn",
            "device": "cpu",
            "text_detection_model_name": "PP-OCRv5_server_det",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        },
        "ja_horizontal": {
            "language": "jpn",
            "device": "cpu",
            "text_detection_model_name": "PP-OCRv5_server_det",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        },
        "en_horizontal": {
            "language": "eng",
            "device": "cpu",
            "text_detection_model_name": "PP-OCRv5_server_det",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        },
    }
    return PaddleOcrConfig(
        engine_version="3.7.0",
        traineddata={"jpn": {"sha256": "a" * 64}, "eng": {"sha256": "a" * 64}},
        candidate_parameters=parameters,
        preprocess_version="1",
        classifier_version="1",
        pipeline_version="1",
        profile_path="PADDLEOCR_CANDIDATE_PROFILE.json",
        candidate_id="PADDLE-PPOCRV5-CPU-001",
        device="cpu",
        text_detection_model_name="PP-OCRv5_server_det",
        text_recognition_model_name="PP-OCRv5_server_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        paddlex_cache_home="/tmp/paddlex",
    )


def test_paddleocr_candidate_id_constant():
    """Verify constant candidate ID is correct."""
    assert PADDLEOCR_CANDIDATE_ID == "PADDLE-PPOCRV5-CPU-001"


def test_engine_factory_recognizes_paddleocr_candidate_id():
    """Factory should dispatch PaddleOCR candidate ID correctly."""
    cfg, engine = factory.create_candidate(
        PADDLEOCR_CANDIDATE_ID,
        manifest_path=REPO_ROOT / "PADDLEOCR_CANDIDATE_PROFILE.json",
    )
    assert isinstance(engine, PaddleOcrEngine)
    assert cfg.candidate_id == "PADDLE-PPOCRV5-CPU-001"
    assert cfg.engine_version == "3.7.0"
    assert cfg.device == "cpu"


def test_paddleocr_config_is_frozen():
    """PaddleOcrConfig should be immutable."""
    cfg = config()
    with pytest.raises(AttributeError):
        cfg.device = "gpu"  # Should raise because frozen=True


def test_paddleocr_config_fields_match_profile():
    """Config fields should match loaded profile."""
    cfg, _ = factory.create_candidate(
        PADDLEOCR_CANDIDATE_ID,
        manifest_path=REPO_ROOT / "PADDLEOCR_CANDIDATE_PROFILE.json",
    )
    assert cfg.candidate_id == "PADDLE-PPOCRV5-CPU-001"
    assert cfg.engine_version == "3.7.0"
    assert cfg.device == "cpu"
    assert cfg.text_detection_model_name == "PP-OCRv5_server_det"
    assert cfg.text_recognition_model_name == "PP-OCRv5_server_rec"
    assert cfg.use_doc_orientation_classify is False
    assert cfg.use_doc_unwarping is False
    assert cfg.use_textline_orientation is False


def test_paddleocr_engine_instantiation():
    """Engine should instantiate with config."""
    cfg = config()
    engine = PaddleOcrEngine(cfg)
    assert engine.config.candidate_id == "PADDLE-PPOCRV5-CPU-001"
    assert engine.config.engine_version == "3.7.0"


def test_paddleocr_engine_missing_paddleocr_raises():
    """Engine should raise if paddleocr is not available."""
    cfg = config()
    engine = PaddleOcrEngine(cfg)
    img = Image.new("RGB", (100, 100), color="white")
    request = EngineRequest("jpn", 0)

    with pytest.raises(EngineUnavailableError, match="PaddleOCR candidate environment"):
        engine.recognize(img, request)
