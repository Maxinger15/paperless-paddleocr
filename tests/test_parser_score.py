"""Parser priority is testable without requiring a running Paperless host."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace


def _module(monkeypatch):
    """Load the parser against the smallest accurate import-time host surface."""
    django = ModuleType("django")
    django_conf = ModuleType("django.conf")
    django_conf.settings = SimpleNamespace()
    django.conf = django_conf

    documents = ModuleType("documents")
    documents_parsers = ModuleType("documents.parsers")
    documents_parsers.ParseError = RuntimeError
    documents_parsers.make_thumbnail_from_pdf = lambda *args: None
    documents_utils = ModuleType("documents.utils")
    documents_utils.copy_file_with_basic_stats = lambda *args: None
    documents_utils.maybe_override_pixel_limit = lambda: None
    documents_utils.run_subprocess = lambda *args, **kwargs: None
    documents.parsers = documents_parsers
    documents.utils = documents_utils

    paperless = ModuleType("paperless")
    paperless.__path__ = []
    paperless_config = ModuleType("paperless.config")
    paperless_config.OcrConfig = object
    paperless_models = ModuleType("paperless.models")
    paperless_models.CleanChoices = SimpleNamespace(CLEAN="clean", FINAL="final")
    paperless_models.ModeChoices = SimpleNamespace(
        FORCE="force", REDO="redo", OFF="off", AUTO="auto"
    )
    paperless_models.OutputTypeChoices = SimpleNamespace(PDF="pdf")
    paperless_parsers = ModuleType("paperless.parsers")
    paperless_parsers.__path__ = []
    tesseract = ModuleType("paperless.parsers.tesseract")
    tesseract.post_process_text = lambda text: text
    utils = ModuleType("paperless.parsers.utils")
    utils.PDF_TEXT_MIN_LENGTH = 1
    utils.extract_pdf_text = lambda *args, **kwargs: ""
    utils.is_tagged_pdf = lambda *args, **kwargs: False
    utils.read_file_handle_unicode_errors = lambda *args, **kwargs: ""

    modules = {
        "django": django,
        "django.conf": django_conf,
        "documents": documents,
        "documents.parsers": documents_parsers,
        "documents.utils": documents_utils,
        "paperless": paperless,
        "paperless.config": paperless_config,
        "paperless.models": paperless_models,
        "paperless.parsers": paperless_parsers,
        "paperless.parsers.tesseract": tesseract,
        "paperless.parsers.utils": utils,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "paperless_paddleocr.parser", raising=False)
    return importlib.import_module("paperless_paddleocr.parser")


def test_parser_score_uses_default_and_environment_override(monkeypatch):
    parser = _module(monkeypatch).PaperlessPaddleOCRParser
    monkeypatch.delenv("PAPERLESS_PADDLEOCR_SCORE", raising=False)
    assert parser.score("application/pdf", "document.pdf") == 15
    monkeypatch.setenv("PAPERLESS_PADDLEOCR_SCORE", "27")
    assert parser.score("application/pdf", "document.pdf") == 27
    assert parser.score("text/plain", "document.txt") is None
