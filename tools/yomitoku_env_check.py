"""Validate the pinned local YomiToku Windows CPU candidate environment."""

import argparse
import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(manifest_path: Path) -> dict:
    import torch
    import yomitoku

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("YomiToku candidate requires Python 3.12")
    if version("yomitoku") != manifest["package_version"]:
        raise RuntimeError("YomiToku package version mismatch")
    if torch.cuda.is_available():
        raise RuntimeError("YomiToku candidate probe must remain CPU-only")
    checked = []
    for item in manifest["model_files"]:
        path = REPO_ROOT / Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["size"] or file_hash(path) != item["sha256"]:
            raise RuntimeError(f"model artifact mismatch: {item['path']}")
        checked.append(item["path"])
    return {
        "schema_version": 1,
        "candidate_id": "yomitoku-0.13.1-cpu-lite-fixed-v1",
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "yomitoku": version("yomitoku"),
        "torch": torch.__version__,
        "cuda_available": False,
        "device": "cpu",
        "mode": "lite",
        "manifest": str(manifest_path),
        "manifest_sha256": file_hash(manifest_path),
        "verified_model_files": checked,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "yomitoku_model_manifest.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.manifest.resolve())
    except Exception as exc:
        print(f"YOMITOKU_ENV_FAILED: {exc}")
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
