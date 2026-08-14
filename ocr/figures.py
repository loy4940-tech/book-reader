"""Figure crop and filesystem persistence independent of canonical OCR text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from PIL import Image, UnidentifiedImageError

from .errors import FigurePersistenceError
from .models import FigureCandidate, PreprocessResult


FIGURE_MANIFEST_SCHEMA_VERSION = 1
FIGURE_EXTRACTION_VERSION = "1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class FigurePersistenceOptions:
    enabled: bool = False
    storage_root: Path | None = None
    candidate_id: str = ""
    extraction_version: str = FIGURE_EXTRACTION_VERSION


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value) or value in {".", ".."}:
        raise FigurePersistenceError(f"unsafe {label}: {value!r}")
    return value


def map_bbox_to_source(
    bbox: tuple[int, int, int, int], preprocessed: PreprocessResult,
) -> tuple[int, int, int, int]:
    """Map the OCR crop coordinate system back to the original source image."""
    x1, y1, x2, y2 = bbox
    output_width, output_height = preprocessed.output_size
    left, top, right, bottom = preprocessed.content_box
    if output_width <= 0 or output_height <= 0:
        raise FigurePersistenceError("invalid OCR input dimensions")
    if not (0 <= x1 < x2 <= output_width and 0 <= y1 < y2 <= output_height):
        raise FigurePersistenceError(f"figure bbox outside OCR input: {bbox!r}")
    crop_width, crop_height = right - left, bottom - top
    # Lower edges floor and upper edges ceil so a future resized preprocessor cannot
    # discard a detected border pixel. Current preprocessing is crop-only.
    source_box = (
        left + (x1 * crop_width) // output_width,
        top + (y1 * crop_height) // output_height,
        left + (x2 * crop_width + output_width - 1) // output_width,
        top + (y2 * crop_height + output_height - 1) // output_height,
    )
    source_width, source_height = preprocessed.original_size
    sx1, sy1, sx2, sy2 = source_box
    if not (0 <= sx1 < sx2 <= source_width and 0 <= sy1 < sy2 <= source_height):
        raise FigurePersistenceError(f"mapped figure bbox outside source: {source_box!r}")
    return source_box


def deterministic_figure_id(
    source_page_sha256: str, bbox: tuple[int, int, int, int], order: int,
    extraction_version: str = FIGURE_EXTRACTION_VERSION,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", source_page_sha256):
        raise FigurePersistenceError("invalid source page SHA-256")
    payload = json.dumps(
        [source_page_sha256, list(bbox), order, extraction_version],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    return "fig-" + hashlib.sha256(payload).hexdigest()


def _png_bytes(image: Image.Image) -> bytes:
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except OSError as exc:
        raise FigurePersistenceError("cannot serialize figure as PNG") from exc


def _atomic_write(path: Path, data: bytes, *, replace: bool) -> None:
    if path.is_symlink():
        raise FigurePersistenceError(f"refusing to replace symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
            temporary = None
        else:
            # Publish without an overwrite race. A hard-link is atomic on the same
            # filesystem (the temp file is deliberately created beside the target).
            os.link(temporary, path)
            Path(temporary).unlink()
            temporary = None
    except FigurePersistenceError:
        raise
    except OSError as exc:
        raise FigurePersistenceError(f"cannot atomically write figure artifact: {path}") from exc
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise FigurePersistenceError(f"refusing manifest symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FigurePersistenceError(f"cannot read figure manifest: {path}") from exc
    validate_figure_manifest(value)
    return value


def validate_figure_manifest(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != FIGURE_MANIFEST_SCHEMA_VERSION:
        raise FigurePersistenceError("unsupported figure manifest")
    required = {
        "page_id", "source_page_sha256", "engine", "engine_version", "candidate_id",
        "extraction_version", "figures",
    }
    if required - set(value):
        raise FigurePersistenceError("figure manifest is missing required fields")
    if not isinstance(value["figures"], list):
        raise FigurePersistenceError("figure manifest figures must be a list")
    identities: set[str] = set()
    paths: set[str] = set()
    for item in value["figures"]:
        if not isinstance(item, dict):
            raise FigurePersistenceError("figure metadata must be an object")
        fields = {
            "figure_id", "page_id", "figure_order", "bbox_x1", "bbox_y1", "bbox_x2",
            "bbox_y2", "relative_path", "mime_type", "width", "height", "sha256",
            "source_page_sha256", "engine", "engine_version", "candidate_id",
            "extraction_version", "created_at",
        }
        if fields - set(item):
            raise FigurePersistenceError("figure metadata is missing required fields")
        figure_id = item["figure_id"]
        if not isinstance(figure_id, str) or figure_id in identities:
            raise FigurePersistenceError("duplicate or invalid figure_id")
        identities.add(figure_id)
        relative = Path(item["relative_path"])
        if relative.is_absolute() or ".." in relative.parts or item["relative_path"] in paths:
            raise FigurePersistenceError("invalid or duplicate figure relative_path")
        paths.add(item["relative_path"])
        bbox = tuple(item[key] for key in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"))
        if any(isinstance(number, bool) or not isinstance(number, int) for number in bbox):
            raise FigurePersistenceError("figure bbox must contain integers")
        if not (0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3]):
            raise FigurePersistenceError("invalid figure bbox")
        if item["width"] != bbox[2] - bbox[0] or item["height"] != bbox[3] - bbox[1]:
            raise FigurePersistenceError("figure dimensions do not match bbox")
        if item["mime_type"] != "image/png":
            raise FigurePersistenceError("figure mime_type must be image/png")
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise FigurePersistenceError("invalid figure SHA-256")


def persist_figures(
    *, source_path: Path, page_id: str, source_page_sha256: str,
    preprocessed: PreprocessResult, figures: Iterable[FigureCandidate],
    engine: str, engine_version: str, options: FigurePersistenceOptions,
) -> dict[str, Any] | None:
    """Persist figure PNGs and a metadata-only manifest; disabled is a strict no-op."""
    if not options.enabled:
        return None
    if options.storage_root is None:
        raise FigurePersistenceError("figure storage_root is required when enabled")
    safe_page = _safe_identifier(page_id, "page_id")
    _safe_identifier(options.extraction_version, "extraction_version")
    root = options.storage_root.resolve()
    page_directory = root / "figures" / safe_page
    if root not in page_directory.resolve().parents:
        raise FigurePersistenceError("figure path escapes storage root")
    manifest_path = page_directory / "figures.manifest.json"
    existing = _read_manifest(manifest_path)
    if existing is not None and (
        existing.get("page_id") != page_id
        or existing.get("source_page_sha256") != source_page_sha256
        or existing.get("extraction_version") != options.extraction_version
    ):
        raise FigurePersistenceError("existing figure manifest identity mismatch")

    try:
        with Image.open(source_path) as opened:
            source = opened.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise FigurePersistenceError(f"cannot read source image: {source_path}") from exc
    if source.size != preprocessed.original_size:
        raise FigurePersistenceError("source image dimensions changed after OCR preprocessing")
    if _sha256_file(source_path) != source_page_sha256:
        raise FigurePersistenceError("source page hash changed before figure persistence")

    old_by_id = {
        item.get("figure_id"): item for item in (existing or {}).get("figures", [])
        if isinstance(item, dict)
    }
    records: list[dict[str, Any]] = []
    newly_created: list[Path] = []
    seen: set[str] = set()
    try:
        for candidate in sorted(figures, key=lambda item: (item.order, item.bbox)):
            source_box = map_bbox_to_source(candidate.bbox, preprocessed)
            figure_id = deterministic_figure_id(
                source_page_sha256, source_box, candidate.order, options.extraction_version,
            )
            if figure_id in seen:
                raise FigurePersistenceError(f"duplicate figure identity: {figure_id}")
            seen.add(figure_id)
            filename = f"{figure_id}.png"
            relative_path = Path("figures") / safe_page / filename
            final_path = root / relative_path
            png = _png_bytes(source.crop(source_box))
            png_hash = _sha256_bytes(png)
            existed = final_path.exists()
            if existed:
                if final_path.is_symlink() or _sha256_file(final_path) != png_hash:
                    raise FigurePersistenceError(f"figure asset hash mismatch: {figure_id}")
            else:
                _atomic_write(final_path, png, replace=False)
                newly_created.append(final_path)
            prior = old_by_id.get(figure_id, {})
            width, height = source_box[2] - source_box[0], source_box[3] - source_box[1]
            records.append({
                "figure_id": figure_id,
                "page_id": page_id,
                "figure_order": candidate.order,
                "bbox_x1": source_box[0], "bbox_y1": source_box[1],
                "bbox_x2": source_box[2], "bbox_y2": source_box[3],
                "bbox_coordinate_system": "original_source_pixels_xyxy",
                "relative_path": relative_path.as_posix(),
                "mime_type": "image/png", "width": width, "height": height,
                "sha256": png_hash, "source_page_sha256": source_page_sha256,
                "engine": engine, "engine_version": engine_version,
                "candidate_id": options.candidate_id,
                "extraction_version": options.extraction_version,
                "created_at": prior.get("created_at") or datetime.now(timezone.utc).isoformat(),
            })
        if existing is not None and set(old_by_id) != seen:
            raise FigurePersistenceError("figure set differs from existing manifest; refusing destructive update")
        manifest = {
            "schema_version": FIGURE_MANIFEST_SCHEMA_VERSION,
            "page_id": page_id,
            "source_page_sha256": source_page_sha256,
            "engine": engine,
            "engine_version": engine_version,
            "candidate_id": options.candidate_id,
            "extraction_version": options.extraction_version,
            "figures": records,
        }
        validate_figure_manifest(manifest)
        encoded = (json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
        ) + "\n").encode("utf-8")
        if manifest_path.exists() and manifest_path.read_bytes() == encoded:
            return manifest
        _atomic_write(manifest_path, encoded, replace=manifest_path.exists())
        return manifest
    except Exception:
        for path in newly_created:
            try:
                path.unlink()
            except OSError:
                pass
        raise
