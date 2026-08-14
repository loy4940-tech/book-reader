"""Phase 8Aのページ分類・OCR結果contract。"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClassificationResult:
    language: str
    orientation: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class PreprocessResult:
    image: Any
    original_size: tuple[int, int]
    content_box: tuple[int, int, int, int]
    output_size: tuple[int, int]
    threshold: int
    version: str = "1"


@dataclass(frozen=True)
class EngineRequest:
    language: str
    psm: int
    oem: int = 3
    routing_category: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FigureCandidate:
    """Engine-neutral figure location in the OCR input image coordinate space."""

    order: int
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class EngineResult:
    text: str
    engine: str
    engine_version: str
    elapsed_seconds: float
    figures: tuple[FigureCandidate, ...] = ()


@dataclass(frozen=True)
class PageOcrRecord:
    source_page: str
    source_sha256: str
    status: str
    text: str
    classifier: ClassificationResult
    engine: str
    engine_version: str
    engine_state: str
    parameters: dict[str, Any]
    model_sha256: str
    preprocess_version: str
    classifier_version: str
    pipeline_version: str
    processed_at: str
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
