"""Session-level OCR batching, freshness, resume, and exact deduplication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config import OcrConfig
from .page_ocr import PageOcrProcessor
from .profile import build_ocr_profile, profile_id
from .store import TERMINAL_STATUSES, OcrStoreError, atomic_write_store, load_store


class OcrBatchError(RuntimeError):
    """Raised when canonical session input cannot be processed safely."""


@dataclass(frozen=True)
class BatchResult:
    metadata_success_count: int
    record_count: int
    processed_count: int
    skipped_count: int
    duplicate_count: int
    blank_count: int
    retry_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_metadata(path: Path) -> list[dict[str, Any]]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OcrBatchError(f"cannot read capture metadata: {path}") from exc
    captures = metadata.get("captures") if isinstance(metadata, dict) else None
    if not isinstance(captures, list):
        raise OcrBatchError("capture metadata must contain a captures list")
    result: list[dict[str, Any]] = []
    for capture in captures:
        if not isinstance(capture, dict):
            raise OcrBatchError("capture metadata entry must be an object")
        if capture.get("status") == "success":
            result.append(capture)
    return result


def _source_path(session_dir: Path, capture: Mapping[str, Any]) -> Path:
    raw = capture.get("image_path")
    if not isinstance(raw, str) or not raw:
        raise OcrBatchError("successful capture has no image_path")
    path = Path(raw)
    if not path.is_absolute():
        path = session_dir / path
    if not path.is_file():
        raise OcrBatchError(f"successful capture source is missing: {path}")
    return path


def _source_page(path: Path) -> str:
    return path.name


def _record_is_fresh(record: Mapping[str, Any], page: str, source_hash: str, current_profile_id: str) -> bool:
    return (
        record.get("source_page") == page
        and record.get("source_sha256") == source_hash
        and record.get("ocr_profile_id") == current_profile_id
        and record.get("status") in TERMINAL_STATUSES
    )


class SessionOcrBatch:
    def __init__(self, processor: PageOcrProcessor, config: OcrConfig) -> None:
        self.processor = processor
        self.profile = build_ocr_profile(config)
        self.profile_id = profile_id(self.profile)

    def run(
        self,
        session_dir: str | Path,
        *,
        metadata_name: str = "metadata.json",
        output_name: str = "ocr.json",
    ) -> BatchResult:
        root = Path(session_dir)
        captures = _load_metadata(root / metadata_name)
        sources = [_source_path(root, capture) for capture in captures]
        pages = [_source_page(source) for source in sources]
        if len(set(pages)) != len(pages):
            raise OcrBatchError("successful captures do not have unique source_page identities")
        hashes = [_sha256(source) for source in sources]

        output_path = root / output_name
        existing = load_store(output_path)
        existing_by_page = {
            record["source_page"]: record
            for record in (existing["records"] if existing is not None else [])
        }
        prior_slots: list[dict[str, Any] | None] = [existing_by_page.get(page) for page in pages]
        slots: list[dict[str, Any] | None] = []
        prior_canonical_by_hash: dict[str, str] = {}
        for prior, page, source_hash in zip(prior_slots, pages, hashes):
            keep = prior is not None and _record_is_fresh(prior, page, source_hash, self.profile_id)
            if keep and prior["status"] == "duplicate":
                keep = prior.get("duplicate_of") == prior_canonical_by_hash.get(source_hash)
            if keep and prior["status"] != "duplicate":
                prior_canonical_by_hash.setdefault(source_hash, page)
            slots.append(prior if keep else None)
        processed = skipped = duplicates = blanks = retries = 0
        canonical_by_hash: dict[str, str] = {}

        for index, (capture, source, page, source_hash) in enumerate(zip(captures, sources, pages, hashes)):
            prior = slots[index]
            if prior is not None and _record_is_fresh(prior, page, source_hash, self.profile_id):
                if prior["status"] == "duplicate":
                    original_page = canonical_by_hash.get(source_hash)
                    if original_page != prior["duplicate_of"]:
                        raise OcrStoreError("fresh duplicate does not reference the canonical prior page")
                else:
                    canonical_by_hash.setdefault(source_hash, page)
                skipped += 1
                duplicates += int(prior["status"] == "duplicate")
                blanks += int(prior["status"] == "blank")
                continue

            if prior_slots[index] is not None:
                retries += 1
            page_record = self.processor.process(
                source,
                page_id=page,
                book_identifier=str(capture.get("window_title", "")),
            ).to_dict()
            page_record["ocr_profile_id"] = self.profile_id
            page_record["duplicate_of"] = None

            original_page = canonical_by_hash.get(source_hash)
            if original_page is None:
                canonical_by_hash[source_hash] = page
            else:
                page_record["status"] = "duplicate"
                page_record["text"] = ""
                page_record["duplicate_of"] = original_page
                duplicates += 1

            # No canonical upstream blank signal exists in the current capture schema.
            # Empty OCR text is deliberately retained as a normal success result.
            slots[index] = page_record
            processed += 1
            store = {
                "schema_version": 1,
                "ocr_profile_id": self.profile_id,
                "ocr_profile": self.profile,
                "records": [record for record in slots if record is not None],
            }
            atomic_write_store(output_path, store)

        records = [record for record in slots if record is not None]
        if len(records) != len(captures):
            raise OcrBatchError("OCR record count does not match metadata success count")
        final_store = {
            "schema_version": 1,
            "ocr_profile_id": self.profile_id,
            "ocr_profile": self.profile,
            "records": records,
        }
        atomic_write_store(output_path, final_store)
        return BatchResult(len(captures), len(records), processed, skipped, duplicates, blanks, retries)
