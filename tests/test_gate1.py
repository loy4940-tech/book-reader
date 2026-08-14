import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ocr.gate1 import (
    ERROR_CATEGORIES, Gate1ValidationError, Status, aggregate_candidate,
    calculate_cer, calculate_wer, compare_candidates, page_pass, validate_evidence,
    finalize_evidence, validate_ocr_status, validate_pending, validate_review,
)
from tools.run_gate1 import _classify_worker_output, build_plan, execute


CAL = {f"CAND-{number:04d}" for number in range(1, 11)}
ACC = {f"ACC-{number:04d}" for number in range(1, 11)}
NONE = {category: "None" for category in ERROR_CATEGORIES}
REPO_ROOT = Path(__file__).resolve().parents[1]


def page(input_id, candidate="tesseract-v1", status="SUCCESS", order=None, cer=0.1):
    return {"candidate_id": candidate, "input_id": input_id, "routing_category": "ja_horizontal",
            "status": status, "reading_order": order or dict(NONE), "cer": cer,
            "wer": None, "wer_status": "NOT_COMPUTABLE_JAPANESE_TOKENIZER_UNDEFINED",
            "duration_seconds": 1.0, "error_code": None, "error_message": None}


def evidence():
    pages = [page(item) for item in sorted(CAL)]
    candidate_summary = aggregate_candidate(pages); candidate_summary["candidate_id"] = "tesseract-v1"
    return {"schema_version": 1, "gate_id": "GATE_1", "run_id": "fixture", "timestamp": "2026-08-14T00:00:00+09:00",
            "git_commit": "a" * 40, "dataset_id": "cal-v1", "dataset_hash": "d" * 64,
            "gold_id": "gold-v1", "gold_hash": "e" * 64,
            "candidates": [{"candidate_id": "tesseract-v1", "engine": "tesseract", "engine_version": "5.4",
                            "routing_profile_set": {"ja_vertical": ["jpn_vert", 5, 3], "ja_horizontal": ["jpn", 6, 3],
                                                    "en_horizontal": ["eng", 6, 3]}}],
            "pages": pages, "candidate_summaries": [candidate_summary],
            "selection_result": compare_candidates([candidate_summary])}


def validate(item):
    validate_evidence(item, expected_calibration_ids=CAL, acceptance_ids=ACC,
                      expected_candidate_ids={"tesseract-v1"}, expected_dataset_hash="d" * 64,
                      expected_gold_hash="e" * 64)


def schema_accepts(item, tmp_path):
    payload = tmp_path / "evidence.json"
    payload.write_text(json.dumps(item), encoding="utf-8")
    schema = REPO_ROOT / "docs" / "gate1_evidence.schema.json"
    command = (
        f"$value=Get-Content -Raw -LiteralPath '{payload}'; "
        f"if($value | Test-Json -SchemaFile '{schema}'){{exit 0}}else{{exit 1}}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command], cwd=REPO_ROOT,
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def test_final_schema_accepts_fail_no_selection(tmp_path):
    item = evidence()
    item["selection_result"] = {
        "gate_status": "FAIL", "selection_result": "NO_SELECTION", "candidate_id": None,
    }
    assert schema_accepts(item, tmp_path)


def test_final_schema_accepts_pass_provisional(tmp_path):
    assert evidence()["selection_result"] == {
        "gate_status": "PASS", "selection_result": "PROVISIONAL", "candidate_id": "tesseract-v1",
    }
    assert schema_accepts(evidence(), tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "gate", "selection", "candidate"])
def test_final_schema_rejects_invalid_selection_object(mutation, tmp_path):
    item = evidence()
    if mutation == "missing":
        del item["selection_result"]["candidate_id"]
    elif mutation == "gate":
        item["selection_result"]["gate_status"] = "UNKNOWN"
    elif mutation == "selection":
        item["selection_result"]["selection_result"] = "SELECTED"
    else:
        item["selection_result"]["candidate_id"] = 42
    assert not schema_accepts(item, tmp_path)


