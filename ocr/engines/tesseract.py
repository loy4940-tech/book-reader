"""TEMPORARY / UNVALIDATED Tesseract engine。"""

import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from ..config import OcrConfig
from ..errors import EngineProcessError, EngineUnavailableError
from ..models import EngineRequest, EngineResult
from .base import OcrEngine


class TesseractEngine(OcrEngine):
    def __init__(self, config: OcrConfig) -> None:
        self.config = config

    def recognize(self, image: Image.Image, request: EngineRequest) -> EngineResult:
        executable = Path(self.config.executable)
        if not executable.is_file():
            raise EngineUnavailableError(f"Tesseract executableが見つかりません: {executable}")
        with tempfile.TemporaryDirectory(prefix="book_reader_ocr_") as directory:
            input_path = Path(directory) / "page.png"
            image.save(input_path, format="PNG")
            command = [
                str(executable), str(input_path), "stdout", "-l", request.language,
                "--psm", str(request.psm), "--oem", str(request.oem),
            ]
            started = time.perf_counter()
            try:
                result = subprocess.run(
                    command, capture_output=True, timeout=120, check=False,
                )
            except OSError as exc:
                raise EngineUnavailableError("Tesseract processを開始できません") from exc
            except subprocess.SubprocessError as exc:
                raise EngineProcessError("Tesseract processが異常終了しました") from exc
            elapsed = time.perf_counter() - started
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise EngineProcessError(
                    f"Tesseract exit code {result.returncode}: {detail[:500]}"
                )
            try:
                text = result.stdout.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EngineProcessError("Tesseract出力がUTF-8ではありません") from exc
        return EngineResult(text, "tesseract", self.config.engine_version, elapsed)
