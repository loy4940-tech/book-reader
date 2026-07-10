"""保存済みPNGを1ページ1画像のPDFにまとめる。

各ページ上部に撮影日時、下部にページ番号を表示し、先頭にセッション概要ページを付ける。
アスペクト比を維持し、A4横向きを既定とする。
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from .errors import PdfBuildError


def _page_size(page: str, orientation: str):
    base = A4  # 現状はA4のみサポート（将来拡張可）
    return landscape(base) if orientation == "landscape" else portrait(base)


def build_pdf(
    captures: list,
    output_path: Path,
    *,
    summary: dict,
    page_size: str = "A4",
    orientation: str = "landscape",
    add_timestamp: bool = True,
    add_page_number: bool = True,
    add_summary_page: bool = True,
) -> int:
    """captures（成功分。image_path/captured_at を含むdictのリスト）をPDF化する。

    生成したページ数を返す。画像が1枚もない場合は PdfBuildError。
    """
    if not captures:
        raise PdfBuildError("PDF化対象の画像がありません")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = _page_size(page_size, orientation)
    c = canvas.Canvas(str(output_path), pagesize=(width, height))
    page_count = 0

    margin = 15 * mm
    header_h = 10 * mm
    footer_h = 10 * mm

    if add_summary_page:
        _draw_summary(c, width, height, margin, summary)
        page_count += 1
        c.showPage()

    for i, cap in enumerate(captures, start=1):
        img_path = cap["image_path"]
        if not img_path or not Path(img_path).exists():
            continue

        if add_timestamp:
            c.setFont("Helvetica", 10)
            c.drawString(margin, height - margin, f"Captured: {cap.get('captured_at', '')}")

        # 画像の描画領域（ヘッダ/フッタを除いた矩形）にアスペクト比維持で収める
        avail_w = width - 2 * margin
        avail_h = height - 2 * margin - header_h - footer_h
        img = ImageReader(img_path)
        iw, ih = img.getSize()
        scale = min(avail_w / iw, avail_h / ih)
        draw_w, draw_h = iw * scale, ih * scale
        x = (width - draw_w) / 2
        y = footer_h + margin + (avail_h - draw_h) / 2
        c.drawImage(img, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True)

        if add_page_number:
            c.setFont("Helvetica", 9)
            c.drawCentredString(width / 2, margin, f"- {i} -")

        page_count += 1
        c.showPage()

    if page_count == 0:
        raise PdfBuildError("有効な画像がなくPDFを生成できませんでした")

    c.save()
    return page_count


def _draw_summary(c, width, height, margin, summary: dict) -> None:
    y = height - margin - 10 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "Screen Capture Session Summary")
    y -= 12 * mm
    c.setFont("Helvetica", 11)
    for label, key in (
        ("Target app", "target_app"),
        ("Started", "started_at"),
        ("Finished", "finished_at"),
        ("Captures", "capture_count"),
        ("Skips", "skip_count"),
        ("PDF generated", "generated_at"),
    ):
        c.drawString(margin, y, f"{label}: {summary.get(key, '')}")
        y -= 8 * mm
