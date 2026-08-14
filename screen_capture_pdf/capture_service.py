"""撮影処理全体を統括する。

セッション開始 → 各撮影（capture_once）でPNG保存とmetadata記録 →
終了時（finish_session）にPDF生成、成功時のみPNG削除・imagesフォルダ削除、を担う。

出力構造:
  output/<yyyymmdd>_<書名>/
    ├── images/              ← PDF生成成功後に削除
    ├── capture_log_pdf_<yyyymmdd>_<書名>.pdf
    └── metadata.json
"""
import re
import shutil
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from logger_setup import setup_logger

from . import cleanup, pdf_builder
from .errors import PdfBuildError
from .metadata_store import MetadataStore
from .screenshot_backend import capture_window
from .window_resolver import resolve_target

logger = setup_logger()

_COMPLETION_FILE = ".capture_complete.json"


def _write_completion_marker(session_dir: Path, session_id: str) -> None:
    """Publish the GUI/OCR handoff signal only after final metadata is closed."""
    path = session_dir / _COMPLETION_FILE
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=f".{path.name}.",
            suffix=".tmp", dir=session_dir, delete=False,
        ) as handle:
            temporary = handle.name
            json.dump({
                "schema_version": 1, "session_id": session_id,
                "completed_at": _now_iso(),
            }, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _capture_environment() -> dict:
    """撮影条件のうち自動取得できるものを集める。

    OCRの評価結果は解像度とスケーリングに強く依存するため、
    どの条件で撮った画像かを後から追跡できるよう記録する。
    Kindle側の文字サイズは取得できないので、評価時に手動で控える。
    """
    import ctypes

    environment = {}
    try:
        user32 = ctypes.WinDLL("user32")
        environment["screen_width"] = user32.GetSystemMetrics(0)
        environment["screen_height"] = user32.GetSystemMetrics(1)
        dpi = user32.GetDpiForSystem()
        environment["dpi"] = dpi
        environment["scaling_percent"] = round(dpi / 96 * 100)
    except (OSError, AttributeError):
        logger.debug("撮影条件の取得に失敗しました（記録をスキップします）")
    return environment


def _extract_book_name(window_title: str) -> str:
    """ウィンドウタイトルから書名を抽出する。
    "Legacy Kindle for PC - 新書 世界現代史 ..." → "新書 世界現代史 ..."
    区切り文字が見つからない場合はタイトル全体を使う。
    """
    for sep in (" - ", " – ", " — "):
        if sep in window_title:
            return window_title.split(sep, 1)[1].strip()
    return window_title.strip()


def _sanitize_filename(name: str) -> str:
    """ファイル名に使えない文字を除去する。"""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


def _unique_dir(base: Path, folder_name: str) -> Path:
    """重複時に _2, _3 … と連番を付与して一意なパスを返す。"""
    candidate = base / folder_name
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = base / f"{folder_name}_{n}"
        if not candidate.exists():
            return candidate
        n += 1


class CaptureService:
    def __init__(self, config: dict, base_dir: Path) -> None:
        sc = config.get("screen_capture", {})
        self._target = sc.get("target", {})
        self._output = sc.get("output", {})
        self._base_output = base_dir / self._output.get("base_dir", "output")

        self._date_str: Optional[str] = None
        self._book_name: Optional[str] = None
        self._session_dir: Optional[Path] = None
        self._images_dir: Optional[Path] = None
        self._metadata: Optional[MetadataStore] = None
        self._index = 0
        self._dir_finalized = False

    # --- セッション ---------------------------------------------------------
    def start_session(self) -> None:
        now = datetime.now()
        self._date_str = now.strftime("%Y%m%d")
        self._book_name = None
        self._dir_finalized = False

        temp_id = now.strftime("%Y%m%d_%H%M%S")
        temp_dir = self._base_output / f"_temp_{temp_id}"
        self._session_dir = temp_dir
        self._images_dir = temp_dir / "images"
        self._images_dir.mkdir(parents=True, exist_ok=True)

        self._metadata = MetadataStore(
            temp_id,
            {
                "window_title_keyword": self._target.get("window_title_keyword"),
                "process_name": self._target.get("process_name"),
            },
            temp_dir / "metadata.json",
        )
        self._metadata.set_started(_now_iso())
        self._metadata.set_environment(_capture_environment())
        self._metadata.save()
        self._index = 0
        logger.info("撮影セッションを開始しました: %s", temp_id)

    def _finalize_dir(self, window_title: str) -> None:
        """最初の撮影成功時にフォルダ名を確定する。"""
        if self._dir_finalized:
            return
        self._book_name = _sanitize_filename(_extract_book_name(window_title))
        if not self._book_name:
            self._book_name = "unknown"
        folder_name = f"{self._date_str}_{self._book_name}"
        final_dir = _unique_dir(self._base_output, folder_name)

        old_dir = self._session_dir
        shutil.move(str(old_dir), str(final_dir))

        self._session_dir = final_dir
        self._images_dir = final_dir / "images"
        self._metadata.update_path(final_dir / "metadata.json")
        self._dir_finalized = True
        logger.info("出力フォルダを確定: %s", final_dir.name)

    # --- 1回撮影 ------------------------------------------------------------
    def capture_once(self) -> None:
        if self._metadata is None:
            raise RuntimeError("start_session が呼ばれていません")

        self._index += 1
        captured_at = _now_iso()

        result = resolve_target(
            self._target.get("window_title_keyword", ""),
            self._target.get("process_name"),
            require_visible=self._target.get("require_visible", True),
            allow_minimized=self._target.get("allow_minimized", False),
        )

        if result.window is None:
            self._metadata.add_capture(self._index, captured_at, status=result.skip_reason)
            self._metadata.save()
            logger.warning("撮影スキップ（%s）", result.skip_reason)
            return

        win = result.window
        image = capture_window(win.hwnd)
        if image is None:
            self._metadata.add_capture(self._index, captured_at, status="capture_failed",
                                       window_title=win.title)
            self._metadata.save()
            logger.warning("撮影に失敗しました（画像取得不可）")
            return

        self._finalize_dir(win.title)

        image_path = self._images_dir / f"capture_{self._index:03d}.png"
        image.save(image_path)
        self._metadata.add_capture(
            self._index, captured_at, status="success",
            image_path=str(image_path), window_title=win.title,
            rect={"left": win.left, "top": win.top, "width": win.width, "height": win.height},
        )
        self._metadata.save()
        logger.info("撮影しました（%d枚目）", self._index)

    # --- 終了・PDF化 --------------------------------------------------------
    def finish_session(self) -> Optional[Path]:
        if self._metadata is None:
            return None

        self._metadata.set_finished(_now_iso())
        successes = self._metadata.success_captures
        if not successes:
            self._metadata.save()
            _write_completion_marker(self._session_dir, self._metadata.data["session_id"])
            logger.warning("撮影成功が0枚のためPDFは生成しません")
            return None

        name_part = f"{self._date_str}_{self._book_name or 'unknown'}"
        pdf_path = self._session_dir / f"{name_part}.pdf"

        summary = {
            "target_app": self._target.get("window_title_keyword"),
            "book_name": self._book_name,
            "started_at": self._metadata.data["started_at"],
            "finished_at": self._metadata.data["finished_at"],
            "capture_count": len(successes),
            "skip_count": self._metadata.skip_count,
            "generated_at": _now_iso(),
        }
        add_summary = self._output.get("add_summary_page", True)
        try:
            pages = pdf_builder.build_pdf(
                successes, pdf_path, summary=summary,
                page_size=self._output.get("pdf_page_size", "A4"),
                orientation=self._output.get("pdf_orientation", "landscape"),
                add_timestamp=self._output.get("add_timestamp", True),
                add_page_number=self._output.get("add_page_number", True),
                add_summary_page=add_summary,
            )
        except PdfBuildError as e:
            self._metadata.set_pdf(None, images_deleted=False)
            self._metadata.save()
            _write_completion_marker(self._session_dir, self._metadata.data["session_id"])
            logger.error("PDF生成に失敗しました（PNGは削除しません）: %s", e)
            return None

        expected = len(successes) + (1 if add_summary else 0)
        deleted = False
        keep_png = self._output.get("keep_png_after_pdf", False)
        if not keep_png and cleanup.can_delete_pngs(pdf_path, pages, expected):
            image_paths = [c["image_path"] for c in successes]
            n = cleanup.delete_pngs(image_paths)
            deleted = True
            # imagesフォルダも削除
            if self._images_dir and self._images_dir.exists():
                try:
                    shutil.rmtree(self._images_dir)
                except OSError:
                    pass
            logger.info("PDF生成成功。一時PNGとimagesフォルダを削除しました（%d枚）", n)
        elif not keep_png:
            logger.warning("PDF検証に問題があるためPNGを削除しませんでした")

        self._metadata.set_pdf(str(pdf_path), images_deleted=deleted,
                               page_count=pages, summary_page=add_summary)
        self._metadata.save()
        _write_completion_marker(self._session_dir, self._metadata.data["session_id"])
        logger.info("PDFを生成しました: %s（%dページ）", pdf_path, pages)
        return pdf_path
