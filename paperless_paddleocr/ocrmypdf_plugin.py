"""OCRmyPDF hook registration and cheap PaddleOCR configuration validation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import ocrmypdf

from paperless_paddleocr.engine.client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ENDPOINT,
    DEFAULT_READ_TIMEOUT,
    PaddleOCRClientError,
    normalize_endpoint,
    normalize_server_url,
)
from paperless_paddleocr.engine.engine import PaddleOCREngine

log = logging.getLogger("paperless.paddleocr.plugin")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no", "off"}:
        return False
    raise ValueError("paddleocr_verify_tls must be true or false.")


def _positive_timeout(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive number.")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a positive number.") from error
    if timeout <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return timeout


@ocrmypdf.hookimpl
def add_options(parser: Any) -> None:
    group = parser.add_argument_group("PaddleOCR", "Options for the PP-OCRv6 PaddleX service")
    group.add_argument(
        "--paddleocr-server-url", default="", dest="paddleocr_server_url", metavar="URL"
    )
    group.add_argument(
        "--paddleocr-endpoint", default=DEFAULT_ENDPOINT, dest="paddleocr_endpoint", metavar="PATH"
    )
    group.add_argument("--paddleocr-api-key", default="", dest="paddleocr_api_key", metavar="KEY")
    group.add_argument(
        "--paddleocr-connect-timeout",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT,
        dest="paddleocr_connect_timeout",
        metavar="SECONDS",
    )
    group.add_argument(
        "--paddleocr-read-timeout",
        type=float,
        default=DEFAULT_READ_TIMEOUT,
        dest="paddleocr_read_timeout",
        metavar="SECONDS",
    )
    group.add_argument(
        "--paddleocr-verify-tls", default=True, dest="paddleocr_verify_tls", metavar="BOOL"
    )
    group.add_argument(
        "--paddleocr-ca-bundle", default="", dest="paddleocr_ca_bundle", metavar="PATH"
    )


@ocrmypdf.hookimpl
def check_options(options: Any) -> None:
    """Validate local values only; first page request reports network failures."""
    server_url = getattr(options, "paddleocr_server_url", "") or ""
    endpoint = getattr(options, "paddleocr_endpoint", DEFAULT_ENDPOINT)
    try:
        normalize_server_url(server_url)
        normalize_endpoint(endpoint)
    except PaddleOCRClientError as error:
        raise ValueError(str(error)) from error
    _positive_timeout(
        "paddleocr_connect_timeout", getattr(options, "paddleocr_connect_timeout", None)
    )
    _positive_timeout("paddleocr_read_timeout", getattr(options, "paddleocr_read_timeout", None))
    verify_tls = _bool(getattr(options, "paddleocr_verify_tls", True))
    ca_bundle = (getattr(options, "paddleocr_ca_bundle", "") or "").strip()
    if ca_bundle and not verify_tls:
        raise ValueError("paddleocr_ca_bundle cannot be combined with disabled TLS verification.")
    if ca_bundle:
        path = Path(ca_bundle)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError("paddleocr_ca_bundle must name a readable CA certificate file.")
        options.paddleocr_verify_tls = str(path)
    elif not verify_tls:
        log.warning("PaddleOCR TLS certificate verification is disabled by configuration.")
        options.paddleocr_verify_tls = False
    else:
        options.paddleocr_verify_tls = True


@ocrmypdf.hookimpl(tryfirst=True)
def get_ocr_engine() -> Any:
    return PaddleOCREngine()
