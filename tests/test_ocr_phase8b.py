import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ocr.batch import OcrBatchError, SessionOcrBatch
from ocr.config import ENGINE_STATE, OcrConfig
from ocr.models import ClassificationResult, PageOcrRecord
from ocr.profile import build_ocr_profile, canonical_profile_json, profile_id
from ocr.store import OcrStoreError, atomic_write_store, load_store


def config(**overrides):
    values = dict(
        executable="tesseract",
        engine_version="5.4",
        traineddata={"eng": {"sha256": "a" * 64}, "jpn": {"sha256": "b" * 64}},
        candidate_parameters={
            "en_horizontal": {"lang": "eng", "psm": 6},
            "ja_horizontal": {"lang": "jpn", "psm": 6},
            "ja_vertical": {"lang": "jpn_vert", "psm": 5},
        },
        preprocess_version="1",
        classifier_version="1",
        pipeline_version="1",
    )
    values.update(overrides)
    return OcrConfig(**values)


class FakeProcessor:
    def __init__(self, cfg, *, empty=False):
        self.config = cfg
        self.calls = []
        self.empty = empty

    def process(self, path, *, page_id, book_identifier):
        path = Path(path)
        self.calls.append(page_id)
        return PageOcrRecord(
            source_page=page_id,
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            status="success",
            text="" if self.empty else f"text:{page_id}",
            classifier=ClassificationResult("eng", "horizontal", 1.0, "synthetic"),
            engine="tesseract",
            engine_version=self.config.engine_version,
            engine_state=ENGINE_STATE,
            parameters={"lang": "eng", "psm": 6, "oem": 3},
            model_sha256="a" * 64,
            preprocess_version="1",
            classifier_version="1",
            pipeline_version="1",
            processed_at="2026-01-01T00:00:00+00:00",
            elapsed_seconds=0.01,
        )


def session(tmp_path, contents=(b"one", b"two"), statuses=None):
    captures = []
    statuses = statuses or ["success"] * len(contents)
    for index, (content, status) in enumerate(zip(contents, statuses), 1):
        name = f"page_{index:03d}.png"
        (tmp_path / name).write_bytes(content)
        captures.append({"capture_index": index, "status": status, "image_path": name})
    (tmp_path / "metadata.json").write_text(json.dumps({"captures": captures}), encoding="utf-8")
    return tmp_path


def test_profile_is_deterministic_order_independent_and_portable():
    first = build_ocr_profile(config())
    reversed_candidates = dict(reversed(list(config().candidate_parameters.items())))
    second = build_ocr_profile(config(candidate_parameters=reversed_candidates))
    assert profile_id(first) == profile_id(second)
    assert len(profile_id(first)) == 64
    assert "tesseract" in canonical_profile_json(first)
    assert all(term not in first for term in ("processed_at", "elapsed_seconds", "absolute_path"))


def test_semantic_profile_change_changes_id():
    first = build_ocr_profile(config())
    changed = build_ocr_profile(config(pipeline_version="2"))
    assert profile_id(first) != profile_id(changed)


def test_batch_filters_success_preserves_order_and_cardinality(tmp_path):
    root = session(tmp_path, (b"one", b"ignored", b"three"), ("success", "failed", "success"))
    processor = FakeProcessor(config())
    result = SessionOcrBatch(processor, config()).run(root)
    store = load_store(root / "ocr.json")
    assert result.metadata_success_count == result.record_count == 2
    assert processor.calls == ["page_001.png", "page_003.png"]
    assert [r["source_page"] for r in store["records"]] == processor.calls


def test_resume_skips_fresh_and_reprocesses_source_stale(tmp_path):
    root = session(tmp_path)
    first = FakeProcessor(config())
    SessionOcrBatch(first, config()).run(root)
    second = FakeProcessor(config())
    result = SessionOcrBatch(second, config()).run(root)
    assert result.skipped_count == 2 and second.calls == []
    (root / "page_002.png").write_bytes(b"changed")
    third = FakeProcessor(config())
    result = SessionOcrBatch(third, config()).run(root)
    assert result.processed_count == 1 and third.calls == ["page_002.png"]