@pytest.mark.parametrize("selection", [
    {"gate_status": "FAIL", "selection_result": "PROVISIONAL", "candidate_id": "tesseract-v1"},
    {"gate_status": "PASS", "selection_result": "NO_SELECTION", "candidate_id": None},
])
def test_semantic_validator_rejects_contradictory_selection(selection):
    item = evidence(); item["selection_result"] = selection
    with pytest.raises(Gate1ValidationError, match="selection result mismatch"):
        validate(item)


def test_valid_evidence_passes(): validate(evidence())


@pytest.mark.parametrize("mutation", ["missing", "unknown", "duplicate"])
def test_bad_calibration_pages_rejected(mutation):
    item = evidence()
    if mutation == "missing": item["pages"].pop()
    elif mutation == "unknown": item["pages"][0]["input_id"] = "CAND-9999"
    else: item["pages"][0] = copy.deepcopy(item["pages"][1])
    with pytest.raises(Gate1ValidationError): validate(item)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_bad_candidate_matrix_rejected(mutation):
    item = evidence()
    if mutation == "missing": item["candidates"] = []
    elif mutation == "duplicate": item["candidates"].append(copy.deepcopy(item["candidates"][0]))
    else: item["candidates"][0]["candidate_id"] = "unknown"
    with pytest.raises(Gate1ValidationError): validate(item)


def test_invalid_status_rejected():
    item = evidence(); item["pages"][0]["status"] = "BOGUS"
    with pytest.raises(ValueError): validate(item)


def test_missing_page_evidence_field_rejected():
    item = evidence(); del item["pages"][0]["wer_status"]
    with pytest.raises(Gate1ValidationError): validate(item)


@pytest.mark.parametrize("status", ["EMPTY_OUTPUT", "ENGINE_ERROR", "CRASH", "TIMEOUT"])
def test_execution_failure_is_page_fail(status): assert not page_pass(status, NONE)


@pytest.mark.parametrize("status", ["INVALID_CONFIG", "MISSING_LANGUAGE_DATA", "UNREADABLE_INPUT"])
def test_blocked_status_blocks_candidate(status):
    pages = [page(item) for item in sorted(CAL)]; pages[0]["status"] = status
    assert aggregate_candidate(pages)["blocked_count"] == 1


def test_cer_nfkc_and_whitespace(): assert calculate_cer("Ａ B\n", "AB") == 0
def test_cer_preserves_punctuation(): assert calculate_cer("a。", "a,") == pytest.approx(0.5)
def test_marker_matches_exactly_one(): assert calculate_cer("a〓b", "aXb") == 0
def test_marker_does_not_match_zero(): assert calculate_cer("a〓b", "ab") > 0
def test_marker_does_not_match_multiple(): assert calculate_cer("a〓b", "aXYb") > 0


def test_japanese_wer_not_computable(): assert calculate_wer("日本語", "日本語").value is None
def test_english_wer(): assert calculate_wer("one two", "one too").value == pytest.approx(0.5)


def test_major_fails_and_minor_passes():
    major = dict(NONE); major["BLOCK_ORDER"] = "Major"
    minor = dict(NONE); minor["OMISSION"] = "Minor"
    assert not page_pass(Status.SUCCESS, major) and page_pass(Status.SUCCESS, minor)


def test_dataset_ten_passes(): assert aggregate_candidate([page(item) for item in CAL])["dataset_pass"]
def test_dataset_nine_fails(): assert not aggregate_candidate([page(item) for item in list(CAL)[:9]])["dataset_pass"]


def summary(candidate="a", **changes):
    base = aggregate_candidate([page(item, candidate) for item in CAL]); base["candidate_id"] = candidate
    base.update(changes); return base


def test_execution_failure_means_no_selection():
    assert compare_candidates([summary(provisional_eligible=False, page_failure_count=1)])["selection_result"] == "NO_SELECTION"
