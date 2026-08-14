"""Synthetic-only tests for figure crop and persistence foundation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

import ocr.figures as figures_module
from ocr.errors import FigurePersistenceError
from ocr.figures import (
    FigurePersistenceOptions,
    deterministic_figure_id,
    map_bbox_to_source,
    persist_figures,
    validate_figure_manifest,
)
from ocr.models import FigureCandidate, PreprocessResult


def _source(path: Path) -> tuple[Path, str]:
    image = Image.new("RGB", (12, 10), "white")
    for y in range(10):
        for x in range(12):
            image.putpixel((x, y), (x * 10, y * 10, (x + y) * 5))
    image.save(path, format="PNG")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _preprocessed() -> PreprocessResult:
    return PreprocessResult(
        Image.new("1", (8, 6)), (12, 10), (2, 3, 10, 9), (8, 6), 127,
    )


def _options(root: Path, *, enabled: bool = True) -> FigurePersistenceOptions:
    return FigurePersistenceOptions(
        enabled=enabled,
        storage_root=root,
        candidate_id="yomitoku-0.13.1-cpu-lite-fixed-v1",
    )


def _persist(tmp_path: Path, candidates=(FigureCandidate(1, (1, 1, 5, 4)),)):
    source, source_hash = _source(tmp_path / "source.png")
    manifest = persist_figures(
        source_path=source, page_id="PAGE-001", source_page_sha256=source_hash,
        preprocessed=_preprocessed(), figures=candidates,
        engine="yomitoku", engine_version="0.13.1", options=_options(tmp_path / "assets"),
    )
    return source, source_hash, manifest


def test_bbox_maps_to_original_source_and_boundary_is_valid():
    assert map_bbox_to_source((0, 0, 8, 6), _preprocessed()) == (2, 3, 10, 9)
    with pytest.raises(FigurePersistenceError, match="outside OCR input"):
        map_bbox_to_source((-1, 0, 2, 2), _preprocessed())
    with pytest.raises(FigurePersistenceError, match="outside OCR input"):
        map_bbox_to_source((2, 2, 2, 3), _preprocessed())


def test_multiple_lossless_pngs_metadata_hashes_and_relative_paths(tmp_path):
    candidates = (FigureCandidate(2, (4, 2, 8, 6)), FigureCandidate(1, (0, 0, 3, 2)))
    source, source_hash, manifest = _persist(tmp_path, candidates)
    assert [item["figure_order"] for item in manifest["figures"]] == [1, 2]
    assert manifest["source_page_sha256"] == source_hash
    for item in manifest["figures"]:
        assert not Path(item["relative_path"]).is_absolute()
        path = tmp_path / "assets" / item["relative_path"]
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        with Image.open(path) as crop:
            assert crop.size == (item["width"], item["height"])
            expected = Image.open(source).crop((
                item["bbox_x1"], item["bbox_y1"], item["bbox_x2"], item["bbox_y2"],
            ))
            assert crop.convert("RGB").tobytes() == expected.convert("RGB").tobytes()


def test_zero_figures_writes_empty_manifest(tmp_path):
    _, _, manifest = _persist(tmp_path, ())
    assert manifest["figures"] == []


def test_deterministic_id_and_idempotent_reingestion(tmp_path):
    _, source_hash, first = _persist(tmp_path)
    _, _, second = _persist(tmp_path)
    assert first == second
    item = first["figures"][0]
    assert item["figure_id"] == deterministic_figure_id(
        source_hash,
        (item["bbox_x1"], item["bbox_y1"], item["bbox_x2"], item["bbox_y2"]),
        item["figure_order"],
    )
    assert len(list((tmp_path / "assets").rglob("*.png"))) == 1


def test_missing_file_is_repaired_and_hash_mismatch_fails_closed(tmp_path):
    _, _, manifest = _persist(tmp_path)
    path = tmp_path / "assets" / manifest["figures"][0]["relative_path"]
    path.unlink()
    _persist(tmp_path)
    assert path.is_file()
    path.write_bytes(b"corrupt")
    with pytest.raises(FigurePersistenceError, match="hash mismatch"):
        _persist(tmp_path)
    assert path.read_bytes() == b"corrupt"


def test_manifest_failure_removes_new_png(tmp_path, monkeypatch):
    original_link = figures_module.os.link

    def fail_manifest(source, destination):
        if Path(destination).name == "figures.manifest.json":
            raise OSError("synthetic manifest failure")
        return original_link(source, destination)

    monkeypatch.setattr(figures_module.os, "link", fail_manifest)
    with pytest.raises(FigurePersistenceError, match="atomically write"):
        _persist(tmp_path)
    assert list((tmp_path / "assets").rglob("*.png")) == []
    assert list((tmp_path / "assets").rglob("*.tmp")) == []


def test_flag_off_is_noop_and_unsafe_page_id_is_rejected(tmp_path):
    source, source_hash = _source(tmp_path / "source.png")
    result = persist_figures(
        source_path=source, page_id="../escape", source_page_sha256=source_hash,
        preprocessed=_preprocessed(), figures=(FigureCandidate(1, (0, 0, 1, 1)),),
        engine="yomitoku", engine_version="0.13.1",
        options=_options(tmp_path / "disabled", enabled=False),
    )
    assert result is None and not (tmp_path / "disabled").exists()
    with pytest.raises(FigurePersistenceError, match="unsafe page_id"):
        persist_figures(
            source_path=source, page_id="../escape", source_page_sha256=source_hash,
            preprocessed=_preprocessed(), figures=(), engine="yomitoku",
            engine_version="0.13.1", options=_options(tmp_path / "assets"),
        )


def test_existing_manifest_rejects_changed_figure_set(tmp_path):
    _persist(tmp_path)
    with pytest.raises(FigurePersistenceError, match="figure set differs"):
        _persist(tmp_path, (FigureCandidate(2, (1, 1, 5, 4)),))
    manifest = json.loads(
        (tmp_path / "assets" / "figures" / "PAGE-001" / "figures.manifest.json")
        .read_text(encoding="utf-8")
    )
    assert len(manifest["figures"]) == 1


def test_manifest_validation_rejects_duplicate_identity_and_absolute_path(tmp_path):
    _, _, manifest = _persist(tmp_path)
    duplicate = dict(manifest["figures"][0])
    manifest["figures"].append(duplicate)
    with pytest.raises(FigurePersistenceError, match="duplicate or invalid figure_id"):
        validate_figure_manifest(manifest)
    manifest["figures"] = [duplicate]
    duplicate["relative_path"] = "C:/absolute/figure.png"
    with pytest.raises(FigurePersistenceError, match="relative_path"):
        validate_figure_manifest(manifest)
