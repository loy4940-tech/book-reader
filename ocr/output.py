"""Phase 9: Output generation from OCR results."""

import json
import re
from pathlib import Path
from typing import Any

from .store import load_store


class OutputGenerationError(RuntimeError):
    """Raised when output cannot be generated."""


def _extract_page_number(filename: str) -> int:
    """Extract numeric page number from filename (e.g., 'page_001.png' → 1, 'capture_003.png' → 3)."""
    match = re.search(r'(\d+)', filename)
    if match:
        return int(match.group(1))
    raise OutputGenerationError(f"Cannot extract page number from: {filename}")


def generate_text_files(
    session_dir: str | Path,
    *,
    ocr_data_name: str = "ocr.json",
    output_dir_name: str = "text",
) -> int:
    """Generate per-page text files.

    Args:
        session_dir: Path to session directory containing ocr.json
        ocr_data_name: Name of OCR JSON file
        output_dir_name: Name of output directory to create

    Returns:
        Number of pages written
    """
    root = Path(session_dir)
    store = load_store(root / ocr_data_name)

    output_dir = root / output_dir_name
    output_dir.mkdir(exist_ok=True)

    count = 0
    for record in store["records"]:
        page = record["source_page"]
        text = record["text"]

        page_num = _extract_page_number(page)
        output_file = output_dir / f"page_{page_num:03d}.txt"
        output_file.write_text(text, encoding="utf-8")
        count += 1

    return count


def generate_markdown(
    session_dir: str | Path,
    *,
    ocr_data_name: str = "ocr.json",
    output_name: str = "book.md",
) -> Path:
    """Generate combined markdown with page markers.

    Args:
        session_dir: Path to session directory containing ocr.json
        ocr_data_name: Name of OCR JSON file
        output_name: Name of output markdown file

    Returns:
        Path to generated markdown file
    """
    root = Path(session_dir)
    store = load_store(root / ocr_data_name)

    lines = []
    for record in store["records"]:
        page = record["source_page"]
        text = record["text"]
        language = record.get("classifier", {}).get("language", "unknown")
        orientation = record.get("classifier", {}).get("orientation", "unknown")
        status = record.get("status", "unknown")

        page_num = _extract_page_number(page)
        marker = f"<!-- page: {page_num:03d} | source: {page} | lang: {language} | dir: {orientation} | status: {status} -->"
        lines.append(marker)
        lines.append(text)
        lines.append("")

    output_file = root / output_name
    output_file.write_text("\n".join(lines), encoding="utf-8")
    return output_file


def generate_json_output(
    session_dir: str | Path,
    *,
    ocr_data_name: str = "ocr.json",
) -> Path:
    """Ensure OCR JSON output exists (already created by batch).

    Args:
        session_dir: Path to session directory
        ocr_data_name: Name of OCR JSON file

    Returns:
        Path to JSON file (verifies it exists)
    """
    root = Path(session_dir)
    json_file = root / ocr_data_name
    if not json_file.is_file():
        raise OutputGenerationError(f"OCR JSON not found: {json_file}")
    return json_file


def verify_outputs(
    session_dir: str | Path,
    *,
    ocr_data_name: str = "ocr.json",
    text_dir_name: str = "text",
    markdown_name: str = "book.md",
) -> dict[str, Any]:
    """Verify that all expected output files exist.

    Args:
        session_dir: Path to session directory
        ocr_data_name: Name of OCR JSON file
        text_dir_name: Name of text output directory
        markdown_name: Name of markdown file

    Returns:
        Dictionary with verification results
    """
    root = Path(session_dir)
    result = {
        "json_exists": (root / ocr_data_name).is_file(),
        "markdown_exists": (root / markdown_name).is_file(),
        "text_dir_exists": (root / text_dir_name).is_dir(),
    }

    if result["text_dir_exists"]:
        result["text_files"] = len(list((root / text_dir_name).glob("page_*.txt")))
    else:
        result["text_files"] = 0

    return result
