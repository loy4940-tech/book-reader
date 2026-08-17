"""Phase 7A manifestからtemporary Tesseract設定を読み込む。"""

import hashlib
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


@dataclass(frozen=True)
class PaddleOcrConfig:
    engine_version: str
    traineddata: dict
    candidate_parameters: dict
    preprocess_version: str
    classifier_version: str
    pipeline_version: str
    profile_path: str
    candidate_id: str
    device: str
    text_detection_model_name: str
    text_recognition_model_name: str
    use_doc_orientation_classify: bool
    use_doc_unwarping: bool
    use_textline_orientation: bool
    paddlex_cache_home: str
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


def load_paddleocr_config(manifest_path: Path | None = None) -> PaddleOcrConfig:
    path = manifest_path or Path(__file__).resolve().parent.parent / "PADDLEOCR_CANDIDATE_PROFILE.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineUnavailableError(f"PaddleOCR candidate profileを読めません: {path}") from exc
    if data.get("candidate_id") != "PADDLE-PPOCRV5-CPU-001":
        raise EngineUnavailableError("PaddleOCR candidate profileのcandidate IDが不正です")
    if data.get("profile_frozen") is not True or data.get("acceptance_access") != 0:
        raise EngineUnavailableError("PaddleOCR candidate profileがFormal-readyではありません")
    parameters = {
        "ja_vertical": {
            "language": "jpn",
            "device": data["device"],
            "text_detection_model_name": data["text_detection_model_name"],
            "text_recognition_model_name": data["text_recognition_model_name"],
        },
        "ja_horizontal": {
            "language": "jpn",
            "device": data["device"],
            "text_detection_model_name": data["text_detection_model_name"],
            "text_recognition_model_name": data["text_recognition_model_name"],
        },
        "en_horizontal": {
            "language": "eng",
            "device": data["device"],
            "text_detection_model_name": data["text_detection_model_name"],
            "text_recognition_model_name": data["text_recognition_model_name"],
        },
    }
    profile_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    traineddata = {"jpn": {"sha256": profile_hash}, "eng": {"sha256": profile_hash}}
    return PaddleOcrConfig(
        engine_version=str(data.get("engine_version", "3.7.0")),
        traineddata=traineddata,
        candidate_parameters=parameters,
        preprocess_version="1",
        classifier_version="1",
        pipeline_version="1",
        profile_path=str(path),
        candidate_id=str(data["candidate_id"]),
        device=str(data["device"]),
        text_detection_model_name=str(data["text_detection_model_name"]),
        text_recognition_model_name=str(data["text_recognition_model_name"]),
        use_doc_orientation_classify=bool(data["use_doc_orientation_classify"]),
        use_doc_unwarping=bool(data["use_doc_unwarping"]),
        use_textline_orientation=bool(data["use_textline_orientation"]),
        paddlex_cache_home=str(data["paddlex_cache_home"]),
    )
