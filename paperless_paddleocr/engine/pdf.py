"""Render hOCR to OCRmyPDF's invisible-text-only PDF representation."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def render_textonly(input_file: Path, hocr_file: Path, output_pdf: Path) -> None:
    import ocrmypdf
    from ocrmypdf.font import MultiFontManager
    from ocrmypdf.fpdf_renderer import Fpdf2PdfRenderer
    from ocrmypdf.hocrtransform import HocrParser

    page = HocrParser(hocr_file).parse()
    dpi = page.dpi
    if not dpi:
        with Image.open(input_file) as image:
            dpi = image.info.get("dpi", (300, 300))[0]
    renderer = Fpdf2PdfRenderer(
        page=page,
        dpi=float(dpi or 300),
        multi_font_manager=MultiFontManager(Path(ocrmypdf.__file__).parent / "data"),
        invisible_text=True,
        image=None,
    )
    renderer.render(output_pdf)