def test_blocked_means_gate_blocked(): assert compare_candidates([summary(blocked_count=1)])["gate_status"] == "BLOCKED"
def test_complete_pass_selects_provisional(): assert compare_candidates([summary()])["selection_result"] == "PROVISIONAL"
def test_exact_quality_tie_means_no_selection(): assert compare_candidates([summary("a"), summary("b")])["selection_result"] == "TIE / NO_SELECTION"


def test_acceptance_id_rejected():
    item = evidence(); item["pages"][0]["input_id"] = "ACC-0001"
    with pytest.raises(Gate1ValidationError): validate(item)
def test_acceptance_reference_rejected():
    item = evidence(); item["gold_id"] = "dist/output/acceptance/gold"
    with pytest.raises(Gate1ValidationError): validate(item)
def test_dataset_identity_rejected():
    item = evidence(); item["dataset_hash"] = "x" * 64
    with pytest.raises(Gate1ValidationError): validate(item)
def test_gold_identity_rejected():
    item = evidence(); item["gold_hash"] = "x" * 64
    with pytest.raises(Gate1ValidationError): validate(item)


@pytest.mark.parametrize("script", ["validate_gate1.py", "run_gate1.py"])
def test_canonical_cli_direct_help_from_repository_root(script):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / script), "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_validator_direct_invocation_imports_gate1():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "validate_gate1.py"), "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert "ModuleNotFoundError" not in result.stderr


def pending():
    item = evidence()
    item.pop("candidate_summaries")
    item["selection_result"] = "PENDING_HUMAN_REVIEW"
    for record in item["pages"]:
        record["reading_order"] = {name: "PENDING_HUMAN_REVIEW" for name in ERROR_CATEGORIES}
        record["cer"] = record["wer"] = None
        record["wer_status"] = "PENDING_METRIC_EVALUATION"
        record["ocr_output_reference"] = "synthetic-output.json"
    return item


def review(item=None, severity="None"):
    item = item or pending()
    return {"schema_version": 1, "gate_id": "GATE_1", "run_id": item["run_id"],
            "pages": [{"page_id": page["input_id"], "candidate_id": page["candidate_id"],
                       "categories": {name: severity for name in ERROR_CATEGORIES}, "note": ""}
                      for page in item["pages"]]}


def test_pending_contract_accepts_pending_values(): validate_pending(pending())


@pytest.mark.parametrize("payload", [b'{"text":"abc"}', '{"text":"日本語"}'.encode("utf-8")])
def test_structured_non_empty_worker_output_is_success(payload):
    assert _classify_worker_output(0, payload) == ("SUCCESS", None)


def test_non_empty_json_wrapper_with_empty_text_is_empty_output():
    assert _classify_worker_output(0, b'{"text":""}') == ("EMPTY_OUTPUT", None)


def test_invalid_worker_record_is_engine_error():
    status, error = _classify_worker_output(0, b'{"not_text":"value"}')
    assert status == "ENGINE_ERROR"
    assert error and "invalid worker OCR record" in error


def test_strict_worker_protocol_rejects_diagnostic_prefix():
    status, error = _classify_worker_output(0, b'Loading weights\n{"text":"synthetic"}')
    assert status == "ENGINE_ERROR"
    assert error and "invalid worker OCR record" in error


def test_success_with_empty_text_is_rejected():
    with pytest.raises(Gate1ValidationError, match="SUCCESS.*empty"):
        validate_ocr_status("SUCCESS", "")


def test_empty_output_with_non_empty_text_is_rejected():
    with pytest.raises(Gate1ValidationError, match="EMPTY_OUTPUT.*empty"):
        validate_ocr_status("EMPTY_OUTPUT", "text")


def test_pending_status_text_consistency():
    item = pending()
    texts = {(page["candidate_id"], page["input_id"]): "text" for page in item["pages"]}
    validate_pending(item, texts)
    texts[(item["pages"][0]["candidate_id"], item["pages"][0]["input_id"])] = ""
    with pytest.raises(Gate1ValidationError, match="SUCCESS.*empty"):
        validate_pending(item, texts)


