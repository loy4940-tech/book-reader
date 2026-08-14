"""Finalize reviewed Gate 1 pending evidence into canonical final evidence."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.gate1 import Gate1ValidationError, finalize_evidence


def _ocr_text(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = payload.get("text")
    if not isinstance(text, str):
        raise Gate1ValidationError(f"OCR output has no text: {path}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        pending = json.loads(args.pending.read_text(encoding="utf-8"))
        review = json.loads(args.review.read_text(encoding="utf-8"))
        gold = {page["input_id"]: (args.gold / f'{page["input_id"]}.txt').read_text(encoding="utf-8")
                for page in pending["pages"]}
        ocr = {(page["candidate_id"], page["input_id"]): _ocr_text(Path(page["ocr_output_reference"]))
               for page in pending["pages"] if page["status"] in {"SUCCESS", "EMPTY_OUTPUT"}}
        final = finalize_evidence(pending, review, gold_texts=gold, ocr_texts=ocr)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, Gate1ValidationError) as exc:
        print(f"FINALIZATION_FAILED: {exc}")
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
