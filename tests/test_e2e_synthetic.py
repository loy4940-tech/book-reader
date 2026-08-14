"""E2E synthetic tests: capture → worker → batch → output without quality judgment."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from ocr.batch import SessionOcrBatch
from ocr.classifier import classify_page
from ocr.config import ENGINE_STATE, OcrConfig
from ocr.engines.synthetic import SyntheticEngine
from ocr.models import EngineRequest, EngineResult
from ocr.output import generate_json_output, generate_markdown, generate_text_files, verify_outputs
from ocr.page_ocr import PageOcrProcessor
from ocr.preprocess import preprocess_page
from ocr.store import load_store


def make_test_image(path: Path, width: int = 800, height: int = 600) -> Path:
    """Create a simple test image with text-like patterns."""
    image = Image.new("RGB", (width, height), "white")
    image.save(path, format="PNG")
    return path


def make_config() -> OcrConfig:
    """Create minimal OCR config for synthetic engine."""
    return OcrConfig(
        executable="synthetic",
        engine_version="synthetic-1.0",
        traineddata={"jpn": {"sha256": "a" * 64}, "eng": {"sha256": "b" * 64}},
        candidate_parameters={
            "ja_vertical": {"lang": "jpn_vert", "psm": 5},
            "ja_horizontal": {"lang": "jpn", "psm": 6},
            "en_horizontal": {"lang": "eng", "psm": 6},
        },
        preprocess_version="1",
        classifier_version="1",
        pipeline_version="1",
    )


def make_session(tmp_path: Path, page_count: int = 3) -> Path:
    """Create minimal capture session with metadata and images."""
    captures = []
    for page_num in range(1, page_count + 1):
        name = f"page_{page_num:03d}.png"
        image_path = tmp_path / name
        make_test_image(image_path)
        captures.append({
            "capture_index": page_num,
            "status": "success",
            "image_path": name,
        })
    (tmp_path / "metadata.json").write_text(
        json.dumps({"captures": captures}),
        encoding="utf-8"
    )
    return tmp_path


def test_synthetic_engine_is_deterministic(tmp_path):
    """Synthetic engine returns same result for same image."""
    config = make_config()
    engine = SyntheticEngine(config)

    image = Image.new("RGB", (800, 600), color="white")
    request = EngineRequest(language="eng", psm=6)

    result1 = engine.recognize(image, request)
    result2 = engine.recognize(image, request)

    assert result1.text == result2.text
    assert result1.engine == "synthetic"
    assert result1.engine_version == "synthetic-1.0"


def test_synthetic_engine_differentiates_different_images(tmp_path):
    """Synthetic engine returns different results for different images."""
    config = make_config()
    engine = SyntheticEngine(config)

    image1 = Image.new("RGB", (800, 600), color="white")
    image2 = Image.new("RGB", (800, 600), color="gray")
    request = EngineRequest(language="eng", psm=6)

    result1 = engine.recognize(image1, request)
    result2 = engine.recognize(image2, request)

    assert result1.text != result2.text


def test_synthetic_engine_respects_language_request(tmp_path):
    """Synthetic engine includes requested language in output."""
    config = make_config()
    engine = SyntheticEngine(config)

    image = Image.new("RGB", (800, 600), color="white")

    result_jpn = engine.recognize(image, EngineRequest(language="jpn", psm=5))
    result_eng = engine.recognize(image, EngineRequest(language="eng", psm=6))

    assert "jpn" in result_jpn.text
    assert "eng" in result_eng.text


class FakeProcessor:
    """Minimal processor for batch testing."""

    def __init__(self, config: OcrConfig, engine):
        self.config = config
        self.engine = engine

    def process(self, path: Path, *, page_id: str, book_identifier: str = "test"):
        image = Image.open(path)
        request = EngineRequest(language="eng", psm=6)
        result = self.engine.recognize(image, request)

        from ocr.models import ClassificationResult, PageOcrRecord

        return PageOcrRecord(
            source_page=page_id,
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            status="success",
            text=result.text,
            classifier=ClassificationResult("eng", "horizontal", 1.0, "synthetic"),
            engine=result.engine,
            engine_version=result.engine_version,
            engine_state=ENGINE_STATE,
            parameters={"lang": "eng", "psm": 6, "oem": 3},
            model_sha256="b" * 64,
            preprocess_version="1",
            classifier_version="1",
            pipeline_version="1",
            processed_at="2026-08-15T00:00:00+00:00",
            elapsed_seconds=result.elapsed_seconds,
        )


def test_batch_with_synthetic_engine(tmp_path):
    """SessionOcrBatch works with synthetic engine."""
    session = make_session(tmp_path, page_count=2)
    config = make_config()
    engine = SyntheticEngine(config)
    processor = FakeProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    result = batch.run(session)

    assert result.record_count == 2
    assert result.processed_count == 2

    store = load_store(session / "ocr.json")
    assert len(store["records"]) == 2
    assert all(r["engine"] == "synthetic" for r in store["records"])


def test_text_output_generation(tmp_path):
    """Phase 9: generate per-page text files."""
    session = make_session(tmp_path, page_count=3)
    config = make_config()
    engine = SyntheticEngine(config)
    processor = FakeProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    batch.run(session)

    count = generate_text_files(session)

    assert count == 3
    assert (session / "text" / "page_001.txt").is_file()
    assert (session / "text" / "page_002.txt").is_file()
    assert (session / "text" / "page_003.txt").is_file()

    content = (session / "text" / "page_001.txt").read_text(encoding="utf-8")
    assert "[Synthetic OCR]" in content


def test_markdown_output_generation(tmp_path):
    """Phase 9: generate combined markdown with page markers."""
    session = make_session(tmp_path, page_count=2)
    config = make_config()
    engine = SyntheticEngine(config)
    processor = FakeProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    batch.run(session)

    markdown_file = generate_markdown(session)

    assert markdown_file.is_file()
    content = markdown_file.read_text(encoding="utf-8")

    assert "<!-- page: 001" in content
    assert "<!-- page: 002" in content
    assert "| source: page_001.png" in content
    assert "| lang: eng" in content
    assert "[Synthetic OCR]" in content


def test_json_output_verification(tmp_path):
    """Phase 9: verify JSON output exists."""
    session = make_session(tmp_path, page_count=1)
    config = make_config()
    engine = SyntheticEngine(config)
    processor = FakeProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    batch.run(session)

    json_file = generate_json_output(session)
    assert json_file.is_file()

    store = load_store(json_file)
    assert "records" in store
    assert len(store["records"]) == 1


def test_verify_outputs_all_present(tmp_path):
    """Phase 9: verify all outputs are generated."""
    session = make_session(tmp_path, page_count=2)
    config = make_config()
    engine = SyntheticEngine(config)
    processor = FakeProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    batch.run(session)

    generate_text_files(session)
    generate_markdown(session)
    generate_json_output(session)

    result = verify_outputs(session)

    assert result["json_exists"] is True
    assert result["markdown_exists"] is True
    assert result["text_dir_exists"] is True
    assert result["text_files"] == 2


def test_idempotency_completed_session_no_reprocess(tmp_path):
    """Phase 8B: completed sessions not reprocessed on second run."""
    session = make_session(tmp_path, page_count=1)
    config = make_config()
    engine = SyntheticEngine(config)

    class CountingProcessor:
        def __init__(self, config, engine):
            self.config = config
            self.engine = engine
            self.process_count = 0

        def process(self, path: Path, *, page_id: str, book_identifier: str = "test"):
            self.process_count += 1

            from ocr.models import ClassificationResult, PageOcrRecord

            return PageOcrRecord(
                source_page=page_id,
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                status="success",
                text="already processed",
                classifier=ClassificationResult("eng", "horizontal", 1.0, "synthetic"),
                engine="synthetic",
                engine_version="1.0",
                engine_state=ENGINE_STATE,
                parameters={"lang": "eng", "psm": 6},
                model_sha256="b" * 64,
                preprocess_version="1",
                classifier_version="1",
                pipeline_version="1",
                processed_at="2026-08-15T00:00:00+00:00",
                elapsed_seconds=0.01,
            )

    processor = CountingProcessor(config, engine)
    batch = SessionOcrBatch(processor, config)

    result1 = batch.run(session)
    assert processor.process_count == 1

    result2 = batch.run(session)
    assert processor.process_count == 1
    assert result2.skipped_count == 1


def test_resume_after_interruption(tmp_path):
    """Phase 8B: resume continues from last successful page."""
    session = make_session(tmp_path, page_count=3)
    config = make_config()
    engine = SyntheticEngine(config)

    class InterruptingProcessor:
        def __init__(self, config, engine):
            self.config = config
            self.engine = engine
            self.calls = []

        def process(self, path: Path, *, page_id: str, book_identifier: str = "test"):
            self.calls.append(page_id)

            from ocr.models import ClassificationResult, PageOcrRecord

            return PageOcrRecord(
                source_page=page_id,
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                status="success",
                text=f"page: {page_id}",
                classifier=ClassificationResult("eng", "horizontal", 1.0, "synthetic"),
                engine="synthetic",
                engine_version="1.0",
                engine_state=ENGINE_STATE,
                parameters={"lang": "eng", "psm": 6},
                model_sha256="b" * 64,
                preprocess_version="1",
                classifier_version="1",
                pipeline_version="1",
                processed_at="2026-08-15T00:00:00+00:00",
                elapsed_seconds=0.01,
            )

    processor = InterruptingProcessor(config, engine)
    batch = SessionOcrBatch(processor, config)
    result = batch.run(session)

    assert len(processor.calls) == 3
    assert result.processed_count == 3

    processor2 = InterruptingProcessor(config, engine)
    batch2 = SessionOcrBatch(processor2, config)
    result2 = batch2.run(session)

    assert processor2.calls == []
    assert result2.skipped_count == 3
