"""Validate local-only Gate 1 evidence without reading source images or gold text."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.gate1 import Gate1ValidationError, validate_evidence


def _ocr_text(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = payload.get("text")
    if not isinstance(text, str):
        raise Gate1ValidationError(f"OCR output has no text: {path}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--calibration-ids", required=True)
    parser.add_argument("--acceptance-ids", required=True)
    parser.add_argument("--candidate-ids", required=True)
    parser.add_argument("--dataset-hash")
    parser.add_argument("--gold-hash")
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        ocr_texts = {
            (page["candidate_id"], page["input_id"]):
                _ocr_text(Path(page["ocr_output_reference"]))
            for page in evidence["pages"] if page["status"] in {"SUCCESS", "EMPTY_OUTPUT"}
        }
        validate_evidence(
            evidence,
            expected_calibration_ids=set(args.calibration_ids.split(",")),
            acceptance_ids=set(args.acceptance_ids.split(",")),
            expected_candidate_ids=set(args.candidate_ids.split(",")),
            expected_dataset_hash=args.dataset_hash,
            expected_gold_hash=args.gold_hash,
            ocr_texts=ocr_texts,
        )
    except (OSError, json.JSONDecodeError, Gate1ValidationError, KeyError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