def test_final_validator_rejects_pending_values():
    with pytest.raises(Gate1ValidationError): validate(pending())


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "severity", "run"])
def test_invalid_review_rejected(mutation):
    p = pending(); r = review(p)
    if mutation == "missing": r["pages"].pop()
    elif mutation == "duplicate": r["pages"][0] = copy.deepcopy(r["pages"][1])
    elif mutation == "unknown": r["pages"][0]["page_id"] = "CAND-9999"
    elif mutation == "severity": r["pages"][0]["categories"]["OMISSION"] = "PENDING_HUMAN_REVIEW"
    else: r["run_id"] = "wrong"
    with pytest.raises(Gate1ValidationError): validate_review(r, p)


def test_finalize_synthetic_pass_and_selection():
    p = pending(); r = review(p)
    gold = {page_id: "日本語 gold" for page_id in CAL}
    ocr = {("tesseract-v1", page_id): "日本語 gold" for page_id in CAL}
    final = finalize_evidence(p, r, gold_texts=gold, ocr_texts=ocr)
    assert final["candidate_summaries"][0]["dataset_pass"] is True
    assert final["selection_result"]["selection_result"] == "PROVISIONAL"
    validate(final)


def test_finalize_execution_failure_no_selection():
    p = pending(); p["pages"][0]["status"] = "EMPTY_OUTPUT"
    r = review(p); gold = {page_id: "日本語" for page_id in CAL}
    empty_id = p["pages"][0]["input_id"]
    ocr = {("tesseract-v1", page_id): "" if page_id == empty_id else "日本語" for page_id in CAL}
    final = finalize_evidence(p, r, gold_texts=gold, ocr_texts=ocr)
    assert final["pages"][0]["status"] == "EMPTY_OUTPUT"
    assert final["pages"][0]["page_pass"] is False
    assert final["candidate_summaries"][0]["empty_count"] == 1
    assert final["selection_result"]["selection_result"] == "NO_SELECTION"


def test_finalize_blocked_status():
    p = pending(); p["pages"][0]["status"] = "INVALID_CONFIG"
    r = review(p); gold = {page_id: "日本語" for page_id in CAL}
    ocr = {("tesseract-v1", page_id): "日本語" for page_id in CAL if page_id != p["pages"][0]["input_id"]}
    final = finalize_evidence(p, r, gold_texts=gold, ocr_texts=ocr)
    assert final["selection_result"]["gate_status"] == "BLOCKED"


def test_synthetic_empty_output_e2e_and_validator_cli(tmp_path):
    p = pending(); empty_id = p["pages"][0]["input_id"]
    p["pages"][0]["status"] = "EMPTY_OUTPUT"
    r = review(p)
    gold = {page_id: "synthetic gold" for page_id in CAL}
    ocr = {("tesseract-v1", page_id): "" if page_id == empty_id else "synthetic" for page_id in CAL}
    output_dir = tmp_path / "ocr"; output_dir.mkdir()
    for record in p["pages"]:
        path = output_dir / f'{record["input_id"]}.json'
        path.write_text(json.dumps({"text": ocr[(record["candidate_id"], record["input_id"])]}), encoding="utf-8")
        record["ocr_output_reference"] = str(path)
    final = finalize_evidence(p, r, gold_texts=gold, ocr_texts=ocr)
    final_path = tmp_path / "final.json"
    final_path.write_text(json.dumps(final), encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(REPO_ROOT / "tools" / "validate_gate1.py"), str(final_path),
        "--calibration-ids", ",".join(sorted(CAL)), "--acceptance-ids", ",".join(sorted(ACC)),
        "--candidate-ids", "tesseract-v1", "--dataset-hash", "d" * 64,
        "--gold-hash", "e" * 64,
    ], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert schema_accepts(final, tmp_path)
    assert final["pages"][0]["status"] == "EMPTY_OUTPUT"
    assert final["selection_result"]["selection_result"] == "NO_SELECTION"


