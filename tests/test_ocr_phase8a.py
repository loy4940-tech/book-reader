"""Phase 8A: synthetic fixtureだけを使うページ単位core OCR test。"""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr.classifier import LANGUAGES, ORIENTATIONS, classify_page, detect_language
from ocr.config import ENGINE_STATE, OcrConfig, load_ocr_config
from ocr.engines.base import OcrEngine
from ocr.engines.tesseract import TesseractEngine
from ocr.errors import EngineProcessError, InputImageError
from ocr.figures import FigurePersistenceOptions
from ocr.models import EngineRequest, EngineResult, FigureCandidate
from ocr.page_ocr import PageOcrProcessor
from ocr.preprocess import preprocess_page


def _fixture(path: Path) -> Path:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for y in range(120, 420, 60):
        draw.rectangle((120, y, 680, y + 22), fill="black")
    image.save(path)
    return path


def _config(executable: str = "fake") -> OcrConfig:
    return OcrConfig(
        executable=executable,
        engine_version="fake 1",
        traineddata={"jpn": {"sha256": "a" * 64}, "eng": {"sha256": "b" * 64}},
        candidate_parameters={
            "ja_vertical": {"lang": "jpn_vert", "psm": 5},
            "ja_horizontal": {"lang": "jpn", "psm": 6},
            "en_horizontal": {"lang": "eng", "psm": 6},
        },
        preprocess_version="1", classifier_version="1", pipeline_version="1",
    )


class FakeEngine(OcrEngine):
    def recognize(self, image, request: EngineRequest) -> EngineResult:
        assert image.size[0] > 0 and image.size[1] > 0
        return EngineResult("synthetic text", "fake", "fake 1", 0.01)


class FailingEngine(OcrEngine):
    def recognize(self, image, request: EngineRequest) -> EngineResult:
        raise EngineProcessError("synthetic failure")


class FigureEngine(OcrEngine):
    def recognize(self, image, request: EngineRequest) -> EngineResult:
        return EngineResult(
            "canonical text unchanged", "yomitoku", "0.13.1", 0.01,
            (FigureCandidate(1, (0, 0, image.width, image.height)),),
        )


def test_page_api_returns_one_structured_record(tmp_path):
    source = _fixture(tmp_path / "page.png")
    record = PageOcrProcessor(_config(), FakeEngine()).process(
        source, page_id="p001", language_override="eng", orientation_override="horizontal"
    )
    assert record.status == "success"
    assert record.source_page == "p001"
    assert record.text == "synthetic text"
    assert len(record.source_sha256) == 64


def test_classifier_returns_canonical_values(tmp_path):
    source = _fixture(tmp_path / "page.png")
    processed = preprocess_page(source)
    result = classify_page(processed.image, "English Book")
    assert result.language in LANGUAGES
    assert result.orientation in ORIENTATIONS
    assert detect_language("日本語の本") == "jpn"


def test_preprocess_produces_engine_ready_image(tmp_path):
    source = _fixture(tmp_path / "page.png")
    result = preprocess_page(source)
    assert result.image.mode == "1"
    assert result.output_size == result.image.size
    assert source.exists()


def test_page_processor_uses_engine_abstraction(tmp_path):
    source = _fixture(tmp_path / "page.png")
    record = PageOcrProcessor(_config(), FakeEngine()).process(
        source, language_override="jpn", orientation_override="horizontal"
    )
    assert record.engine == "fake"


def test_figure_feature_flag_preserves_canonical_text(tmp_path):
    source = _fixture(tmp_path / "page.png")
    disabled = PageOcrProcessor(_config(), FigureEngine()).process(
        source, page_id="PAGE-001", language_override="jpn", orientation_override="horizontal",
    )
    asset_root = tmp_path / "assets"
    enabled = PageOcrProcessor(
        _config(), FigureEngine(),
        figure_options=FigurePersistenceOptions(
            enabled=True, storage_root=asset_root,
            candidate_id="yomitoku-0.13.1-cpu-lite-fixed-v1",
        ),
    ).process(
        source, page_id="PAGE-001", language_override="jpn", orientation_override="horizontal",
    )
    assert disabled.text.encode("utf-8") == enabled.text.encode("utf-8")
    assert not (tmp_path / "figures").exists()
    assert (asset_root / "figures" / "PAGE-001" / "figures.manifest.json").is_file()


def test_missing_input_is_explicit_failure(tmp_path):
    with pytest.raises(InputImageError) as error:
        PageOcrProcessor(_config(), FakeEngine()).process(
            tmp_path / "missing.png", language_override="eng"
        )
    assert error.value.stage == "input"


def test_engine_failure_is_not_success(tmp_path):
    source = _fixture(tmp_path / "page.png")
    with pytest.raises(EngineProcessError):
        PageOcrProcessor(_config(), FailingEngine()).process(
            source, language_override="eng", orientation_override="horizontal"
        )


def test_image_is_preserved_after_success_and_failure(tmp_path):
    source = _fixture(tmp_path / "page.png")
    PageOcrProcessor(_config(), FakeEngine()).process(
        source, language_override="eng", orientation_override="horizontal"
    )
    assert source.exists()
    with pytest.raises(EngineProcessError):
        PageOcrProcessor(_config(), FailingEngine()).process(
            source, language_override="eng", orientation_override="horizontal"
        )
    assert source.exists()


def test_record_contract_and_temporary_state(tmp_path):
    source = _fixture(tmp_path / "page.png")
    record = PageOcrProcessor(_config(), FakeEngine()).process(
        source, language_override="jpn", orientation_override="horizontal"
    )
    data = record.to_dict()
    required = {
        "source_page", "source_sha256", "status", "text", "classifier", "engine",
        "engine_version", "engine_state", "parameters", "model_sha256",
        "preprocess_version", "classifier_version", "pipeline_version", "processed_at",
        "elapsed_seconds",
    }
    assert required <= data.keys()
    assert data["engine_state"] == ENGINE_STATE
    assert data["engine_state"].lower() not in {"provisional", "validated", "qualified"}


def test_corrupt_image_is_explicit_input_failure(tmp_path):
    source = tmp_path / "broken.png"
    source.write_bytes(b"not an image")
    with pytest.raises(InputImageError) as error:
        PageOcrProcessor(_config(), FakeEngine()).process(
            source, language_override="eng", orientation_override="horizontal"
        )
    assert error.value.stage == "input"
    assert source.exists()


def test_real_tesseract_invocation_on_synthetic_image(tmp_path):
    source = _fixture(tmp_path / "page.png")
    config = load_ocr_config()
    processed = preprocess_page(source)
    result = TesseractEngine(config).recognize(processed.image, EngineRequest("eng", 6, 3))
    assert isinstance(result.text, str)
    assert result.engine == "tesseract"
    assert source.exists()
