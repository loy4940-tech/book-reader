"""screen_capture_pdf モジュールのユニットテスト。"""
import json
from pathlib import Path

import pytest
from PIL import Image

from screen_capture_pdf import cleanup, pdf_builder
from screen_capture_pdf.capture_service import CaptureService
from screen_capture_pdf.errors import PdfBuildError
from screen_capture_pdf.interval_adapter import IntervalAdapter
from screen_capture_pdf.metadata_store import MetadataStore
from screen_capture_pdf.window_resolver import SKIP_NOT_FOUND, resolve_target


# --- interval_adapter ------------------------------------------------------
def test_interval_adapter_returns_value_in_range():
    cfg = {"min_interval": 5, "max_interval": 5, "jitter_distribution": "uniform"}
    adapter = IntervalAdapter(cfg)
    assert adapter.get_next_interval_seconds() == 5


def test_interval_adapter_fallback_on_bad_config():
    adapter = IntervalAdapter({}, fallback_seconds=42)
    assert adapter.get_next_interval_seconds() == 42


# --- window_resolver -------------------------------------------------------
def test_resolver_skips_when_not_found():
    result = resolve_target("___definitely_no_such_window_title___")
    assert result.window is None
    assert result.skip_reason == SKIP_NOT_FOUND


# --- metadata_store --------------------------------------------------------
def test_metadata_save_and_counts(tmp_path):
    path = tmp_path / "metadata.json"
    store = MetadataStore("sid", {"window_title_keyword": "業務"}, path)
    store.add_capture(1, "2026-07-10T18:00:00+09:00", "success", image_path="a.png")
    store.add_capture(2, "2026-07-10T18:01:00+09:00", "not_found")
    store.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["session_id"] == "sid"
    assert len(data["captures"]) == 2
    assert len(store.success_captures) == 1
    assert store.skip_count == 1


# --- pdf_builder -----------------------------------------------------------
def _make_png(path: Path, color=(200, 200, 200), size=(400, 300)) -> None:
    Image.new("RGB", size, color).save(path)


def test_pdf_build_success(tmp_path):
    img1 = tmp_path / "c1.png"
    img2 = tmp_path / "c2.png"
    _make_png(img1)
    _make_png(img2, color=(100, 100, 100))
    captures = [
        {"image_path": str(img1), "captured_at": "2026-07-10T18:00:00+09:00"},
        {"image_path": str(img2), "captured_at": "2026-07-10T18:01:00+09:00"},
    ]
    out = tmp_path / "out.pdf"
    pages = pdf_builder.build_pdf(captures, out, summary={"target_app": "業務"})
    # 概要ページ + 画像2枚 = 3ページ
    assert pages == 3
    assert out.exists() and out.stat().st_size > 0


def test_pdf_build_no_images_raises(tmp_path):
    with pytest.raises(PdfBuildError):
        pdf_builder.build_pdf([], tmp_path / "out.pdf", summary={})


# --- cleanup ---------------------------------------------------------------
def test_cleanup_allowed_when_pdf_valid(tmp_path):
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    assert cleanup.can_delete_pngs(pdf, generated_pages=3, expected_pages=3) is True


def test_cleanup_blocked_when_pdf_missing(tmp_path):
    assert cleanup.can_delete_pngs(tmp_path / "nope.pdf", 3, 3) is False


def test_cleanup_blocked_when_pdf_zero_bytes(tmp_path):
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"")
    assert cleanup.can_delete_pngs(pdf, 3, 3) is False


def test_cleanup_blocked_when_page_count_mismatch(tmp_path):
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    assert cleanup.can_delete_pngs(pdf, generated_pages=2, expected_pages=3) is False


def test_delete_pngs_removes_files(tmp_path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    p1.write_bytes(b"x")
    p2.write_bytes(b"y")
    deleted = cleanup.delete_pngs([str(p1), str(p2)])
    assert deleted == 2
    assert not p1.exists() and not p2.exists()


# --- capture_service (統合) ------------------------------------------------
def _config(enabled=True, keyword="___no_such_window___"):
    return {
        "min_interval": 5, "max_interval": 5,
        "screen_capture": {
            "enabled": enabled,
            "target": {"window_title_keyword": keyword},
            "output": {"base_dir": "output/screen_capture"},
        },
    }


def test_capture_once_records_skip_when_window_missing(tmp_path):
    service = CaptureService(_config(), tmp_path)
    service.start_session()
    service.capture_once()
    md_path = next(tmp_path.rglob("metadata.json"))
    data = json.loads(md_path.read_text(encoding="utf-8"))
    assert data["captures"][0]["status"] == SKIP_NOT_FOUND


def test_finish_session_builds_pdf_and_deletes_png(tmp_path, monkeypatch):
    """撮影成功をモックし、PDF生成→PNG削除まで通ることを確認する。"""
    from screen_capture_pdf import capture_service as cs
    from screen_capture_pdf.window_resolver import ResolveResult, WindowInfo

    fake_window = WindowInfo(hwnd=1, title="業務アプリ", left=0, top=0, width=400, height=300)
    monkeypatch.setattr(cs, "resolve_target", lambda *a, **k: ResolveResult(fake_window, None))
    monkeypatch.setattr(cs, "capture_window", lambda hwnd: Image.new("RGB", (400, 300), (180, 180, 180)))

    service = CaptureService(_config(keyword="業務"), tmp_path)
    service.start_session()
    service.capture_once()
    service.capture_once()
    png_paths = list(tmp_path.rglob("*.png"))
    assert len(png_paths) == 2  # 撮影直後はPNGが存在

    pdf_path = service.finish_session()
    assert pdf_path is not None and pdf_path.exists()
    # keep_png_after_pdf=False（既定）なのでPNGは削除されている
    assert list(tmp_path.rglob("*.png")) == []
    data = json.loads(next(tmp_path.rglob("metadata.json")).read_text(encoding="utf-8"))
    assert data["images_deleted_after_pdf"] is True
