"""Validation and atomic persistence for the canonical Phase 8B OCR store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


STORE_SCHEMA_VERSION = 1
TERMINAL_STATUSES = frozenset({"success", "blank", "duplicate"})
RETRYABLE_STATUSES = frozenset({"error", "failed", "interrupted", "incomplete"})
KNOWN_STATUSES = TERMINAL_STATUSES | RETRYABLE_STATUSES

_PAGE_FIELDS = {
    "source_page",
    "source_sha256",
    "status",
    "text",
    "classifier",
    "engine",
    "engine_version",
    "engine_state",
    "parameters",
    "model_sha256",
    "preprocess_version",
    "classifier_version",
    "pipeline_version",
    "processed_at",
    "elapsed_seconds",
    "ocr_profile_id",
    "duplicate_of",
}


class OcrStoreError(RuntimeError):
    """Raised when an existing canonical OCR store is unsafe to use."""


def validate_record(record: Mapping[str, Any]) -> None:
    missing = _PAGE_FIELDS - set(record)
    if missing:
        raise OcrStoreError(f"OCR record is missing fields: {sorted(missing)}")
    if not isinstance(record["source_page"], str) or not record["source_page"]:
        raise OcrStoreError("OCR record has invalid source_page")
    if not isinstance(record["source_sha256"], str) or len(record["source_sha256"]) != 64:
        raise OcrStoreError("OCR record has invalid source_sha256")
    if not isinstance(record["ocr_profile_id"], str) or len(record["ocr_profile_id"]) != 64:
        raise OcrStoreError("OCR record has invalid ocr_profile_id")
    if record["status"] not in KNOWN_STATUSES:
        raise OcrStoreError(f"OCR record has unsupported status: {record['status']!r}")
    if not isinstance(record["text"], str):
        raise OcrStoreError("OCR record text must be a string")
    duplicate_of = record["duplicate_of"]
    if record["status"] == "duplicate":
        if not isinstance(duplicate_of, str) or not duplicate_of:
            raise OcrStoreError("duplicate record requires duplicate_of")
    elif duplicate_of is not None:
        raise OcrStoreError("non-duplicate record must have duplicate_of=null")


def validate_store(store: Mapping[str, Any]) -> None:
    if store.get("schema_version") != STORE_SCHEMA_VERSION:
        raise OcrStoreError("unsupported OCR store schema_version")
    if not isinstance(store.get("ocr_profile_id"), str) or len(store["ocr_profile_id"]) != 64:
        raise OcrStoreError("invalid OCR store profile ID")
    if not isinstance(store.get("ocr_profile"), dict):
        raise OcrStoreError("invalid OCR profile")
    records = store.get("records")
    if not isinstance(records, list):
        raise OcrStoreError("OCR records must be a list")
    identities: set[str] = set()
    records_by_page: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise OcrStoreError("OCR record must be an object")
        validate_record(record)
        source_page = record["source_page"]
        if source_page in identities:
            raise OcrStoreError(f"duplicate source_page in OCR store: {source_page}")
        identities.add(source_page)
        records_by_page[source_page] = record
    for record in records:
        if record["status"] != "duplicate":
            continue
        original = records_by_page.get(record["duplicate_of"])
        if original is None or original["status"] == "duplicate":
            raise OcrStoreError("duplicate_of must reference a non-duplicate record")
        if original["source_sha256"] != record["source_sha256"]:
            raise OcrStoreError("duplicate source hash differs from original")


def load_store(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OcrStoreError(f"cannot read existing OCR store: {path}") from exc
    if not isinstance(value, dict):
        raise OcrStoreError("OCR store root must be an object")
    validate_store(value)
    return value


def atomic_write_store(path: Path, store: Mapping[str, Any]) -> None:
    validate_store(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(store, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except OSError:
                pass

