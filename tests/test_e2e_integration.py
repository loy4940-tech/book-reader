"""End-to-end integration: capture session → worker → batch → output generation."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from ocr.config import OcrConfig
from ocr.engines.synthetic import SYNTHETIC_CANDIDATE_PREFIX, SyntheticEngine
from ocr.ingestion import IngestionWorker, IngestionState
from ocr.batch import SessionOcrBatch
from ocr.page_ocr import PageOcrProcessor


def make_synthetic_config() -> OcrConfig:
    """Create OCR config for synthetic engine."""
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


def test_e2e_capture_to_output_generation(tmp_path):
    """Full E2E: synthetic capture session through output generation.

    Flow:
    1. Create capture session with synthetic images
    2. Run ingestion worker with synthetic engine
    3. Verify OCR batch completes
    4. Verify output files generated (text, markdown, JSON)
    5. Verify completed session won't reprocess
    """
    capture_root = tmp_path / "capture"
    capture_root.mkdir()

    session_name = "session-001"
    session_dir = capture_root / session_name
    images_dir = session_dir / "images"
    images_dir.mkdir(parents=True)

    page_count = 3
    captures = []
    for page_num in range(1, page_count + 1):
        image_name = f"capture_{page_num:03d}.png"
        image_path = images_dir / image_name
        image = Image.new("RGB", (800, 600), color="white")
        image.save(image_path)

        captures.append({
            "index": page_num,
            "captured_at": "2026-08-15T00:00:00+00:00",
            "status": "success",
            "image_path": str(image_path),
            "window_title": "Synthetic Book",
        })

    session_id = f"sid-{session_name}"
    (session_dir / "metadata.json").write_text(
        json.dumps({
            "session_id": session_id,
            "started_at": "2026-08-15T00:00:00+00:00",
            "finished_at": "2026-08-15T00:01:00+00:00",
            "captures": captures,
        }),
        encoding="utf-8"
    )

    (session_dir / ".capture_complete.json").write_text(
        json.dumps({
            "schema_version": 1,
            "session_id": session_id,
            "completed_at": "2026-08-15T00:01:00+00:00",
        }),
        encoding="utf-8"
    )

    config = make_synthetic_config()
    engine = SyntheticEngine(config)
    processor = PageOcrProcessor(config, engine)

    batch = SessionOcrBatch(processor, config)
    worker = IngestionWorker(capture_root, batch, worker_id="e2e-test")

    outcomes = worker.scan_once()

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.state == IngestionState.COMPLETED.value
    assert outcome.session_id == session_id

    assert (session_dir / "ocr.json").is_file()
    assert (session_dir / "text").is_dir()
    assert (session_dir / "book.md").is_file()

    assert (session_dir / "text" / "page_001.txt").is_file()
    assert (session_dir / "text" / "page_002.txt").is_file()
    assert (session_dir / "text" / "page_003.txt").is_file()

    markdown = (session_dir / "book.md").read_text(encoding="utf-8")
    assert "<!-- page: 001" in markdown
    assert "<!-- page: 002" in markdown
    assert "<!-- page: 003" in markdown
    assert "[Synthetic OCR]" in markdown

    ocr_json = json.loads((session_dir / "ocr.json").read_text(encoding="utf-8"))
    assert len(ocr_json["records"]) == 3
    assert all(r["engine"] == "synthetic" for r in ocr_json["records"])


def test_e2e_idempotency_no_duplicate_outputs(tmp_path):
    """Completed session run twice produces identical outputs."""
    capture_root = tmp_path / "capture"
    capture_root.mkdir()

    session_dir = capture_root / "session-idempotent"
    images_dir = session_dir / "images"
    images_dir.mkdir(parents=True)

    image_path = images_dir / "capture_001.png"
    Image.new("RGB", (800, 600), color="white").save(image_path)

    session_id = "sid-idempotent"
    (session_dir / "metadata.json").write_text(
        json.dumps({
            "session_id": session_id,
            "started_at": "2026-08-15T00:00:00+00:00",
            "finished_at": "2026-08-15T00:01:00+00:00",
            "captures": [{
                "index": 1,
                "captured_at": "2026-08-15T00:00:00+00:00",
                "status": "success",
                "image_path": str(image_path),
                "window_title": "Book",
            }],
        }),
        encoding="utf-8"
    )

    (session_dir / ".capture_complete.json").write_text(
        json.dumps({
            "schema_version": 1,
            "session_id": session_id,
            "completed_at": "2026-08-15T00:01:00+00:00",
        }),
        encoding="utf-8"
    )

    config = make_synthetic_config()

    outcomes_run1 = IngestionWorker(
        capture_root, SessionOcrBatch(PageOcrProcessor(config, SyntheticEngine(config)), config),
        worker_id="run1"
    ).scan_once()

    markdown_1 = (session_dir / "book.md").read_text(encoding="utf-8")
    json_1 = json.loads((session_dir / "ocr.json").read_text(encoding="utf-8"))

    outcomes_run2 = IngestionWorker(
        capture_root, SessionOcrBatch(PageOcrProcessor(config, SyntheticEngine(config)), config),
        worker_id="run2"
    ).scan_once()

    markdown_2 = (session_dir / "book.md").read_text(encoding="utf-8")
    json_2 = json.loads((session_dir / "ocr.json").read_text(encoding="utf-8"))

    assert len(outcomes_run1) == 1
    assert len(outcomes_run2) == 1
    assert outcomes_run1[0].state == IngestionState.COMPLETED.value
    assert outcomes_run2[0].state == IngestionState.COMPLETED.value

    assert markdown_1 == markdown_2
    assert json_1 == json_2


def test_e2e_deterministic_output_for_same_image(tmp_path):
    """Same image always produces same synthetic OCR text."""
    capture_root = tmp_path / "capture"
    capture_root.mkdir()

    image_bytes = b"PNG_FAKE_DATA_FOR_DETERMINISM"

    for run_num in range(1, 3):
        session_dir = capture_root / f"session-{run_num:03d}"
        images_dir = session_dir / "images"
        images_dir.mkdir(parents=True)

        image_path = images_dir / "capture_001.png"
        image = Image.new("RGB", (800, 600), color="white")
        image.save(image_path)

        session_id = f"sid-det-{run_num}"
        (session_dir / "metadata.json").write_text(
            json.dumps({
                "session_id": session_id,
                "started_at": "2026-08-15T00:00:00+00:00",
                "finished_at": "2026-08-15T00:01:00+00:00",
                "captures": [{
                    "index": 1,
                    "captured_at": "2026-08-15T00:00:00+00:00",
                    "status": "success",
                    "image_path": str(image_path),
                    "window_title": "Book",
                }],
            }),
            encoding="utf-8"
        )

        (session_dir / ".capture_complete.json").write_text(
            json.dumps({
                "schema_version": 1,
                "session_id": session_id,
                "completed_at": "2026-08-15T00:01:00+00:00",
            }),
            encoding="utf-8"
        )

        config = make_synthetic_config()
        IngestionWorker(
            capture_root,
            SessionOcrBatch(PageOcrProcessor(config, SyntheticEngine(config)), config),
            worker_id=f"worker-{run_num}"
        ).scan_once()

    text_1 = json.loads((capture_root / "session-001" / "ocr.json").read_text(encoding="utf-8"))
    text_2 = json.loads((capture_root / "session-002" / "ocr.json").read_text(encoding="utf-8"))

    assert text_1["records"][0]["text"] == text_2["records"][0]["text"]