def test_validator_rejects_success_with_empty_referenced_text(tmp_path):
    item = evidence(); output_dir = tmp_path / "ocr"; output_dir.mkdir()
    texts = {}
    for record in item["pages"]:
        text = "" if record is item["pages"][0] else "synthetic"
        path = output_dir / f'{record["input_id"]}.json'
        path.write_text(json.dumps({"text": text}), encoding="utf-8")
        record["ocr_output_reference"] = str(path)
        texts[(record["candidate_id"], record["input_id"])] = text
    with pytest.raises(Gate1ValidationError, match="SUCCESS.*empty"):
        validate_evidence(item, expected_calibration_ids=CAL, acceptance_ids=ACC,
                          expected_candidate_ids={"tesseract-v1"}, ocr_texts=texts)


def test_finalizer_cli_synthetic_end_to_end(tmp_path):
    p = pending(); r = review(p); gold_dir = tmp_path / "gold"; out_dir = tmp_path / "ocr"
    gold_dir.mkdir(); out_dir.mkdir()
    for record in p["pages"]:
        (gold_dir / f'{record["input_id"]}.txt').write_text("日本語 gold", encoding="utf-8")
        output = out_dir / f'{record["input_id"]}.json'
        output.write_text(json.dumps({"text": "日本語 gold"}), encoding="utf-8")
        record["ocr_output_reference"] = str(output)
    pending_path, review_path, final_path = tmp_path / "pending.json", tmp_path / "review.json", tmp_path / "final.json"
    pending_path.write_text(json.dumps(p), encoding="utf-8"); review_path.write_text(json.dumps(r), encoding="utf-8")
    command = [sys.executable, str(REPO_ROOT / "tools" / "finalize_gate1.py"), "--pending", str(pending_path),
               "--review", str(review_path), "--gold", str(gold_dir), "--output", str(final_path)]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    validate(json.loads(final_path.read_text(encoding="utf-8")))


def test_finalizer_direct_help():
    result = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "finalize_gate1.py"), "--help"],
                            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0


def _runner_fixture(tmp_path, run_id="G1-TEST-001"):
    gold = tmp_path / "gold"; sources = tmp_path / "sources"
    gold.mkdir(); sources.mkdir()
    pages = []
    for page_id in sorted(CAL):
        source = sources / f"{page_id}.png"
        source.write_bytes(b"synthetic-not-an-image")
        (gold / f"{page_id}.txt").write_text("synthetic gold", encoding="utf-8")
        pages.append({"input_id": page_id, "source_reference": str(source),
                      "selected_set": "CALIBRATION", "language": "eng",
                      "orientation": "horizontal", "routing_category": "en_horizontal"})
    manifest = {"run_id": run_id, "dataset_id": "synthetic-cal", "gold_id": "synthetic-gold",
                "pages": pages}
    matrix = {"candidates": [{"candidate_id": "tesseract-v1", "engine": "tesseract",
                              "engine_version": "5.4", "routing_profile_set": {}}]}
    return manifest, matrix, gold


def test_explicit_run_id_is_independent_of_nested_output(monkeypatch, tmp_path):
    run_id = "G1-TEST-001"
    manifest, matrix, gold = _runner_fixture(tmp_path, run_id)
    environment = {"run_id": run_id, "runtime": "synthetic"}
    output = tmp_path / run_id / "formal"

    class Result:
        returncode = 0
        stdout = b'{"text":"synthetic"}'
        stderr = b""

    monkeypatch.setattr("tools.run_gate1.subprocess.run", lambda *args, **kwargs: Result())
    monkeypatch.setattr("tools.run_gate1.subprocess.check_output", lambda *args, **kwargs: "a" * 40)
    result = execute(manifest, matrix, gold, output, 120, run_id, environment)

    assert result["run_id"] == run_id != output.name
    assert json.loads((output / "evidence.pending.json").read_text(encoding="utf-8"))["run_id"] == run_id
    assert json.loads((output / "review.template.json").read_text(encoding="utf-8"))["run_id"] == run_id
    assert json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))["run_id"] == run_id
    assert json.loads((output / "environment.record.json").read_text(encoding="utf-8"))["run_id"] == run_id

    reviewed = review(result)
    gold_texts = {page_id: "synthetic gold" for page_id in CAL}
    ocr_texts = {("tesseract-v1", page_id): "synthetic" for page_id in CAL}
    final = finalize_evidence(result, reviewed, gold_texts=gold_texts, ocr_texts=ocr_texts)
    assert final["run_id"] == run_id
    validate_evidence(final, expected_calibration_ids=CAL, acceptance_ids=ACC,
                      expected_candidate_ids={"tesseract-v1"},
                      expected_dataset_hash=result["dataset_hash"],
                      expected_gold_hash=result["gold_hash"])


