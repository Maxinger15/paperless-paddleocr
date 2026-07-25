"""Typed page model and hOCR serialisation used by OCRmyPDF."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from paperless_paddleocr.engine.geometry import BBox

_LANG_RE = re.compile(r"^[a-z]{2,3}$")


def to_hocr_lang(code: str | None) -> str:
    cleaned = (code or "").strip().lower()
    return cleaned if _LANG_RE.fullmatch(cleaned) else "und"


@dataclass(frozen=True)
class Word:
    text: str
    box: BBox
    confidence: int


@dataclass
class Line:
    box: BBox
    confidence: int
    text: str
    words: list[Word] = field(default_factory=list)
    baseline: tuple[float, float] = (0.0, 0.0)


@dataclass
class Block:
    box: BBox
    lines: list[Line] = field(default_factory=list)


@dataclass
class Page:
    width: int
    height: int
    lang: str
    ocr_system: str
    blocks: list[Block] = field(default_factory=list)


def _bbox(box: BBox) -> str:
    return f"bbox {box[0]} {box[1]} {box[2]} {box[3]}"


def render_hocr(page: Page) -> str:
    lang = escape(to_hocr_lang(page.lang), {'"': "&quot;"})
    ocr_system = escape(page.ocr_system, {'"': "&quot;"})
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"',
        '    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">',
        "<head>",
        "<title></title>",
        '<meta http-equiv="content-type" content="text/html; charset=utf-8" />',
        f'<meta name="ocr-system" content="{ocr_system}" />',
        '<meta name="ocr-capabilities" content="ocr_page ocr_carea ocr_par ocr_line ocrx_word" />',
        "</head>",
        "<body>",
        f'<div class="ocr_page" id="page_1" title="bbox 0 0 {page.width} {page.height}">',
    ]
    word_no = line_no = 0
    for block_no, block in enumerate(page.blocks, start=1):
        out.extend(
            [
                f'<div class="ocr_carea" id="carea_{block_no}" title="{_bbox(block.box)}">',
                f'<p class="ocr_par" id="par_{block_no}" lang="{lang}" title="{_bbox(block.box)}">',
            ]
        )
        for line in block.lines:
            line_no += 1
            slope, constant = line.baseline
            out.append(
                f'<span class="ocr_line" id="line_{line_no}" title="{_bbox(line.box)}; '
                f'baseline {slope:.6f} {constant:.0f}; x_wconf {line.confidence}">'
            )
            for index, word in enumerate(line.words):
                word_no += 1
                out.append(
                    f'<span class="ocrx_word" id="word_{word_no}" '
                    f'title="{_bbox(word.box)}; x_wconf {word.confidence}">{escape(word.text)}</span>'
                )
                if index < len(line.words) - 1:
                    out.append(" ")
            out.append("</span>")
        out.extend(["</p>", "</div>"])
    out.extend(["</div>", "</body>", "</html>"])
    return "\n".join(out)


def sidecar_text(page: Page) -> str:
    return "\n".join(line.text for block in page.blocks for line in block.lines if line.text)


def write_document(page: Page, hocr_path: Path, text_path: Path) -> None:
    hocr_path.write_text(render_hocr(page), encoding="utf-8")
    text_path.write_text(sidecar_text(page), encoding="utf-8")
