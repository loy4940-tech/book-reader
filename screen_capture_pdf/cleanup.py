"""PDF生成が確実に成功した場合のみ、一時PNGを削除する。

削除条件（すべて満たす場合のみ削除）:
  - PDFファイルが存在する
  - PDFファイルサイズが0でない
  - 生成ページ数が撮影成功枚数（＋概要ページ）と一致する
いずれか満たさない場合はPNGを残す（復旧不能を防ぐ）。
"""
from pathlib import Path


def can_delete_pngs(pdf_path: Path, generated_pages: int, expected_pages: int) -> bool:
    """PNG削除が安全か判定する。"""
    if not pdf_path.exists():
        return False
    if pdf_path.stat().st_size == 0:
        return False
    if generated_pages != expected_pages:
        return False
    return True


def delete_pngs(image_paths: list) -> int:
    """PNGを削除し、削除できた件数を返す。"""
    deleted = 0
    for p in image_paths:
        path = Path(p)
        try:
            if path.exists():
                path.unlink()
                deleted += 1
        except OSError:
            pass  # 削除失敗は無視（次回起動時に残るのみで実害は小さい）
    return deleted
