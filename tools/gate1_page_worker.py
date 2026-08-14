"""Isolated one-page worker used by the explicitly authorized Gate 1 runner."""

import json
import argparse
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.page_ocr import process_page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("page_id")
    parser.add_argument("language")
    parser.add_argument("orientation")
    parser.add_argument("--candidate-id", required=True)
    args = parser.parse_args()
    if args.candidate_id.startswith("yomitoku-"):
        diagnostics = io.StringIO()
        try:
            with contextlib.redirect_stdout(diagnostics):
                record = process_page(
                    args.image, page_id=args.page_id, candidate_id=args.candidate_id,
                    language_override=args.language, orientation_override=args.orientation,
                )
        finally:
            captured = diagnostics.getvalue()
            if captured:
                sys.stderr.write(captured)
    else:
        record = process_page(
            args.image, page_id=args.page_id, candidate_id=args.candidate_id,
            language_override=args.language, orientation_override=args.orientation,
        )
    sys.stdout.write(json.dumps(record.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
