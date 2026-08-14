"""Canonical OCR profile construction and fingerprinting for Phase 8B."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .config import OcrConfig, YomiTokuConfig


PROFILE_SCHEMA_VERSION = 1


def build_ocr_profile(config: OcrConfig | YomiTokuConfig) -> dict[str, Any]:
    """Return the semantic, portable profile for the Phase 8A pipeline."""
    is_yomitoku = isinstance(config, YomiTokuConfig)
    engine = {
        "name": "yomitoku" if is_yomitoku else "tesseract",
        "version": config.engine_version,
        "model_sha256": {
            name: str(details.get("sha256", ""))
            for name, details in sorted(config.traineddata.items())
        },
        "parameters": {
            "candidates": {
                name: dict(parameters)
                for name, parameters in sorted(config.candidate_parameters.items())
            },
        },
    }
    if not is_yomitoku:
        engine["parameters"]["oem"] = 3
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "engine": engine,
        "preprocess": {
            "version": config.preprocess_version,
            "parameters": {
                "crop_ratio": 0.86,
                "white_threshold": 235,
                "white_run_min_ratio": 0.5,
                "detected_content_min_fraction": 0.2,
                "crop_inset_ratio": 0.02,
                "binarization": "otsu",
                "output_mode": "1",
                "resize_resampling": "BOX",
            },
        },
        "classifier": {
            "version": config.classifier_version,
            "parameters": {
                "dark_band_threshold": 0.2,
                "minimum_bands": 3,
                "language_cjk_ratio": 0.15,
                "profile_quantiles": [0.05, 0.90],
                "resize_resampling": "BOX",
            },
        },
        "pipeline": {"version": config.pipeline_version},
    }


def canonical_profile_json(profile: Mapping[str, Any]) -> str:
    return json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def profile_id(profile: Mapping[str, Any]) -> str:
    payload = canonical_profile_json(profile).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
