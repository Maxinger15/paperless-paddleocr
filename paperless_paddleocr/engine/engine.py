"""OCRmyPDF engine backed by a remote PaddleX PP-OCRv6 Basic Serving API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence
from PIL import Image

from paperless_paddleocr import __version__
from paperless_paddleocr.engine import client, deskew, osd, pdf
from paperless_paddleocr.engine.geometry import BBox, estimate_word_boxes
from paperless_paddleocr.engine.hocr import Block, Line, Page, Word, write_document

log = logging.getLogger("paperless.paddleocr.engine")


def _effective_verify_tls(options: Any) -> bool | str:
    ca_bundle = (getattr(options, "paddleocr_ca_bundle", "") or "").strip()
    if ca_bundle:
        return ca_bundle
    configured = getattr(options, "paddleocr_verify_tls", True)
    if isinstance(configured, bool):
        return configured
    normalized = str(configured).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise client.PaddleOCRClientError(
        "PaddleOCR TLS verification must be configured as true or false."
    )


def _config(options: Any) -> client.PaddleOCRConfig:
    return client.PaddleOCRConfig(
        server_url=getattr(options, "paddleocr_server_url", "") or "",
        endpoint=getattr(options, "paddleocr_endpoint", client.DEFAULT_ENDPOINT)
        or client.DEFAULT_ENDPOINT,
        api_key=getattr(options, "paddleocr_api_key", "") or "",
        connect_timeout=float(getattr(options, "paddleocr_connect_timeout", 10)),
        read_timeout=float(getattr(options, "paddleocr_read_timeout", 300)),
        verify_tls=_effective_verify_tls(options),
    )


def _clamp_box(box: tuple[float, float, float, float], width: int, height: int) -> BBox:
    x0, y0, x1, y1 = (round(value) for value in box)
    x0, x1 = sorted((max(0, min(width, x0)), max(0, min(width, x1))))
    y0, y1 = sorted((max(0, min(height, y0)), max(0, min(height, y1))))
    if x0 == x1 or y0 == y1:
        raise client.PaddleOCRClientError(
            "PaddleOCR returned a recognition box with no visible area."
        )
    return x0, y0, x1, y1


def _page(lines: list[client.RecognitionLine], width: int, height: int, lang: str) -> Page:
    blocks: list[Block] = []
    for recognition in lines:
        box = _clamp_box(recognition.box, width, height)
        confidence = round(recognition.score * 100)
        words = recognition.text.split()
        word_boxes = estimate_word_boxes(words, box)
        line = Line(
            box=box,
            confidence=confidence,
            text=recognition.text,
            words=[
                Word(text, word_box, confidence)
                for text, word_box in zip(words, word_boxes, strict=True)
            ],
        )
        blocks.append(Block(box=box, lines=[line]))
    return Page(
        width=width, height=height, lang=lang, ocr_system="PP-OCRv6 via PaddleX", blocks=blocks
    )


class PaddleOCREngine(OcrEngine):
    """PP-OCRv6 implementation of OCRmyPDF's engine interface."""

    @staticmethod
    def version() -> str:
        return __version__

    @staticmethod
    def creator_tag(options: Any) -> str:
        return f"PaddleOCR {PaddleOCREngine.version()}"

    def __str__(self) -> str:
        return f"PaddleOCR {self.version()}"

    @staticmethod
    def languages(options: Any) -> set[str]:
        return set(getattr(options, "languages", None) or []) | {"eng"}

    @staticmethod
    def get_orientation(input_file: Path, options: Any) -> OrientationConfidence:
        try:
            angle, confidence = osd.detect_orientation(input_file)
            return OrientationConfidence(angle=angle, confidence=confidence)
        except Exception:
            log.exception("Local Tesseract OSD failed for %s; skipping rotation.", input_file)
            return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options: Any) -> float:
        try:
            return deskew.estimate_skew(input_file)
        except Exception:
            log.exception("Local deskew estimation failed for %s; skipping deskew.", input_file)
            return 0.0

    @staticmethod
    def generate_hocr(input_file: Path, output_hocr: Path, output_text: Path, options: Any) -> None:
        with Image.open(input_file) as image:
            page_image = image.convert("RGB")
        recognitions = client.ocr_image(page_image, _config(options))
        languages = list(getattr(options, "languages", None) or [])
        write_document(
            _page(
                recognitions,
                page_image.width,
                page_image.height,
                languages[0] if languages else "eng",
            ),
            output_hocr,
            output_text,
        )

    @classmethod
    def generate_pdf(
        cls, input_file: Path, output_pdf: Path, output_text: Path, options: Any
    ) -> None:
        output_hocr = output_pdf.with_suffix(".hocr")
        cls.generate_hocr(input_file, output_hocr, output_text, options)
        pdf.render_textonly(input_file, output_hocr, output_pdf)
