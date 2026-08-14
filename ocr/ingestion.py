"""Safe filesystem handoff for completed capture sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Any, Callable
from uuid import uuid4

from logger_setup import setup_logger


logger = setup_logger("book_reader.ingestion")

COMPLETION_FILE = ".capture_complete.json"
CLAIM_FILE = ".bookreader_claim.json"
STATE_FILE = ".bookreader_ingestion.json"
SCHEMA_VERSION = 1


class IngestionState(str, Enum):
    DISCOVERED = "DISCOVERED"
    NOT_READY = "NOT_READY"
    CLAIMED = "CLAIMED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class ReadinessKind(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    TERMINAL = "TERMINAL"


class ClaimDeniedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadinessResult:
    kind: ReadinessKind
    session_id: str
    reason: str
    success_count: int = 0


@dataclass(frozen=True)
class Claim:
    session_id: str
    worker_id: str
    pid: int
    hostname: str
    claimed_at: str
    state: str = IngestionState.CLAIMED.value


@dataclass(frozen=True)
class WorkerOutcome:
    session: str
    session_id: str
    state: str
    reason: str
    batch_result: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=f".{path.name}.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish a complete JSON file without replacing an existing owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=f".{path.name}.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        Path(temporary).unlink()
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def discover_sessions(capture_root: str | Path) -> list[Path]:
    root = Path(capture_root)
    if not root.is_dir():
        return []
    return sorted(
        (item for item in root.iterdir() if item.is_dir() and (item / "metadata.json").exists()),
        key=lambda item: item.name,
    )


def validate_session(
    session: str | Path, capture_root: str | Path, *, allow_legacy_finalized: bool = False,
) -> ReadinessResult:
    root = Path(capture_root).resolve()
    session_path = Path(session).resolve()
    name = session_path.name
    if not _inside(session_path, root) or session_path == root:
        return ReadinessResult(ReadinessKind.TERMINAL, name, "session_path_escape")
    marker_path = session_path / COMPLETION_FILE
    metadata_path = session_path / "metadata.json"
    if not metadata_path.is_file():
        return ReadinessResult(ReadinessKind.NOT_READY, name, "metadata_missing")

    marker: dict[str, Any] | None = None
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ReadinessResult(ReadinessKind.TERMINAL, name, "completion_marker_invalid")
        if not isinstance(marker, dict) or marker.get("schema_version") != SCHEMA_VERSION:
            return ReadinessResult(ReadinessKind.TERMINAL, name, "completion_marker_invalid")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        kind = ReadinessKind.TERMINAL if marker is not None else ReadinessKind.NOT_READY
        return ReadinessResult(kind, name, "metadata_invalid")
    if not isinstance(metadata, dict):
        kind = ReadinessKind.TERMINAL if marker is not None else ReadinessKind.NOT_READY
        return ReadinessResult(kind, name, "metadata_invalid")
    session_id = metadata.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        kind = ReadinessKind.TERMINAL if marker is not None else ReadinessKind.NOT_READY
        return ReadinessResult(kind, name, "session_id_invalid")
    if marker is None:
        if not (allow_legacy_finalized and metadata.get("finished_at")):
            return ReadinessResult(ReadinessKind.NOT_READY, session_id, "completion_signal_missing")
    elif marker.get("session_id") != session_id:
        return ReadinessResult(ReadinessKind.TERMINAL, session_id, "completion_identity_mismatch")
    if not metadata.get("finished_at"):
        return ReadinessResult(ReadinessKind.TERMINAL, session_id, "finished_at_missing")
    captures = metadata.get("captures")
    if not isinstance(captures, list):
        return ReadinessResult(ReadinessKind.TERMINAL, session_id, "captures_invalid")

    successes = []
    for capture in captures:
        if not isinstance(capture, dict) or not isinstance(capture.get("status"), str):
            return ReadinessResult(ReadinessKind.TERMINAL, session_id, "capture_record_invalid")
        if capture["status"] != "success":
            continue
        raw = capture.get("image_path")
        if not isinstance(raw, str) or not raw:
            return ReadinessResult(ReadinessKind.TERMINAL, session_id, "success_image_path_invalid")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = session_path / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return ReadinessResult(ReadinessKind.TERMINAL, session_id, "success_image_missing")
        if not _inside(resolved, session_path):
            return ReadinessResult(ReadinessKind.TERMINAL, session_id, "success_image_path_escape")
        if not resolved.is_file() or resolved.suffix.lower() != ".png":
            return ReadinessResult(ReadinessKind.TERMINAL, session_id, "success_image_invalid")
        successes.append(resolved)
    if not successes:
        return ReadinessResult(ReadinessKind.TERMINAL, session_id, "success_capture_empty")
    return ReadinessResult(ReadinessKind.READY, session_id, "ready", len(successes))


def _pid_alive(pid: Any) -> bool | None:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _claim_staleness(claim: dict[str, Any], stale_after_seconds: float) -> tuple[bool, str]:
    claimed = _parse_time(claim.get("claimed_at"))
    age = ((datetime.now(timezone.utc) - claimed).total_seconds() if claimed else None)
    if claim.get("hostname") == socket.gethostname():
        alive = _pid_alive(claim.get("pid"))
        if alive is False:
            return True, "same_host_pid_not_running"
        if alive is True:
            return False, "same_host_pid_running"
    if age is not None and age >= stale_after_seconds:
        return True, "owner_unverifiable_and_claim_expired"
    return False, "owner_unverifiable_claim_not_expired"


def acquire_claim(
    session: str | Path, session_id: str, *, worker_id: str | None = None,
    stale_after_seconds: float = 86400,
) -> Claim:
    path = Path(session) / CLAIM_FILE
    owner = Claim(
        session_id=session_id, worker_id=worker_id or uuid4().hex, pid=os.getpid(),
        hostname=socket.gethostname(), claimed_at=_now(),
    )
    try:
        _exclusive_json(path, asdict(owner))
        return owner
    except FileExistsError:
        pass
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimDeniedError("existing claim is unreadable") from exc
    stale, reason = _claim_staleness(existing, stale_after_seconds)
    if not stale:
        raise ClaimDeniedError(reason)
    audit = path.with_name(f"{CLAIM_FILE}.stale.{owner.worker_id}.json")
    try:
        os.replace(path, audit)
    except FileNotFoundError as exc:
        raise ClaimDeniedError("claim changed during stale recovery") from exc
    existing["recovered_at"] = _now()
    existing["recovered_by"] = owner.worker_id
    existing["stale_reason"] = reason
    _atomic_json(audit, existing)
    try:
        _exclusive_json(path, asdict(owner))
    except FileExistsError as exc:
        raise ClaimDeniedError("another worker acquired recovered claim") from exc
    return owner


def release_claim(session: str | Path, claim: Claim) -> None:
    path = Path(session) / CLAIM_FILE
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimDeniedError("cannot verify claim ownership for release") from exc
    if current.get("worker_id") != claim.worker_id:
        raise ClaimDeniedError("cannot release another worker's claim")
    path.unlink()


def load_worker_state(session: str | Path) -> dict[str, Any] | None:
    path = Path(session) / STATE_FILE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("worker state is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("worker state has unsupported schema")
    return value


def write_worker_state(
    session: str | Path, session_id: str, state: IngestionState, *,
    worker_id: str | None = None, reason: str = "", error: BaseException | None = None,
    batch_result: dict[str, Any] | None = None,
) -> None:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "session_id": session_id,
        "state": state.value, "updated_at": _now(), "worker_id": worker_id,
        "reason": reason, "batch_result": batch_result,
    }
    if error is not None:
        record["error"] = {
            "timestamp": _now(), "stage": "session_batch", "type": type(error).__name__,
            "code": reason or "batch_failure", "message": str(error)[:500],
            "retryable": state is IngestionState.FAILED_RETRYABLE,
        }
    _atomic_json(Path(session) / STATE_FILE, record)


class IngestionWorker:
    def __init__(
        self, capture_root: str | Path, batch: Any, *, worker_id: str | None = None,
        stale_after_seconds: float = 86400, allow_legacy_finalized: bool = False,
        retryable_exception: Callable[[BaseException], bool] | None = None,
    ) -> None:
        self.capture_root = Path(capture_root)
        self.batch = batch
        self.worker_id = worker_id or uuid4().hex
        self.stale_after_seconds = stale_after_seconds
        self.allow_legacy_finalized = allow_legacy_finalized
        self.retryable_exception = retryable_exception or (lambda _error: True)

    def process(self, session: str | Path) -> WorkerOutcome:
        session_path = Path(session)
        existing = load_worker_state(session_path)
        if existing and existing.get("state") in {
            IngestionState.COMPLETED.value, IngestionState.FAILED_TERMINAL.value,
        }:
            return WorkerOutcome(
                str(session_path), str(existing.get("session_id", session_path.name)),
                existing["state"], "terminal_state_already_recorded",
                existing.get("batch_result"),
            )
        readiness = validate_session(
            session_path, self.capture_root,
            allow_legacy_finalized=self.allow_legacy_finalized,
        )
        logger.info("session readiness: session=%s result=%s reason=%s", session_path.name,
                    readiness.kind.value, readiness.reason)
        if readiness.kind is ReadinessKind.NOT_READY:
            return WorkerOutcome(str(session_path), readiness.session_id,
                                 IngestionState.NOT_READY.value, readiness.reason)
        try:
            claim = acquire_claim(
                session_path, readiness.session_id, worker_id=self.worker_id,
                stale_after_seconds=self.stale_after_seconds,
            )
        except ClaimDeniedError as exc:
            logger.info("session claim denied: session=%s reason=%s", session_path.name, exc)
            return WorkerOutcome(str(session_path), readiness.session_id,
                                 IngestionState.NOT_READY.value, f"claim_denied:{exc}")
        try:
            if readiness.kind is ReadinessKind.TERMINAL:
                write_worker_state(
                    session_path, readiness.session_id, IngestionState.FAILED_TERMINAL,
                    worker_id=claim.worker_id, reason=readiness.reason,
                )
                return WorkerOutcome(str(session_path), readiness.session_id,
                                     IngestionState.FAILED_TERMINAL.value, readiness.reason)
            write_worker_state(session_path, readiness.session_id, IngestionState.CLAIMED,
                               worker_id=claim.worker_id, reason="claim_acquired")
            write_worker_state(session_path, readiness.session_id, IngestionState.PROCESSING,
                               worker_id=claim.worker_id, reason="batch_started")
            logger.info("session processing started: session=%s", readiness.session_id)
            result = self.batch.run(session_path)
            payload = asdict(result) if hasattr(result, "__dataclass_fields__") else dict(result)

            if (Path(session_path) / "ocr.json").is_file():
                from .output import generate_json_output, generate_markdown, generate_text_files

                try:
                    generate_text_files(session_path)
                    generate_markdown(session_path)
                    generate_json_output(session_path)
                    logger.info("session output generated: session=%s", readiness.session_id)
                except Exception as output_exc:
                    logger.warning("output generation failed: session=%s error=%s",
                                   readiness.session_id, output_exc)

            write_worker_state(
                session_path, readiness.session_id, IngestionState.COMPLETED,
                worker_id=claim.worker_id, reason="batch_completed", batch_result=payload,
            )
            logger.info("session processing completed: session=%s", readiness.session_id)
            return WorkerOutcome(str(session_path), readiness.session_id,
                                 IngestionState.COMPLETED.value, "batch_completed", payload)
        except Exception as exc:
            retryable = self.retryable_exception(exc)
            state = IngestionState.FAILED_RETRYABLE if retryable else IngestionState.FAILED_TERMINAL
            write_worker_state(
                session_path, readiness.session_id, state, worker_id=claim.worker_id,
                reason="batch_failure", error=exc,
            )
            logger.warning("session processing failed: session=%s retryable=%s type=%s",
                           readiness.session_id, retryable, type(exc).__name__)
            return WorkerOutcome(str(session_path), readiness.session_id, state.value,
                                 "batch_failure")
        finally:
            release_claim(session_path, claim)

    def scan_once(self) -> list[WorkerOutcome]:
        sessions = discover_sessions(self.capture_root)
        logger.info("capture sessions discovered: count=%d", len(sessions))
        return [self.process(session) for session in sessions]
