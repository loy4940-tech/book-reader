"""YomiToku adapter and engine dispatch tests; no Calibration/Acceptance data."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

import ocr.engine_factory as factory
from ocr.config import YomiTokuConfig
from ocr.engines.yomitoku import (
    YOMITOKU_CANDIDATE_ID, YomiTokuEngine, canonical_text_from_yomitoku,
    figure_candidates_from_yomitoku,
)
from ocr.errors import EngineProcessError, EngineUnavailableError
from ocr.models import EngineRequest
from ocr.profile import build_ocr_profile
from tools.run_gate1 import _classify_worker_output


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Item:
    order: int = 0
    contents: str = ""
    role: str | None = None
    row: int = 0
    col: int = 0
    cells: list | None = None
    paragraphs: list | None = None
    box: list[int] | None = None


@dataclass
class Result:
    paragraphs: list
    tables: list
    figures: list


def config() -> YomiTokuConfig:
    parameters = {
        "ja_vertical": {"language": "jpn", "reading_order": "right2left", "device": "cpu", "mode": "lite"},
        "ja_horizontal": {"language": "jpn", "reading_order": "auto", "device": "cpu", "mode": "lite"},
        "en_horizontal": {"language": "eng", "reading_order": "auto", "device": "cpu", "mode": "lite"},
    }
    return YomiTokuConfig("0.13.1", {"jpn": {"sha256": "a" * 64}}, parameters,
                          "1", "1", "1", "manifest.json")


def test_horizontal_and_vertical_ordering_is_deterministic():
    result = Result([Item(2, "left"), Item(1, "right")], [], [])
    assert canonical_text_from_yomitoku(result) == "right\n\nleft"


def test_table_cells_are_flattened_by_row_then_column():
    table = Item(order=1, cells=[Item(contents="B", row=1, col=2),
                                Item(contents="C", row=2, col=1),
                                Item(contents="A", row=1, col=1)])
    assert canonical_text_from_yomitoku(Result([], [table], [])) == "A\tB\nC"


def test_figure_text_is_excluded_but_caption_paragraph_is_kept():
    figure = Item(order=1, paragraphs=[Item(contents="screenshot UI")])
    caption = Item(order=2, contents="Figure caption", role="caption")
    assert canonical_text_from_yomitoku(Result([caption], [], [figure])) == "Figure caption"


def test_figure_candidates_use_box_and_order_without_table_leakage():
    figures = [Item(order=2, box=[20, 30, 80, 90]), Item(order=1, box=[1, 2, 11, 12])]
    table = Item(order=0, box=[0, 0, 100, 100])
    result = Result([], [table], figures)
    assert [(item.order, item.bbox) for item in figure_candidates_from_yomitoku(result)] == [
        (1, (1, 2, 11, 12)), (2, (20, 30, 80, 90)),
    ]


def test_empty_structured_result_is_empty_text():
    assert canonical_text_from_yomitoku(Result([], [], [])) == ""


def test_yomitoku_nonempty_and_engine_error(monkeypatch):
    class Array:
        def __getitem__(self, _key):
            return self
        def copy(self):
            return self
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(asarray=lambda _image: Array()))
    class Analyzer:
        def __call__(self, _image):
            return Result([Item(contents="synthetic")], [], []), None, None
    monkeypatch.setattr(YomiTokuEngine, "_analyzer", staticmethod(lambda _order: Analyzer()))
    request = EngineRequest("jpn", 0, routing_category="ja_horizontal",
                            options={"device": "cpu", "mode": "lite", "reading_order": "auto"})
    assert YomiTokuEngine(config()).recognize(Image.new("RGB", (20, 20)), request).text == "synthetic"

    class Broken:
        def __call__(self, _image):
            raise RuntimeError("synthetic failure")
    monkeypatch.setattr(YomiTokuEngine, "_analyzer", staticmethod(lambda _order: Broken()))
    with pytest.raises(EngineProcessError):
        YomiTokuEngine(config()).recognize(Image.new("RGB", (20, 20)), request)


def test_fixed_cpu_lite_config_is_enforced():
    with pytest.raises(EngineUnavailableError):
        YomiTokuEngine(config()).recognize(
            Image.new("RGB", (20, 20)),
            EngineRequest("jpn", 0, options={"device": "cuda", "mode": "lite"}),
        )


def test_candidate_dispatch(monkeypatch):
    marker = object()
    monkeypatch.setattr(factory, "load_yomitoku_config", lambda _path=None: marker)
    monkeypatch.setattr(factory, "YomiTokuEngine", lambda cfg: ("yomitoku", cfg))
    cfg, engine = factory.create_candidate(YOMITOKU_CANDIDATE_ID)
    assert cfg is marker and engine == ("yomitoku", marker)

    monkeypatch.setattr(factory, "load_ocr_config", lambda _path=None: marker)
    monkeypatch.setattr(factory, "TesseractEngine", lambda cfg: ("tesseract", cfg))
    assert factory.create_candidate("tesseract-fixed-v1")[1] == ("tesseract", marker)
    with pytest.raises(EngineUnavailableError, match="unknown OCR candidate"):
        factory.create_candidate("unknown-v1")


def test_yomitoku_profile_is_fixed_and_engine_specific():
    profile = build_ocr_profile(config())
    assert profile["engine"]["name"] == "yomitoku"
    assert profile["engine"]["parameters"]["candidates"]["ja_vertical"] == {
        "language": "jpn", "reading_order": "right2left", "device": "cpu", "mode": "lite",
    }


def test_actual_yomitoku_worker_stdout_is_exact_json(tmp_path):
    python = REPO_ROOT / ".venv-yomitoku" / "Scripts" / "python.exe"
    if not python.is_file():
        pytest.skip("dedicated YomiToku environment is not installed")
    source = tmp_path / "synthetic-worker.png"
    image = Image.new("RGB", (1200, 900), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.text((80, 180), "SYNTHETIC WORKER TEST 123", fill="black", font_size=48)
    draw.text((80, 360), "SECOND PARAGRAPH", fill="black", font_size=48)
    image.save(source)
    environment = os.environ.copy()
    environment.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    result = subprocess.run(
        [str(python), str(REPO_ROOT / "tools" / "gate1_page_worker.py"),
         str(source), "SYNTHETIC-WORKER-001", "eng", "horizontal",
         "--candidate-id", YOMITOKU_CANDIDATE_ID],
        cwd=REPO_ROOT, env=environment, capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["engine"] == "yomitoku"
    assert payload["text"]
    assert b"Loading weights from local directory" not in result.stdout
    assert b"Loading weights from local directory" in result.stderr
    assert _classify_worker_output(result.returncode, result.stdout) == ("SUCCESS", None)
