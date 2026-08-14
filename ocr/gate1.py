"""Gate 1 canonical metrics, rubric, aggregation, and evidence validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
GATE_ID = "GATE_1"
TIMEOUT_SECONDS = 120
EXPECTED_PAGE_COUNT = 10
UNREADABLE_MARKER = "〓"


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    ENGINE_ERROR = "ENGINE_ERROR"
    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    INVALID_CONFIG = "INVALID_CONFIG"
    MISSING_LANGUAGE_DATA = "MISSING_LANGUAGE_DATA"
    UNREADABLE_INPUT = "UNREADABLE_INPUT"


class Severity(str, Enum):
    MAJOR = "Major"
    MINOR = "Minor"
    NONE = "None"


ERROR_CATEGORIES = (
    "COLUMN_ORDER", "BLOCK_ORDER", "OMISSION", "DUPLICATION", "CONTAMINATION"
)
EXECUTION_FAILURES = frozenset(
    {Status.EMPTY_OUTPUT, Status.ENGINE_ERROR, Status.CRASH, Status.TIMEOUT}
)
BLOCKED_STATUSES = frozenset(
    {Status.INVALID_CONFIG, Status.MISSING_LANGUAGE_DATA, Status.UNREADABLE_INPUT}
)


class Gate1ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MetricResult:
    value: float | None
    status: str
    excluded_unreadable_tokens: int = 0


def normalize_cer(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _levenshtein_with_gold_wildcard(gold: str, observed: str) -> int:
    previous = list(range(len(observed) + 1))
    for row, expected in enumerate(gold, 1):
        current = [row]
        for col, actual in enumerate(observed, 1):
            substitution = 0 if expected == actual or expected == UNREADABLE_MARKER else 1
            current.append(min(current[-1] + 1, previous[col] + 1, previous[col - 1] + substitution))
        previous = current
    return previous[-1]


def calculate_cer(gold: str, observed: str) -> float:
    normalized_gold = normalize_cer(gold)
    if not normalized_gold:
        raise Gate1ValidationError("normalized Calibration gold must not be empty")
    normalized_observed = normalize_cer(observed)
    return _levenshtein_with_gold_wildcard(normalized_gold, normalized_observed) / len(normalized_gold)


def _contains_japanese(text: str) -> bool:
    return any(
        "HIRAGANA" in unicodedata.name(ch, "")
        or "KATAKANA" in unicodedata.name(ch, "")
        or "CJK UNIFIED" in unicodedata.name(ch, "")
        for ch in text
    )


def calculate_wer(gold: str, observed: str) -> MetricResult:
    gold = unicodedata.normalize("NFKC", gold)
    observed = unicodedata.normalize("NFKC", observed)
    if _contains_japanese(gold):
        return MetricResult(None, "NOT_COMPUTABLE_JAPANESE_TOKENIZER_UNDEFINED")
    gold_tokens = gold.split()
    observed_tokens = observed.split()
    excluded = sum(UNREADABLE_MARKER in token for token in gold_tokens)
    gold_tokens = [token for token in gold_tokens if UNREADABLE_MARKER not in token]
    if not gold_tokens:
        return MetricResult(None, "NOT_COMPUTABLE_EMPTY_GOLD", excluded)
    distance = _sequence_distance(gold_tokens, observed_tokens)
    return MetricResult(distance / len(gold_tokens), "COMPUTED", excluded)


def _sequence_distance(expected: Sequence[str], observed: Sequence[str]) -> int:
    previous = list(range(len(observed) + 1))
    for row, token in enumerate(expected, 1):
        current = [row]
        for col, actual in enumerate(observed, 1):
            current.append(min(current[-1] + 1, previous[col] + 1,
                               previous[col - 1] + (token != actual)))
        previous = current
    return previous[-1]


def page_pass(status: Status | str, reading_order: Mapping[str, str]) -> bool:
    status = Status(status)
    if status is not Status.SUCCESS:
        return False
    _validate_reading_order(reading_order)
    return all(value != Severity.MAJOR.value for value in reading_order.values())


def _validate_reading_order(reading_order: Mapping[str, str]) -> None:
    if set(reading_order) != set(ERROR_CATEGORIES):
        raise Gate1ValidationError("reading_order must contain exactly the canonical categories")
    valid = {item.value for item in Severity}
    if any(value not in valid for value in reading_order.values()):
        raise Gate1ValidationError("invalid reading-order severity")


def aggregate_candidate(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    major = failures = blocked = empty = 0
    cer_values: list[float] = []
    passed = 0
    for page in pages:
        status = Status(page["status"])
        order = page["reading_order"]
        _validate_reading_order(order)
        major += sum(value == Severity.MAJOR.value for value in order.values())
        failures += status in EXECUTION_FAILURES
        blocked += status in BLOCKED_STATUSES
        empty += status is Status.EMPTY_OUTPUT
        passed += page_pass(status, order)
        cer = page.get("cer")
        if cer is not None:
            if not isinstance(cer, (int, float)) or not math.isfinite(cer) or cer < 0:
                raise Gate1ValidationError("invalid CER")
            cer_values.append(float(cer))
    dataset_pass = len(pages) == EXPECTED_PAGE_COUNT and passed == EXPECTED_PAGE_COUNT
    return {
        "page_count": len(pages), "page_pass_count": passed, "major_count": major,
        "page_failure_count": failures, "blocked_count": blocked, "empty_count": empty,
        "mean_cer": sum(cer_values) / len(cer_values) if cer_values else None,
        "dataset_pass": dataset_pass,
        "provisional_eligible": dataset_pass and major == failures == blocked == 0,
    }


def compare_candidates(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not summaries:
        return {"gate_status": "FAIL", "selection_result": "NO_SELECTION", "candidate_id": None}
    if any(int(item["blocked_count"]) for item in summaries):
        return {"gate_status": "BLOCKED", "selection_result": "NO_SELECTION", "candidate_id": None}
    eligible = [item for item in summaries if item["provisional_eligible"]]
    if not eligible:
        return {"gate_status": "FAIL", "selection_result": "NO_SELECTION", "candidate_id": None}
    def quality(item: Mapping[str, Any]) -> tuple[Any, ...]:
        return (-int(bool(item["dataset_pass"])), int(item["major_count"]),
                int(item["page_failure_count"]), float(item["mean_cer"] or 0.0))
    eligible = sorted(eligible, key=lambda item: (quality(item), str(item["candidate_id"])))
    best_quality = quality(eligible[0])
    tied = [item for item in eligible if quality(item) == best_quality]
    if len(tied) > 1:
        return {"gate_status": "FAIL", "selection_result": "TIE / NO_SELECTION", "candidate_id": None}
    return {"gate_status": "PASS", "selection_result": "PROVISIONAL", "candidate_id": eligible[0]["candidate_id"]}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _contains_acceptance(value: Any, acceptance_ids: set[str]) -> bool:
    if isinstance(value, str):
        lowered = value.replace("\\", "/").lower()
        return value in acceptance_ids or "acceptance" in PurePath(lowered).parts or "/acceptance/" in f"/{lowered}/"
    if isinstance(value, Mapping):
        return any(_contains_acceptance(item, acceptance_ids) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_acceptance(item, acceptance_ids) for item in value)
    return False


def validate_evidence(
    evidence: Mapping[str, Any], *, expected_calibration_ids: set[str],
    acceptance_ids: set[str], expected_candidate_ids: set[str],
    expected_dataset_hash: str | None = None, expected_gold_hash: str | None = None,
    ocr_texts: Mapping[tuple[str, str], str] | None = None,
) -> None:
    required = {"schema_version", "gate_id", "run_id", "timestamp", "git_commit",
                "dataset_id", "dataset_hash", "gold_id", "gold_hash", "candidates",
                "pages", "selection_result"}
    missing = required - evidence.keys()
    if missing:
        raise Gate1ValidationError(f"missing evidence fields: {sorted(missing)}")
    if evidence["schema_version"] != SCHEMA_VERSION or evidence["gate_id"] != GATE_ID:
        raise Gate1ValidationError("unknown evidence schema or gate")
    if _contains_acceptance(evidence, acceptance_ids):
        raise Gate1ValidationError("Acceptance reference is forbidden")
    if expected_dataset_hash and evidence["dataset_hash"] != expected_dataset_hash:
        raise Gate1ValidationError("dataset identity mismatch")
    if expected_gold_hash and evidence["gold_hash"] != expected_gold_hash:
        raise Gate1ValidationError("gold identity mismatch")
    candidates = [item["candidate_id"] for item in evidence["candidates"]]
    if len(candidates) != len(set(candidates)) or set(candidates) != expected_candidate_ids:
        raise Gate1ValidationError("candidate matrix is missing, duplicate, or unknown")
    pages = evidence["pages"]
    keys = [(item.get("candidate_id"), item.get("input_id")) for item in pages]
    expected_keys = {(candidate, page) for candidate in expected_candidate_ids for page in expected_calibration_ids}
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise Gate1ValidationError("Calibration runs are missing, duplicate, unknown, or unexpected")
    for page in pages:
        page_required = {"candidate_id", "input_id", "routing_category", "status",
                         "reading_order", "cer", "wer", "wer_status", "duration_seconds",
                         "error_code", "error_message"}
        if page_required - page.keys():
            raise Gate1ValidationError("missing per-page evidence fields")
        Status(page["status"])
        _validate_reading_order(page["reading_order"])
        duration = page.get("duration_seconds")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
            raise Gate1ValidationError("invalid duration")
        cer = page.get("cer")
        if cer is not None and (not isinstance(cer, (int, float)) or not math.isfinite(cer) or cer < 0):
            raise Gate1ValidationError("invalid CER")
    if ocr_texts is not None:
        validate_ocr_statuses(pages, ocr_texts)
    if any("PENDING" in str(value) for value in _walk_values(evidence)):
        raise Gate1ValidationError("pending values are forbidden in final evidence")
    summaries = evidence.get("candidate_summaries")
    if not isinstance(summaries, list) or len(summaries) != len(expected_candidate_ids):
        raise Gate1ValidationError("missing candidate summaries")
    recomputed = []
    for candidate_id in sorted(expected_candidate_ids):
        summary = aggregate_candidate([page for page in pages if page["candidate_id"] == candidate_id])
        summary["candidate_id"] = candidate_id
        recomputed.append(summary)
    if summaries != recomputed:
        raise Gate1ValidationError("candidate aggregation mismatch")
    if evidence["selection_result"] != compare_candidates(recomputed):
        raise Gate1ValidationError("selection result mismatch")


def _walk_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def validate_ocr_status(status: Status | str, text: str) -> None:
    """Reject contradictions between canonical OCR text and its execution status."""
    status = Status(status)
    if not isinstance(text, str):
        raise Gate1ValidationError("OCR output text must be a string")
    if status is Status.SUCCESS and text == "":
        raise Gate1ValidationError("SUCCESS OCR output must not have empty text")
    if status is Status.EMPTY_OUTPUT and text != "":
        raise Gate1ValidationError("EMPTY_OUTPUT OCR output must have empty text")


def validate_ocr_statuses(
    pages: Sequence[Mapping[str, Any]], ocr_texts: Mapping[tuple[str, str], str],
) -> None:
    for page in pages:
        status = Status(page["status"])
        if status not in {Status.SUCCESS, Status.EMPTY_OUTPUT}:
            continue
        key = (page["candidate_id"], page["input_id"])
        if key not in ocr_texts:
            raise Gate1ValidationError("OCR text reference is missing")
        validate_ocr_status(status, ocr_texts[key])


def validate_pending(
    evidence: Mapping[str, Any],
    ocr_texts: Mapping[tuple[str, str], str] | None = None,
) -> None:
    if evidence.get("schema_version") != SCHEMA_VERSION or evidence.get("gate_id") != GATE_ID:
        raise Gate1ValidationError("unknown pending evidence schema or gate")
    if not evidence.get("run_id") or len(evidence.get("pages", [])) != EXPECTED_PAGE_COUNT:
        raise Gate1ValidationError("pending evidence must contain one complete Calibration run")
    keys = [(page.get("candidate_id"), page.get("input_id")) for page in evidence["pages"]]
    if len(keys) != len(set(keys)):
        raise Gate1ValidationError("duplicate pending page")
    for page in evidence["pages"]:
        Status(page["status"])
        if set(page.get("reading_order", {})) != set(ERROR_CATEGORIES):
            raise Gate1ValidationError("incomplete pending rubric")
        if any(value != "PENDING_HUMAN_REVIEW" for value in page["reading_order"].values()):
            raise Gate1ValidationError("pending rubric has unexpected values")
    if ocr_texts is not None:
        validate_ocr_statuses(evidence["pages"], ocr_texts)


def validate_review(review: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    if review.get("run_id") != pending.get("run_id"):
        raise Gate1ValidationError("review run ID mismatch")
    records = review.get("pages")
    if not isinstance(records, list):
        raise Gate1ValidationError("review pages are missing")
    expected = {(page["candidate_id"], page["input_id"]) for page in pending["pages"]}
    mapped: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in records:
        key = (item.get("candidate_id"), item.get("page_id"))
        if key in mapped:
            raise Gate1ValidationError("duplicate review page")
        _validate_reading_order(item.get("categories", {}))
        mapped[key] = item
    if set(mapped) != expected:
        raise Gate1ValidationError("review pages are missing or unknown")
    return mapped


def finalize_evidence(
    pending: Mapping[str, Any], review: Mapping[str, Any], *, gold_texts: Mapping[str, str],
    ocr_texts: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    validate_pending(pending, ocr_texts)
    annotations = validate_review(review, pending)
    final_pages = []
    for original in pending["pages"]:
        page = dict(original)
        key = (page["candidate_id"], page["input_id"])
        page["reading_order"] = dict(annotations[key]["categories"])
        if page["status"] == Status.SUCCESS.value:
            if page["input_id"] not in gold_texts or key not in ocr_texts:
                raise Gate1ValidationError("gold or OCR text reference is missing")
            gold, observed = gold_texts[page["input_id"]], ocr_texts[key]
            page["cer"] = calculate_cer(gold, observed)
            wer = calculate_wer(gold, observed)
            page["wer"], page["wer_status"] = wer.value, wer.status
            page["wer_excluded_unreadable_tokens"] = wer.excluded_unreadable_tokens
        else:
            page["cer"], page["wer"] = None, None
            page["wer_status"] = "NOT_COMPUTABLE_EXECUTION_FAILURE"
            page["wer_excluded_unreadable_tokens"] = 0
        page["page_pass"] = page_pass(page["status"], page["reading_order"])
        page["severity_summary"] = {
            severity.value: sum(value == severity.value for value in page["reading_order"].values())
            for severity in Severity
        }
        final_pages.append(page)
    summaries = []
    for candidate in pending["candidates"]:
        summary = aggregate_candidate([page for page in final_pages if page["candidate_id"] == candidate["candidate_id"]])
        summary["candidate_id"] = candidate["candidate_id"]
        summaries.append(summary)
    final = dict(pending)
    final["pages"] = final_pages
    final["candidate_summaries"] = summaries
    final["selection_result"] = compare_candidates(summaries)
    final["lifecycle_state"] = "FINAL"
    final.pop("plan", None)
    return final
