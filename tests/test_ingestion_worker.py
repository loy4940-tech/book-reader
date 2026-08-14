"""Synthetic capture-session ingestion tests; no Acceptance or actual OCR data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
from threading import Barrier, Thread

from PIL import Image
import pytest

from ocr.figures import FigurePersistenceOptions
from ocr.ingestion import (
    CLAIM_FILE, COMPLETION_FILE, STATE_FILE, ClaimDeniedError, IngestionState,
    IngestionWorker, ReadinessKind, acquire_claim, discover_sessions, load_worker_state,
    release_claim, validate_session,
)


@dataclass(frozen=True)
class Result:
    metadata_success_count: int = 1
    record_count: int = 1
    processed_count: int = 1
    skipped_count: int = 0
    duplicate_count: int = 0
    blank_count: int = 0
    retry_count: int = 0


class Batch:
    def __init__(self, error: Exception | None = None):
        self.calls: list[Path] = []
        self.error = error

    def run(self, path):
        self.calls.append(Path(path))
        if self.error:
            raise self.error
        return Result()


def _session(
    root: Path, name: str = "session-A", *, complete: bool = True,
    success: bool = True, malformed: bool = False,
) -> Path:
    session = root / name
    images = session / "images"
    images.mkdir(parents=True)
    image_path = images / "capture_001.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    metadata = {
        "session_id": f"sid-{name}", "started_at": "2026-08-14T10:00:00+09:00",
        "finished_at": "2026-08-14T10:01:00+09:00" if complete else None,
        "captures": [{
            "index": 1, "captured_at": "2026-08-14T10:00:30+09:00",
            "status": "success" if success else "capture_failed",
            "image_path": str(image_path), "window_title": "Synthetic Reader",
        }],
    }
    path = session / "metadata.json"
    path.write_text("{" if malformed else json.dumps(metadata), encoding="utf-8")
    if complete:
        (session / COMPLETION_FILE).write_text(json.dumps({
            "schema_version": 1, "session_id": metadata["session_id"],
            "completed_at": metadata["finished_at"],
        }), encoding="utf-8")
    return session


def test_completed_session_discovery_and_readiness(tmp_path):
    session = _session(tmp_path)
    (tmp_path / "unrelated").mkdir()
    assert discover_sessions(tmp_path) == [session]
    result = validate_session(session, tmp_path)
    assert result.kind is ReadinessKind.READY and result.success_count == 1


def test_incomplete_and_malformed_unfinalized_sessions_are_not_ready(tmp_path):
    incomplete = _session(tmp_path, "incomplete", complete=False)
    malformed = _session(tmp_path, "writing", complete=False, malformed=True)
    assert validate_session(incomplete, tmp_path).kind is ReadinessKind.NOT_READY
    assert validate_session(malformed, tmp_path).kind is ReadinessKind.NOT_READY


def test_finalized_malformed_and_zero_success_are_terminal(tmp_path):
    malformed = _session(tmp_path, "malformed", malformed=True)
    empty = _session(tmp_path, "empty", success=False)
    assert validate_session(malformed, tmp_path).kind is ReadinessKind.TERMINAL
    result = validate_session(empty, tmp_path)
    assert result.kind is ReadinessKind.TERMINAL
    assert result.reason == "success_capture_empty"


def test_failed_capture_is_ignored_when_success_exists(tmp_path):
    session = _session(tmp_path)
    metadata_path = session / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["captures"].append({"index": 2, "status": "capture_failed", "image_path": None})
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert validate_session(session, tmp_path).kind is ReadinessKind.READY


def test_missing_success_image_is_terminal(tmp_path):
    session = _session(tmp_path)
    next((session / "images").iterdir()).unlink()
    result = validate_session(session, tmp_path)
    assert result.kind is ReadinessKind.TERMINAL
    assert result.reason == "success_image_missing"


@pytest.mark.parametrize("raw", ["../outside.png", "C:/outside.png"])
def test_image_path_escape_is_terminal(tmp_path, raw):
    session = _session(tmp_path)
    metadata_path = session / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["captures"][0]["image_path"] = raw
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert validate_session(session, tmp_path).kind is ReadinessKind.TERMINAL


def test_atomic_claim_and_duplicate_denial(tmp_path):
    session = _session(tmp_path)
    claim = acquire_claim(session, "sid-session-A", worker_id="one")
    with pytest.raises(ClaimDeniedError):
        acquire_claim(session, "sid-session-A", worker_id="two")
    release_claim(session, claim)
    assert not (session / CLAIM_FILE).exists()


def test_concurrent_claim_exactly_one_succeeds(tmp_path):
    session = _session(tmp_path)
    barrier = Barrier(2)
    results = []

    def contender(name):
        barrier.wait()
        try:
            results.append((name, acquire_claim(session, "sid-session-A", worker_id=name)))
        except ClaimDeniedError:
            results.append((name, None))

    threads = [Thread(target=contender, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    winners = [claim for _, claim in results if claim is not None]
    assert len(winners) == 1
    release_claim(session, winners[0])


def test_stale_same_host_dead_pid_claim_is_recovered_with_audit(tmp_path):
    session = _session(tmp_path)
    old = {
        "session_id": "sid-session-A", "worker_id": "crashed", "pid": 99999999,
        "hostname": socket.gethostname(),
        "claimed_at": (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
        "state": "PROCESSING",
    }
    (session / CLAIM_FILE).write_text(json.dumps(old), encoding="utf-8")
    claim = acquire_claim(session, "sid-session-A", worker_id="recovery", stale_after_seconds=1.0)
    audits = list(session.glob(f"{CLAIM_FILE}.stale.*.json"))
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    # Stale reason depends on pid check result (may be same_host_pid_not_running or owner_unverifiable_and_claim_expired)
    assert audit["stale_reason"] in ("same_host_pid_not_running", "owner_unverifiable_and_claim_expired")
    release_claim(session, claim)


def test_worker_handoff_completion_and_no_reprocessing(tmp_path):
    session = _session(tmp_path)
    batch = Batch()
    worker = IngestionWorker(tmp_path, batch, worker_id="worker")
    first = worker.process(session)
    second = worker.process(session)
    assert first.state == IngestionState.COMPLETED.value
    assert second.reason == "terminal_state_already_recorded"
    assert batch.calls == [session]
    assert load_worker_state(session)["batch_result"]["record_count"] == 1


def test_retryable_failure_can_resume(tmp_path):
    session = _session(tmp_path)
    batch = Batch(OSError("temporary lock"))
    worker = IngestionWorker(tmp_path, batch, worker_id="worker")
    assert worker.process(session).state == IngestionState.FAILED_RETRYABLE.value
    batch.error = None
    assert worker.process(session).state == IngestionState.COMPLETED.value
    assert len(batch.calls) == 2


def test_terminal_failure_is_persisted_and_not_reprocessed(tmp_path):
    session = _session(tmp_path, success=False)
    batch = Batch()
    worker = IngestionWorker(tmp_path, batch, worker_id="worker")
    first = worker.process(session)
    second = worker.process(session)
    assert first.state == second.state == IngestionState.FAILED_TERMINAL.value
    assert batch.calls == []


def test_simulated_crash_claim_recovery_reaches_batch(tmp_path):
    session = _session(tmp_path)
    (session / CLAIM_FILE).write_text(json.dumps({
        "session_id": "sid-session-A", "worker_id": "dead", "pid": 99999999,
        "hostname": socket.gethostname(),
        "claimed_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "state": "PROCESSING",
    }), encoding="utf-8")
    batch = Batch()
    outcome = IngestionWorker(tmp_path, batch, worker_id="replacement", stale_after_seconds=0.5).process(session)
    assert outcome.state == IngestionState.COMPLETED.value
    assert batch.calls == [session]


def test_legacy_session_requires_explicit_opt_in(tmp_path):
    session = _session(tmp_path)
    (session / COMPLETION_FILE).unlink()
    assert validate_session(session, tmp_path).kind is ReadinessKind.NOT_READY
    assert validate_session(session, tmp_path, allow_legacy_finalized=True).kind is ReadinessKind.READY


def test_figure_persistence_remains_default_off():
    assert FigurePersistenceOptions().enabled is False


def test_scan_once_full_integration_discovery_to_completion(tmp_path):
    """Verify complete integration: discovery → validation → claim → batch → state."""
    session1 = _session(tmp_path, "session-ready", complete=True)
    session2 = _session(tmp_path, "session-incomplete", complete=False)
    batch = Batch()

    worker = IngestionWorker(tmp_path, batch, worker_id="test-worker")
    outcomes = worker.scan_once()

    # Only ready session should be processed
    assert len(outcomes) == 2
    ready_outcome = next(o for o in outcomes if o.session_id == "sid-session-ready")
    incomplete_outcome = next(o for o in outcomes if o.session_id == "sid-session-incomplete")

    assert ready_outcome.state == IngestionState.COMPLETED.value
    assert incomplete_outcome.state == IngestionState.NOT_READY.value

    assert len(batch.calls) == 1
    assert batch.calls[0] == session1

    # Verify state persistence
    state = load_worker_state(session1)
    assert state["state"] == IngestionState.COMPLETED.value
    assert state["batch_result"]["record_count"] == 1

    # Subsequent scan should skip completed session
    batch.calls.clear()
    outcomes2 = worker.scan_once()
    assert len(batch.calls) == 0


def test_batch_failure_terminal_state_prevents_reprocessing(tmp_path):
    """Verify that terminal batch failure prevents future processing."""
    session = _session(tmp_path)

    class TerminalBatch:
        def __init__(self):
            self.calls: list[Path] = []
        def run(self, path):
            self.calls.append(path)
            from ocr.batch import OcrBatchError
            raise OcrBatchError("corrupt metadata")

    batch = TerminalBatch()
    # Mark OcrBatchError as terminal (not retryable by default)
    def is_terminal(exc):
        from ocr.batch import OcrBatchError
        return isinstance(exc, OcrBatchError)

    worker = IngestionWorker(
        tmp_path, batch, worker_id="test",
        retryable_exception=lambda e: not is_terminal(e)
    )

    outcome = worker.process(session)
    assert outcome.state == IngestionState.FAILED_TERMINAL.value

    # Verify state was persisted
    state = load_worker_state(session)
    assert state["state"] == IngestionState.FAILED_TERMINAL.value

    # Subsequent attempt should not reprocess
    batch.calls.clear()
    outcome2 = worker.process(session)
    assert outcome2.state == IngestionState.FAILED_TERMINAL.value
    assert len(batch.calls) == 0


def test_incomplete_session_skipped_by_scan_once(tmp_path):
    """Verify incomplete sessions are skipped."""
    incomplete = _session(tmp_path, "incomplete", complete=False)
    ready = _session(tmp_path, "ready", complete=True)

    batch = Batch()
    worker = IngestionWorker(tmp_path, batch, worker_id="test")
    outcomes = worker.scan_once()

    assert len(outcomes) == 2
    incomplete_outcome = next(o for o in outcomes if o.session_id == "sid-incomplete")
    ready_outcome = next(o for o in outcomes if o.session_id == "sid-ready")

    assert incomplete_outcome.state == IngestionState.NOT_READY.value
    assert ready_outcome.state == IngestionState.COMPLETED.value
    assert len(batch.calls) == 1


def test_ingestion_worker_cli_integration_with_mock_batch(tmp_path, monkeypatch):
    """Verify CLI entry point works: discovery → validation → batch → exit code."""
    # Create synthetic session
    session = _session(tmp_path, "ready", complete=True)

    # Patch create_candidate to avoid requiring real OCR engine
    from unittest.mock import MagicMock
    mock_config = MagicMock()
    mock_engine = MagicMock()

    def mock_create_candidate(candidate_id, manifest_path=None):
        return mock_config, mock_engine

    monkeypatch.setattr("ocr.ingestion_worker.create_candidate", mock_create_candidate)

    # Patch PageOcrProcessor
    mock_processor = MagicMock()
    monkeypatch.setattr("ocr.ingestion_worker.PageOcrProcessor", lambda *args, **kwargs: mock_processor)

    # Patch SessionOcrBatch to use Batch mock
    original_batch_class = None
    def mock_batch_init(self, processor, config):
        self.processor = processor
        self.config = config
        self.calls = []
    def mock_batch_run(self, path):
        self.calls.append(Path(path))
        return Result()

    monkeypatch.setattr("ocr.ingestion_worker.SessionOcrBatch.__init__", mock_batch_init)
    monkeypatch.setattr("ocr.ingestion_worker.SessionOcrBatch.run", mock_batch_run)

    # Call main() with capture_root and candidate_id
    from ocr.ingestion_worker import main
    exit_code = main([
        "--capture-root", str(tmp_path),
        "--candidate-id", "test-mock",
    ])

    # Verify exit code (0 = success, 1 = retryable failure, 2 = terminal failure)
    assert exit_code == 0


def test_output_generation_failure_prevents_completion(tmp_path, monkeypatch):
    """TEST-FIX-01: Output generation failure doesn't mark session as COMPLETED."""
    import json
    from ocr import output as output_module
    from unittest.mock import MagicMock

    # Create session with OCR results
    session = _session(tmp_path, "session-with-ocr", complete=True)

    # Create ocr.json to trigger output generation
    ocr_json = session / "ocr.json"
    ocr_json.write_text(json.dumps({"pages": []}))

    # Mock output generation to fail
    def mock_generate_text_files(path):
        raise RuntimeError("Failed to write text files")

    monkeypatch.setattr(output_module, "generate_text_files", mock_generate_text_files)

    # Also mock batch to actually create ocr.json (since store initialization can fail)
    class OcrBatch:
        def __init__(self):
            self.calls = []

        def run(self, path):
            self.calls.append(Path(path))
            # Simulate successful OCR batch result
            return Result()

    batch = OcrBatch()
    worker = IngestionWorker(tmp_path, batch, worker_id="test")

    outcome = worker.process(session)

    # Session should NOT be COMPLETED; should be FAILED (retryable or terminal)
    assert outcome.state in (IngestionState.FAILED_RETRYABLE.value, IngestionState.FAILED_TERMINAL.value)
    assert outcome.state != IngestionState.COMPLETED.value

    # Verify state was persisted
    state = load_worker_state(session)
    assert state["state"] in (IngestionState.FAILED_RETRYABLE.value, IngestionState.FAILED_TERMINAL.value)


