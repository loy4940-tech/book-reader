"""1 invocation = 1 page のPhase 8A orchestration。"""

import hashlib
from datetime import datetime
from pathlib import Path

from logger_setup import setup_logger

from .classifier import classify_page
from .config import OcrConfig
from .engine_factory import create_candidate
from .engines import OcrEngine
from .errors import OcrPageError, RecordAssemblyError
from .figures import FigurePersistenceOptions, persist_figures
from .models import EngineRequest, PageOcrRecord
from .preprocess import preprocess_page

logger = setup_logger("book_reader.ocr")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request_for(config: OcrConfig, language: str, orientation: str) -> EngineRequest:
    if language == "jpn" and orientation == "vertical":
        key = "ja_vertical"
    elif language == "eng":
        key = "en_horizontal"
    else:
        key = "ja_horizontal"
    parameters = config.candidate_parameters.get(key)
    if not parameters:
        raise RecordAssemblyError(f"OCR parameterがありません: {key}")
    return EngineRequest(
        str(parameters.get("lang", parameters.get("language", language))),
        int(parameters.get("psm", 0)), int(parameters.get("oem", 3)),
        routing_category=key, options=dict(parameters),
    )


class PageOcrProcessor:
    def __init__(
        self, config: OcrConfig, engine: OcrEngine,
        *, figure_options: FigurePersistenceOptions | None = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.figure_options = figure_options or FigurePersistenceOptions()

    def process(
        self,
        image_path: str | Path,
        *,
        page_id: str | None = None,
        book_identifier: str | None = None,
        language_override: str | None = None,
        orientation_override: str | None = None,
    ) -> PageOcrRecord:
        path = Path(image_path)
        identifier = page_id or path.name
        logger.info("page OCRを開始: page=%s engine_state=%s", identifier, self.config.engine_state)
        try:
            preprocessed = preprocess_page(path)
            classification = classify_page(
                preprocessed.image,
                book_identifier or str(path.parent),
                language_override=language_override,
                orientation_override=orientation_override,
            )
            if classification.language == "unknown":
                raise RecordAssemblyError("言語を判定できません。language_overrideが必要です")
            request = _request_for(self.config, classification.language, classification.orientation)
            result = self.engine.recognize(preprocessed.image, request)
            model = self.config.traineddata.get(request.language) or {}
            record_parameters = dict(request.options) if request.options else {
                "lang": request.language, "psm": request.psm, "oem": request.oem,
            }
            record = PageOcrRecord(
                source_page=identifier,
                source_sha256=_sha256(path),
                status="success",
                text=result.text,
                classifier=classification,
                engine=result.engine,
                engine_version=result.engine_version,
                engine_state=self.config.engine_state,
                parameters=record_parameters,
                model_sha256=str(model.get("sha256", "")),
                preprocess_version=self.config.preprocess_version,
                classifier_version=self.config.classifier_version,
                pipeline_version=self.config.pipeline_version,
                processed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                elapsed_seconds=result.elapsed_seconds,
            )
            persist_figures(
                source_path=path,
                page_id=identifier,
                source_page_sha256=record.source_sha256,
                preprocessed=preprocessed,
                figures=result.figures,
                engine=result.engine,
                engine_version=result.engine_version,
                options=self.figure_options,
            )
        except OcrPageError:
            logger.exception("page OCRに失敗: page=%s", identifier)
            raise
        except Exception as exc:
            logger.exception("page OCRで予期しない失敗: page=%s", identifier)
            raise RecordAssemblyError("page OCR recordの組み立てに失敗しました") from exc
        logger.info("page OCRが完了: page=%s", identifier)
        return record


def process_page(
    image_path: str | Path, *, candidate_id: str = "tesseract-default",
    manifest_path: Path | None = None, **kwargs,
) -> PageOcrRecord:
    config, engine = create_candidate(candidate_id, manifest_path=manifest_path)
    return PageOcrProcessor(config, engine).process(image_path, **kwargs)
