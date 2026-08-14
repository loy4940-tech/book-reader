"""Phase 7A manifestからtemporary Tesseract設定を読み込む。"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import EngineUnavailableError

ENGINE_STATE = "TEMPORARY / UNVALIDATED"


@dataclass(frozen=True)
class OcrConfig:
    executable: str
    engine_version: str
    traineddata: dict
    candidate_parameters: dict
    preprocess_version: str
    classifier_version: str
    pipeline_version: str
    engine_state: str = ENGINE_STATE


@dataclass(frozen=True)
class YomiTokuConfig:
    engine_version: str
    traineddata: dict
    candidate_parameters: dict
    preprocess_version: str
    classifier_version: str
    pipeline_version: str
    model_manifest_path: str
    engine_state: str = ENGINE_STATE


def load_ocr_config(manifest_path: Path | None = None) -> OcrConfig:
    path = manifest_path or Path(__file__).resolve().parent.parent / "ocr_environment.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineUnavailableError(f"OCR environment manifestを読めません: {path}") from exc

    configured = data.get("engine_path", "")
    executable = configured if configured and Path(configured).is_file() else shutil.which("tesseract")
    if not executable:
        raise EngineUnavailableError("Tesseract executableが利用できません")

    traineddata = data.get("traineddata") or {}
    parameters = data.get("candidate_parameters") or {}
    if not traineddata or not parameters:
        raise EngineUnavailableError("OCR environment manifestに言語dataまたは候補parameterがありません")

    return OcrConfig(
        executable=str(executable),
        engine_version=str(data.get("engine_version", "")),
        traineddata=traineddata,
        candidate_parameters=parameters,
        preprocess_version=str(data.get("preprocess_version", "1")),
        classifier_version=str(data.get("classifier_version", "1")),
        pipeline_version=str(data.get("pipeline_version", "1")),
    )


def load_yomitoku_config(manifest_path: Path | None = None) -> YomiTokuConfig:
    path = manifest_path or Path(__file__).resolve().parent.parent / "yomitoku_model_manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineUnavailableError(f"YomiToku model manifestを読めません: {path}") from exc
    if data.get("engine") != "YomiToku" or data.get("package_version") != "0.13.1":
        raise EngineUnavailableError("YomiToku model manifestのengine/versionが不正です")
    files = data.get("model_files") or []
    if not files or any(not item.get("sha256") for item in files):
        raise EngineUnavailableError("YomiToku model manifestにmodel hashがありません")
    manifest_hash = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    model = {"sha256": manifest_hash}
    parameters = {
        "ja_vertical": {
            "language": "jpn", "reading_order": "right2left", "device": "cpu", "mode": "lite",
        },
        "ja_horizontal": {
            "language": "jpn", "reading_order": "auto", "device": "cpu", "mode": "lite",
        },
        "en_horizontal": {
            "language": "eng", "reading_order": "auto", "device": "cpu", "mode": "lite",
        },
    }
    return YomiTokuConfig(
        engine_version="0.13.1",
        traineddata={"jpn": model, "eng": model},
        candidate_parameters=parameters,
        preprocess_version="1",
        classifier_version="1",
        pipeline_version="1",
        model_manifest_path=str(path),
    )