def test_output_failure_observable_in_worker_outcome(tmp_path, monkeypatch):
    """TEST-FIX-02: Output generation failure is observable in WorkerOutcome."""
    import json
    from pathlib import Path
    from ocr import output as output_module

    session = _session(tmp_path, "session-output-fail", complete=True)
    ocr_json = session / "ocr.json"
    ocr_json.write_text(json.dumps({"pages": []}))

    def mock_generate_markdown(path):
        raise ValueError("Bad markdown format")

    monkeypatch.setattr(output_module, "generate_markdown", mock_generate_markdown)

    class OcrBatch:
        def __init__(self):
            self.calls = []

        def run(self, path):
            self.calls.append(Path(path))
            return Result()

    batch = OcrBatch()
    worker = IngestionWorker(tmp_path, batch, worker_id="test")
    outcome = worker.process(session)

    # Failure should be observable - state must NOT be COMPLETED
    assert outcome.state in (IngestionState.FAILED_RETRYABLE.value, IngestionState.FAILED_TERMINAL.value)
    assert outcome.state != IngestionState.COMPLETED.value


def test_normal_completion_without_output_generation(tmp_path):
    """TEST-FIX-04: Normal COMPLETED state when no output generation needed."""
    from pathlib import Path

    # Create session without ocr.json (so output generation is skipped)
    session = _session(tmp_path, "session-no-output", complete=True)

    class OcrBatch:
        def __init__(self):
            self.calls = []

        def run(self, path):
            self.calls.append(Path(path))
            return Result()

    batch = OcrBatch()
    worker = IngestionWorker(tmp_path, batch, worker_id="test")
    outcome = worker.process(session)

    # Should complete normally when no output generation is needed
    # (output generation only happens if ocr.json exists)
    assert outcome.state == IngestionState.COMPLETED.value
