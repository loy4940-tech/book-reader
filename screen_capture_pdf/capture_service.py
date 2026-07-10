"""撮影処理全体を統括する。

セッション開始 → 各撮影（capture_once）でPNG保存とmetadata記録 →
終了時（finish_session）にPDF生成、成功時のみPNG削除、を担う。
"""
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


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class CaptureService:
    def __init__(self, config: dict, base_dir: Path) -> None:
        sc = config.get("screen_capture", {})
        self._target = sc.get("target", {})
        self._output = sc.get("output", {})
        self._base_output = base_dir / self._output.get("base_dir", "output/screen_capture")

        self._session_id: Optional[str] = None
        self._session_dir: Optional[Path] = None
        self._images_dir: Optional[Path] = None
        self._metadata: Optional[MetadataStore] = None
        self._index = 0

    # --- セッション ---------------------------------------------------------
    def start_session(self) -> None:
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = self._base_output / self._session_id
        self._images_dir = self._session_dir / "images"
        self._images_dir.mkdir(parents=True, exist_ok=True)
        self._metadata = MetadataStore(
            self._session_id,
            {
                "window_title_keyword": self._target.get("window_title_keyword"),
                "process_name": self._target.get("process_name"),
            },
            self._session_dir / "metadata.json",
        )
        self._metadata.set_started(_now_iso())
        self._metadata.save()
        self._index = 0
        logger.info("撮影セッションを開始しました: %s", self._session_id)

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
            logger.warning("撮影成功が0枚のためPDFは生成しません")
            return None

        pdf_path = self._session_dir / "capture_log.pdf"
        summary = {
            "target_app": self._target.get("window_title_keyword"),
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
            logger.error("PDF生成に失敗しました（PNGは削除しません）: %s", e)
            return None

        expected = len(successes) + (1 if add_summary else 0)
        deleted = False
        keep_png = self._output.get("keep_png_after_pdf", False)
        if not keep_png and cleanup.can_delete_pngs(pdf_path, pages, expected):
            image_paths = [c["image_path"] for c in successes]
            n = cleanup.delete_pngs(image_paths)
            deleted = True
            logger.info("PDF生成成功。一時PNGを削除しました（%d枚）", n)
        elif not keep_png:
            logger.warning("PDF検証に問題があるためPNGを削除しませんでした")

        self._metadata.set_pdf(str(pdf_path), images_deleted=deleted)
        self._metadata.save()
        logger.info("PDFを生成しました: %s（%dページ）", pdf_path, pages)
        return pdf_path
