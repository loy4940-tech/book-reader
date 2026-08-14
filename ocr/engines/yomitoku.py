"""YomiToku 0.13.1 Windows CPU-lite adapter."""

from __future__ import annotations

import time
from typing import Any, Iterable

from PIL import Image

from ..config import YomiTokuConfig
from ..errors import EngineProcessError, EngineUnavailableError
from ..models import EngineRequest, EngineResult, FigureCandidate
from .base import OcrEngine


YOMITOKU_CANDIDATE_ID = "yomitoku-0.13.1-cpu-lite-fixed-v1"


def _value(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _ordered(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda item: (_value(item, "order", 0) or 0, str(_value(item, "box", ""))))


def canonical_text_from_yomitoku(result: Any) -> str:
    """Flatten structured output deterministically; figure-internal text is excluded."""
    blocks: list[tuple[int, int, str]] = []
    for paragraph in _value(result, "paragraphs", []) or []:
        contents = (_value(paragraph, "contents", "") or "").strip()
        if contents:
            blocks.append((int(_value(paragraph, "order", 0) or 0), 0, contents))
    for table in _value(result, "tables", []) or []:
        rows: dict[int, list[tuple[int, str]]] = {}
        for cell in _value(table, "cells", []) or []:
            contents = (_value(cell, "contents", "") or "").strip()
            if contents:
                rows.setdefault(int(_value(cell, "row", 0)), []).append(
                    (int(_value(cell, "col", 0)), contents)
                )
        table_text = "\n".join(
            "\t".join(text for _, text in sorted(cells))
            for _, cells in sorted(rows.items())
        )
        if table_text:
            blocks.append((int(_value(table, "order", 0) or 0), 1, table_text))
    # result.figures and their paragraphs are intentionally not traversed. PLAN.md
    # excludes text inside figures; captions remain included when emitted as paragraphs.
    return "\n\n".join(text for _, _, text in sorted(blocks))


def figure_candidates_from_yomitoku(result: Any) -> tuple[FigureCandidate, ...]:
    """Normalize YomiToku figures without traversing figure-internal text."""
    candidates: list[FigureCandidate] = []
    for fallback_order, figure in enumerate(_ordered(_value(result, "figures", []) or []), 1):
        box = _value(figure, "box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise EngineProcessError("YomiToku figure is missing its [x1, y1, x2, y2] box")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in box):
            raise EngineProcessError("YomiToku figure box must contain four integers")
        raw_order = _value(figure, "order")
        order = fallback_order if raw_order is None else int(raw_order)
        candidates.append(FigureCandidate(order, tuple(box)))
    return tuple(sorted(candidates, key=lambda item: (item.order, item.bbox)))


class YomiTokuEngine(OcrEngine):
    def __init__(self, config: YomiTokuConfig) -> None:
        self.config = config

    @staticmethod
    def _analyzer(reading_order: str):
        try:
            from yomitoku import DocumentAnalyzer
        except ImportError as exc:
            raise EngineUnavailableError("YomiToku candidate environmentが必要です") from exc
        configs = {
            "ocr": {
                "text_recognizer": {
                    "model_name": "parseq-tiny-dynw-v4", "dynamic_width": True,
                    "batch_bucketing": True, "source_downscale": True,
                    "num_parallel_batches": 4, "device": "cpu",
                },
                "text_detector": {"device": "cpu", "infer_onnx": True},
            },
            "layout_analyzer": {
                "layout_parser": {"device": "cpu"},
                "table_structure_recognizer": {"device": "cpu"},
            },
        }
        return DocumentAnalyzer(
            configs=configs, device="cpu", visualize=False, ignore_meta=True,
            reading_order=reading_order, ignore_ruby=True,
        )

    def recognize(self, image: Image.Image, request: EngineRequest) -> EngineResult:
        if request.options.get("device") != "cpu" or request.options.get("mode") != "lite":
            raise EngineUnavailableError("YomiTokuはfixed CPU/lite configurationのみ許可されます")
        started = time.perf_counter()
        try:
            import numpy as np

            analyzer = self._analyzer(str(request.options.get("reading_order", "auto")))
            bgr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
            structured, _, _ = analyzer(bgr)
            text = canonical_text_from_yomitoku(structured)
            figures = figure_candidates_from_yomitoku(structured)
        except EngineUnavailableError:
            raise
        except Exception as exc:
            raise EngineProcessError(f"YomiToku inference failed: {exc}") from exc
        return EngineResult(
            text, "yomitoku", self.config.engine_version,
            time.perf_counter() - started, figures,
        )
