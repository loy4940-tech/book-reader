"""Canonical Gate 1 runner. Planning is default; OCR requires explicit --execute."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.gate1 import Status, TIMEOUT_SECONDS, canonical_hash, validate_ocr_status


def build_plan(manifest: dict, matrix: dict, gold_dir: Path, output: Path, timeout: int,
               run_id: str) -> dict:
    if timeout != TIMEOUT_SECONDS:
        raise ValueError(f"Gate 1 timeout must be {TIMEOUT_SECONDS} seconds")
    serialized = json.dumps({"manifest": manifest, "matrix": matrix}, ensure_ascii=False, sort_keys=True)
    if "acceptance" in serialized.lower():
        raise ValueError("Acceptance references are forbidden")
    pages = manifest.get("pages", [])
    candidates = matrix.get("candidates", [])
    if len(pages) != 10 or not candidates:
        raise ValueError("Gate 1 requires 10 Calibration pages and at least one candidate")
    if any(item.get("selected_set") != "CALIBRATION" for item in pages):
        raise ValueError("Gate 1 manifest must contain only explicitly marked Calibration pages")
    if not run_id:
        raise ValueError("Gate 1 requires an explicit non-empty run ID")
    if manifest.get("run_id") not in (None, run_id):
        raise ValueError("manifest run ID mismatch")
    return {
        "schema_version": 1, "gate_id": "GATE_1", "mode": "PLAN_ONLY",
        "run_id": run_id,
        "timeout_seconds": timeout, "retry": 0, "output_directory": str(output),
        "gold_reference": str(gold_dir), "dataset_hash": canonical_hash(manifest),
        "matrix_hash": canonical_hash(matrix), "run_count": 0,
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_worker_output(returncode: int, stdout: bytes) -> tuple[str, str | None]:
    if returncode != 0:
        return Status.ENGINE_ERROR.value, None
    try:
        payload = json.loads(stdout.decode("utf-8"))
        text = payload.get("text")
        if not isinstance(text, str):
            raise ValueError("worker OCR record has no string text field")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError) as exc:
        return Status.ENGINE_ERROR.value, f"invalid worker OCR record: {exc}"
    status = Status.EMPTY_OUTPUT if text == "" else Status.SUCCESS
    validate_ocr_status(status, text)
    return status.value, None


def execute(manifest: dict, matrix: dict, gold_dir: Path, output: Path, timeout: int,
            run_id: str, environment: dict | None = None) -> dict:
    """Execute only when explicitly authorized; emit LOCAL_ONLY evidence pending human rubric."""
    plan = build_plan(manifest, matrix, gold_dir, output, timeout, run_id)
    if environment is None:
        raise ValueError("formal Gate 1 execution requires an environment record")
    if environment is not None and environment.get("run_id") not in (None, run_id):
        raise ValueError("environment record run ID mismatch")
    output.mkdir(parents=True, exist_ok=False)
    run_manifest = dict(manifest)
    run_manifest["run_id"] = run_id
    (output / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if environment is not None:
        environment_record = dict(environment)
        environment_record["run_id"] = run_id
        (output / "environment.record.json").write_text(
            json.dumps(environment_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    candidate = matrix["candidates"][0]
    if len(matrix["candidates"]) != 1:
        raise ValueError("this runner version requires one fixed candidate per authorized run")
    candidate_id = str(candidate.get("candidate_id", ""))
    engine_id = str(candidate.get("engine", "")).lower()
    if not ((candidate_id.startswith("tesseract-") and engine_id == "tesseract") or
            (candidate_id == "yomitoku-0.13.1-cpu-lite-fixed-v1" and engine_id == "yomitoku")):
        raise ValueError("candidate ID and engine identity mismatch")
    records = []
    for item in manifest["pages"]:
        source = Path(item["source_reference"])
        gold = gold_dir / f'{item["input_id"]}.txt'
        if not source.is_file() or not gold.is_file():
            raise ValueError("Calibration source or gold reference is missing")
        page_output = output / item["input_id"]
        page_output.mkdir()
        command = [sys.executable, str(Path(__file__).with_name("gate1_page_worker.py")),
                   str(source), item["input_id"], item["language"], item["orientation"],
                   "--candidate-id", candidate["candidate_id"]]
        started = datetime.now().astimezone()
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
            status, protocol_error = _classify_worker_output(result.returncode, result.stdout)
            (page_output / "ocr_output.txt").write_bytes(result.stdout)
            stderr = result.stderr.decode("utf-8", errors="replace")[:500] or None
            error_message = protocol_error or stderr
        except subprocess.TimeoutExpired:
            status, error_message = "TIMEOUT", "page OCR exceeded canonical timeout"
        duration = (datetime.now().astimezone() - started).total_seconds()
        records.append({
            "candidate_id": candidate["candidate_id"], "engine": candidate["engine"],
            "engine_version": candidate["engine_version"],
            "routing_profile_set": candidate["routing_profile_set"],
            "input_id": item["input_id"], "routing_category": item["routing_category"],
            "input_hash": _file_hash(source), "gold_hash": _file_hash(gold), "status": status,
            "reading_order": {name: "PENDING_HUMAN_REVIEW" for name in (
                "COLUMN_ORDER", "BLOCK_ORDER", "OMISSION", "DUPLICATION", "CONTAMINATION")},
            "cer": None, "wer": None, "wer_status": "PENDING_METRIC_EVALUATION",
            "duration_seconds": duration, "error_code": None if status == "SUCCESS" else status,
            "error_message": error_message, "ocr_output_reference": str(page_output / "ocr_output.txt"),
        })
    evidence = {
        "schema_version": 1, "gate_id": "GATE_1", "run_id": run_id,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dataset_id": manifest["dataset_id"], "dataset_hash": canonical_hash(manifest),
        "gold_id": manifest["gold_id"], "gold_hash": canonical_hash(
            {item["input_id"]: _file_hash(gold_dir / f'{item["input_id"]}.txt') for item in manifest["pages"]}
        ), "candidates": matrix["candidates"], "pages": records,
        "selection_result": "PENDING_HUMAN_REVIEW", "plan": plan,
    }
    (output / "evidence.pending.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    review = {
        "schema_version": 1, "gate_id": "GATE_1", "run_id": evidence["run_id"],
        "pages": [{
            "page_id": page["input_id"], "candidate_id": page["candidate_id"],
            "categories": {name: "PENDING_HUMAN_REVIEW" for name in (
                "COLUMN_ORDER", "BLOCK_ORDER", "OMISSION", "DUPLICATION", "CONTAMINATION")},
            "note": "",
        } for page in records],
    }
    (output / "review.template.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True,
                        help="explicit canonical formal-run identifier")
    parser.add_argument("--environment-record", type=Path)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    environment = (json.loads(args.environment_record.read_text(encoding="utf-8"))
                   if args.environment_record else None)
    if args.execute:
        execute(manifest, matrix, args.gold_dir, args.output, args.timeout,
                args.run_id, environment)
        print(args.output / "evidence.pending.json")
        return 0
    plan = build_plan(manifest, matrix, args.gold_dir, args.output, args.timeout, args.run_id)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "run_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output / "run_plan.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
