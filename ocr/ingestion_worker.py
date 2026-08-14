"""Independent one-shot capture session ingestion CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch import SessionOcrBatch
from .engine_factory import create_candidate
from .figures import FigurePersistenceOptions
from .ingestion import IngestionWorker
from .page_ocr import PageOcrProcessor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process completed capture sessions once")
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument(
        "--candidate-id", required=True,
        help="explicit existing candidate identity; this worker never selects a default",
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--figure-storage-root", type=Path,
                        help="explicitly enable existing figure persistence")
    parser.add_argument("--allow-legacy-finalized", action="store_true")
    parser.add_argument("--stale-claim-seconds", type=float, default=86400)
    args = parser.parse_args(argv)
    if args.stale_claim_seconds <= 0:
        parser.error("--stale-claim-seconds must be positive")

    config, engine = create_candidate(args.candidate_id, manifest_path=args.manifest)
    figure_options = FigurePersistenceOptions(
        enabled=args.figure_storage_root is not None,
        storage_root=args.figure_storage_root,
        candidate_id=args.candidate_id if args.figure_storage_root is not None else "",
    )
    processor = PageOcrProcessor(config, engine, figure_options=figure_options)
    worker = IngestionWorker(
        args.capture_root, SessionOcrBatch(processor, config),
        stale_after_seconds=args.stale_claim_seconds,
        allow_legacy_finalized=args.allow_legacy_finalized,
    )
    outcomes = worker.scan_once()
    print(json.dumps([outcome.__dict__ for outcome in outcomes], ensure_ascii=False, indent=2))
    if any(outcome.state == "FAILED_TERMINAL" for outcome in outcomes):
        return 2
    if any(outcome.state == "FAILED_RETRYABLE" for outcome in outcomes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
