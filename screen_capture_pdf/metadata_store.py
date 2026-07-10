"""撮影セッションの証跡（metadata.json）を保存する。"""
import json
from pathlib import Path
from typing import Optional


class MetadataStore:
    def __init__(self, session_id: str, target: dict, path: Path) -> None:
        self._path = path
        self._data = {
            "session_id": session_id,
            "target_app": target,
            "started_at": None,
            "finished_at": None,
            "captures": [],
            "pdf_path": None,
            "images_deleted_after_pdf": False,
        }

    # --- 記録 ---------------------------------------------------------------
    def set_started(self, iso_time: str) -> None:
        self._data["started_at"] = iso_time

    def set_finished(self, iso_time: str) -> None:
        self._data["finished_at"] = iso_time

    def add_capture(
        self,
        index: int,
        captured_at: str,
        status: str,
        image_path: Optional[str] = None,
        window_title: Optional[str] = None,
        rect: Optional[dict] = None,
    ) -> None:
        self._data["captures"].append({
            "index": index,
            "captured_at": captured_at,
            "status": status,
            "image_path": image_path,
            "window_title": window_title,
            "rect": rect,
        })

    def set_pdf(self, pdf_path: Optional[str], images_deleted: bool) -> None:
        self._data["pdf_path"] = pdf_path
        self._data["images_deleted_after_pdf"] = images_deleted

    # --- 集計 ---------------------------------------------------------------
    @property
    def success_captures(self) -> list:
        return [c for c in self._data["captures"] if c["status"] == "success"]

    @property
    def skip_count(self) -> int:
        return sum(1 for c in self._data["captures"] if c["status"] != "success")

    @property
    def data(self) -> dict:
        return self._data

    # --- 永続化 -------------------------------------------------------------
    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