def test_runner_empty_output_through_finalizer_and_validator(monkeypatch, tmp_path):
    run_id = "G1-TEST-EMPTY-001"
    manifest, matrix, gold_dir = _runner_fixture(tmp_path, run_id)
    output = tmp_path / run_id / "formal"
    calls = iter([b'{"text":""}'] + [b'{"text":"synthetic"}'] * 9)

    class Result:
        returncode = 0
        stderr = b""

        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(
        "tools.run_gate1.subprocess.run", lambda *args, **kwargs: Result(next(calls))
    )
    monkeypatch.setattr("tools.run_gate1.subprocess.check_output", lambda *args, **kwargs: "a" * 40)
    pending_result = execute(
        manifest, matrix, gold_dir, output, 120, run_id,
        {"run_id": run_id, "runtime": "synthetic"},
    )
    empty_page = pending_result["pages"][0]
    assert empty_page["status"] == "EMPTY_OUTPUT"
    assert json.loads(Path(empty_page["ocr_output_reference"]).read_text(encoding="utf-8"))["text"] == ""

    reviewed = review(pending_result)
    gold_texts = {page_id: "synthetic gold" for page_id in CAL}
    ocr_texts = {
        (record["candidate_id"], record["input_id"]):
            json.loads(Path(record["ocr_output_reference"]).read_text(encoding="utf-8"))["text"]
        for record in pending_result["pages"]
    }
    final = finalize_evidence(
        pending_result, reviewed, gold_texts=gold_texts, ocr_texts=ocr_texts,
    )
    assert final["pages"][0]["status"] == "EMPTY_OUTPUT"
    assert final["pages"][0]["page_pass"] is False
    assert final["selection_result"]["selection_result"] == "NO_SELECTION"
    validate_evidence(
        final, expected_calibration_ids=CAL, acceptance_ids=ACC,
        expected_candidate_ids={"tesseract-v1"},
        expected_dataset_hash=pending_result["dataset_hash"],
        expected_gold_hash=pending_result["gold_hash"], ocr_texts=ocr_texts,
    )