def test_profile_stale_reprocesses_all(tmp_path):
    root = session(tmp_path)
    SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    changed = config(pipeline_version="2")
    processor = FakeProcessor(changed)
    result = SessionOcrBatch(processor, changed).run(root)
    assert result.processed_count == 2


def test_prior_failure_is_retried(tmp_path):
    root = session(tmp_path, (b"one",))
    SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    store_path = root / "ocr.json"
    store = load_store(store_path)
    store["records"][0]["status"] = "failed"
    atomic_write_store(store_path, store)
    processor = FakeProcessor(config())
    result = SessionOcrBatch(processor, config()).run(root)
    assert result.retry_count == 1 and processor.calls == ["page_001.png"]


def test_exact_duplicate_directly_references_first_and_preserves_files(tmp_path):
    root = session(tmp_path, (b"same", b"same", b"same"))
    processor = FakeProcessor(config())
    result = SessionOcrBatch(processor, config()).run(root)
    records = load_store(root / "ocr.json")["records"]
    assert result.duplicate_count == 2
    assert [r["status"] for r in records] == ["success", "duplicate", "duplicate"]
    assert records[1]["duplicate_of"] == records[2]["duplicate_of"] == "page_001.png"
    assert all((root / f"page_{i:03d}.png").exists() for i in range(1, 4))


def test_different_bytes_are_not_duplicate(tmp_path):
    root = session(tmp_path, (b"similar-a", b"similar-b"))
    SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    assert all(r["status"] == "success" for r in load_store(root / "ocr.json")["records"])


def test_stale_duplicate_group_is_rebuilt_without_dangling_state(tmp_path):
    root = session(tmp_path, (b"same", b"same"))
    SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    (root / "page_001.png").write_bytes(b"now-different")
    processor = FakeProcessor(config())
    SessionOcrBatch(processor, config()).run(root)
    records = load_store(root / "ocr.json")["records"]
    assert processor.calls == ["page_001.png", "page_002.png"]
    assert [record["status"] for record in records] == ["success", "success"]


def test_empty_ocr_text_is_not_inferred_blank(tmp_path):
    root = session(tmp_path, (b"white-ish",))
    SessionOcrBatch(FakeProcessor(config(), empty=True), config()).run(root)
    record = load_store(root / "ocr.json")["records"][0]
    assert record["status"] == "success" and record["text"] == ""


def test_missing_source_stops_before_store_write(tmp_path):
    root = session(tmp_path, (b"one",))
    (root / "page_001.png").unlink()
    with pytest.raises(OcrBatchError):
        SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    assert not (root / "ocr.json").exists()


def test_corrupt_store_is_not_overwritten(tmp_path):
    root = session(tmp_path, (b"one",))
    corrupt = "{not-json"
    (root / "ocr.json").write_text(corrupt, encoding="utf-8")
    with pytest.raises(OcrStoreError):
        SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    assert (root / "ocr.json").read_text(encoding="utf-8") == corrupt


def test_atomic_replace_failure_preserves_existing(tmp_path, monkeypatch):
    root = session(tmp_path, (b"one",))
    batch = SessionOcrBatch(FakeProcessor(config()), config())
    batch.run(root)
    original = (root / "ocr.json").read_bytes()
    import ocr.store as store_module
    monkeypatch.setattr(store_module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        batch.run(root)
    assert (root / "ocr.json").read_bytes() == original


def test_invalid_record_structure_is_rejected(tmp_path):
    root = session(tmp_path, (b"one",))
    SessionOcrBatch(FakeProcessor(config()), config()).run(root)
    path = root / "ocr.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    del value["records"][0]["source_sha256"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(OcrStoreError):
        SessionOcrBatch(FakeProcessor(config()), config()).run(root)