def test_yomitoku_candidate_propagates_through_synthetic_gate1_e2e(monkeypatch, tmp_path):
    run_id = "G1-YOMITOKU-SYNTHETIC-001"
    manifest, matrix, gold_dir = _runner_fixture(tmp_path, run_id)
    matrix["candidates"][0] = {
        "candidate_id": "yomitoku-0.13.1-cpu-lite-fixed-v1",
        "engine": "yomitoku", "engine_version": "0.13.1",
        "routing_profile_set": {
            "ja_vertical": {"reading_order": "right2left", "device": "cpu", "mode": "lite"},
            "ja_horizontal": {"reading_order": "auto", "device": "cpu", "mode": "lite"},
            "en_horizontal": {"reading_order": "auto", "device": "cpu", "mode": "lite"},
        },
    }
    commands = []

    class Result:
        returncode = 0
        stdout = b'{"text":"synthetic"}'
        stderr = b""

    def run(command, **_kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr("tools.run_gate1.subprocess.run", run)
    monkeypatch.setattr("tools.run_gate1.subprocess.check_output", lambda *args, **kwargs: "a" * 40)
    pending_result = execute(
        manifest, matrix, gold_dir, tmp_path / run_id / "formal", 120, run_id,
        {"run_id": run_id, "runtime": "synthetic", "device": "cpu"},
    )
    assert len(commands) == 10
    assert all(command[-2:] == ["--candidate-id", "yomitoku-0.13.1-cpu-lite-fixed-v1"]
               for command in commands)
    reviewed = review(pending_result)
    gold_texts = {page_id: "synthetic" for page_id in CAL}
    ocr_texts = {("yomitoku-0.13.1-cpu-lite-fixed-v1", page_id): "synthetic" for page_id in CAL}
    final = finalize_evidence(pending_result, reviewed, gold_texts=gold_texts, ocr_texts=ocr_texts)
    validate_evidence(
        final, expected_calibration_ids=CAL, acceptance_ids=ACC,
        expected_candidate_ids={"yomitoku-0.13.1-cpu-lite-fixed-v1"},
        expected_dataset_hash=pending_result["dataset_hash"],
        expected_gold_hash=pending_result["gold_hash"], ocr_texts=ocr_texts,
    )
    assert schema_accepts(final, tmp_path)
    assert final["selection_result"]["candidate_id"] == "yomitoku-0.13.1-cpu-lite-fixed-v1"


def test_yomitoku_runner_timeout_maps_to_existing_taxonomy(monkeypatch, tmp_path):
    run_id = "G1-YOMITOKU-TIMEOUT-001"
    manifest, matrix, gold_dir = _runner_fixture(tmp_path, run_id)
    matrix["candidates"][0].update({
        "candidate_id": "yomitoku-0.13.1-cpu-lite-fixed-v1",
        "engine": "yomitoku", "engine_version": "0.13.1",
    })
    monkeypatch.setattr(
        "tools.run_gate1.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("worker", 120)),
    )
    monkeypatch.setattr("tools.run_gate1.subprocess.check_output", lambda *args, **kwargs: "a" * 40)
    result = execute(
        manifest, matrix, gold_dir, tmp_path / run_id / "formal", 120, run_id,
        {"run_id": run_id, "runtime": "synthetic", "device": "cpu"},
    )
    assert {record["status"] for record in result["pages"]} == {"TIMEOUT"}


def test_runner_rejects_candidate_engine_mismatch(tmp_path):
    manifest, matrix, gold_dir = _runner_fixture(tmp_path, "G1-MISMATCH-001")
    matrix["candidates"][0].update({"candidate_id": "yomitoku-0.13.1-cpu-lite-fixed-v1",
                                     "engine": "tesseract"})
    with pytest.raises(ValueError, match="candidate ID and engine identity mismatch"):
        execute(manifest, matrix, gold_dir, tmp_path / "formal", 120, "G1-MISMATCH-001",
                {"run_id": "G1-MISMATCH-001", "runtime": "synthetic"})


def test_runner_rejects_manifest_and_environment_run_id_mismatch(tmp_path):
    manifest, matrix, gold = _runner_fixture(tmp_path)
    bad_manifest = dict(manifest); bad_manifest["run_id"] = "wrong"
    with pytest.raises(ValueError, match="manifest run ID mismatch"):
        build_plan(bad_manifest, matrix, gold, tmp_path / "formal", 120, "G1-TEST-001")
    with pytest.raises(ValueError, match="environment record run ID mismatch"):
        execute(manifest, matrix, gold, tmp_path / "formal", 120, "G1-TEST-001",
                {"run_id": "wrong"})


def test_runner_does_not_overwrite_colliding_output(tmp_path):
    manifest, matrix, gold = _runner_fixture(tmp_path)
    output = tmp_path / "G1-TEST-001" / "formal"
    output.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        execute(manifest, matrix, gold, output, 120, "G1-TEST-001",
                {"run_id": "G1-TEST-001"})


def test_finalizer_preserves_pending_run_id():
    p = pending(); p["run_id"] = "G1-TEST-001"
    r = review(p)
    gold = {page_id: "日本語" for page_id in CAL}
    ocr = {("tesseract-v1", page_id): "日本語" for page_id in CAL}
    assert finalize_evidence(p, r, gold_texts=gold, ocr_texts=ocr)["run_id"] == "G1-TEST-001"
