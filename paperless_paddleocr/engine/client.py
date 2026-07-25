"""Small, dependency-light client for PaddleX Basic Serving's OCR endpoint."""

from __future__ import annotations

import base64
import json
import logging
import math
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from PIL import Image

log = logging.getLogger("paperless.paddleocr.client")

DEFAULT_ENDPOINT = "/ocr"
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 300.0
_MAX_RETRIES = 2
_MAX_RETRY_AFTER_SECONDS = 60.0


class PaddleOCRClientError(RuntimeError):
    """The PaddleX service response is unusable or the request could not complete."""


@dataclass(frozen=True)
class PaddleOCRConfig:
    """Validated connection settings passed from the OCRmyPDF plugin."""

    server_url: str
    endpoint: str = DEFAULT_ENDPOINT
    api_key: str = ""
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    verify_tls: bool | str | ssl.SSLContext = True

    @property
    def url(self) -> str:
        return join_url(self.server_url, self.endpoint)


@dataclass(frozen=True)
class RecognitionLine:
    """One recognised PaddleX text line in source image coordinates."""

    text: str
    score: float
    box: tuple[float, float, float, float]


def normalize_server_url(raw: str) -> str:
    """Validate and normalise the serving base URL without probing it."""
    value = (raw or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if not value or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PaddleOCRClientError(
            "PaddleOCR requires PAPERLESS_PADDLEOCR_SERVER_URL to be an absolute HTTP(S) URL."
        )
    if parsed.query or parsed.fragment:
        raise PaddleOCRClientError(
            "PAPERLESS_PADDLEOCR_SERVER_URL must not contain a query or fragment."
        )
    return value


def normalize_endpoint(raw: str | None) -> str:
    """Return an endpoint path suitable for deterministic base-URL joining."""
    value = (raw or DEFAULT_ENDPOINT).strip()
    parsed = urlsplit(value)
    if not value or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PaddleOCRClientError("PAPERLESS_PADDLEOCR_ENDPOINT must be a path such as /ocr.")
    return "/" + value.lstrip("/")


def join_url(server_url: str, endpoint: str) -> str:
    """Join a configured server prefix and a relative endpoint path."""
    return f"{normalize_server_url(server_url)}/{normalize_endpoint(endpoint).lstrip('/')}"


def _png_base64(image: Image.Image) -> str:
    """Encode one rasterised page as a lossless PNG without touching disk."""
    payload = BytesIO()
    image.convert("RGB").save(payload, format="PNG")
    return base64.b64encode(payload.getvalue()).decode("ascii")


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    if math.isfinite(seconds) and 0 <= seconds <= _MAX_RETRY_AFTER_SECONDS:
        return seconds
    return None


def _timeout_value(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaddleOCRClientError(f"PaddleOCR {name} timeout must be a finite positive number.")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise PaddleOCRClientError(f"PaddleOCR {name} timeout must be a finite positive number.")
    return timeout


def _tls_verify(verify_tls: bool | str | ssl.SSLContext) -> bool | ssl.SSLContext:
    """Build a TLS context for an operator-supplied CA bundle when configured."""
    if isinstance(verify_tls, ssl.SSLContext):
        return verify_tls
    if isinstance(verify_tls, str):
        try:
            return ssl.create_default_context(cafile=verify_tls)
        except Exception as error:
            raise PaddleOCRClientError(
                "PaddleOCR could not load the configured CA bundle; check "
                "PAPERLESS_PADDLEOCR_CA_BUNDLE."
            ) from error
    return verify_tls


def _status_error(status_code: int, url: str) -> PaddleOCRClientError:
    if status_code in {401, 403}:
        return PaddleOCRClientError(
            f"PaddleOCR service rejected authentication (HTTP {status_code}) at {url}. "
            "Check PAPERLESS_PADDLEOCR_API_KEY."
        )
    if status_code == 429:
        return PaddleOCRClientError(
            f"PaddleOCR service rate-limited the request (HTTP 429) at {url}."
        )
    if 400 <= status_code < 500:
        return PaddleOCRClientError(
            f"PaddleOCR request was rejected (HTTP {status_code}) at {url}. "
            "Check the endpoint and server configuration."
        )
    return PaddleOCRClientError(
        f"PaddleOCR service failed with HTTP {status_code} at {url}; check the service logs."
    )


def _request_error(error: httpx.HTTPError, url: str) -> PaddleOCRClientError:
    if isinstance(error, httpx.TimeoutException):
        return PaddleOCRClientError(
            f"PaddleOCR request to {url} timed out; adjust PAPERLESS_PADDLEOCR_*_TIMEOUT "
            "or inspect the serving container."
        )
    if isinstance(error, httpx.ConnectError):
        cause = error.__cause__
        if isinstance(cause, ssl.SSLError):
            return PaddleOCRClientError(
                f"PaddleOCR TLS failure at {url}; check TLS verification and CA settings."
            )
        if isinstance(cause, socket.gaierror):
            detail = "could not resolve the PaddleOCR server hostname"
        else:
            detail = "could not connect to the PaddleOCR server"
        return PaddleOCRClientError(
            f"PaddleOCR {detail} at {url}; check server URL and reachability."
        )
    if isinstance(error, httpx.TransportError):
        return PaddleOCRClientError(
            f"PaddleOCR TLS or transport failure at {url}; check TLS verification and CA settings."
        )
    return PaddleOCRClientError(f"PaddleOCR request failed at {url}: {type(error).__name__}.")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaddleOCRClientError(f"PaddleOCR response schema error: {label} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise PaddleOCRClientError(
            f"PaddleOCR response schema error: {label} must be a finite number."
        )
    return number


def _box(value: Any, index: int) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise PaddleOCRClientError(
            f"PaddleOCR response schema error: rec_boxes[{index}] must contain four coordinates."
        )
    return tuple(_number(part, f"rec_boxes[{index}]") for part in value)  # type: ignore[return-value]


def _validate_polygon(value: Any, index: int) -> None:
    if not isinstance(value, list):
        raise PaddleOCRClientError(
            f"PaddleOCR response schema error: rec_polys[{index}] must be an array of points."
        )
    for point_index, point in enumerate(value):
        if not isinstance(point, list) or len(point) != 2:
            raise PaddleOCRClientError(
                f"PaddleOCR response schema error: rec_polys[{index}][{point_index}] "
                "must contain two coordinates."
            )
        _number(point[0], f"rec_polys[{index}][{point_index}][0]")
        _number(point[1], f"rec_polys[{index}][{point_index}][1]")


def parse_response(payload: Any) -> list[RecognitionLine]:
    """Validate PaddleX's documented OCR response and retain API reading order."""
    if not isinstance(payload, dict):
        raise PaddleOCRClientError(
            "PaddleOCR response schema error: top-level JSON must be an object."
        )
    code = payload.get("errorCode")
    if isinstance(code, bool) or not isinstance(code, int):
        raise PaddleOCRClientError("PaddleOCR response schema error: errorCode must be an integer.")
    if code != 0:
        raise PaddleOCRClientError(f"PaddleOCR service reported errorCode {code}.")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise PaddleOCRClientError("PaddleOCR response schema error: result must be an object.")
    results = result.get("ocrResults")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise PaddleOCRClientError(
            "PaddleOCR response schema error: one page request must return exactly one OCR result."
        )
    pruned = results[0].get("prunedResult")
    if not isinstance(pruned, dict):
        raise PaddleOCRClientError(
            "PaddleOCR response schema error: prunedResult must be an object."
        )
    texts, scores, boxes = (
        pruned.get("rec_texts"),
        pruned.get("rec_scores"),
        pruned.get("rec_boxes"),
    )
    if not all(isinstance(value, list) for value in (texts, scores, boxes)):
        raise PaddleOCRClientError(
            "PaddleOCR response schema error: rec_texts, rec_scores, and rec_boxes must be arrays."
        )
    texts = cast(list[Any], texts)
    scores = cast(list[Any], scores)
    boxes = cast(list[Any], boxes)
    if not (len(texts) == len(scores) == len(boxes)):
        raise PaddleOCRClientError(
            "PaddleOCR response schema error: recognition arrays have different lengths."
        )
    polys = pruned.get("rec_polys")
    if polys is not None:
        if not isinstance(polys, list) or len(polys) != len(texts):
            raise PaddleOCRClientError(
                "PaddleOCR response schema error: rec_polys must match the recognition array length."
            )
        for index, polygon in enumerate(polys):
            _validate_polygon(polygon, index)

    lines: list[RecognitionLine] = []
    for index, (text, score, box) in enumerate(zip(texts, scores, boxes, strict=True)):
        if not isinstance(text, str):
            raise PaddleOCRClientError(
                f"PaddleOCR response schema error: rec_texts[{index}] must be a string."
            )
        numeric_score = _number(score, f"rec_scores[{index}]")
        if not 0 <= numeric_score <= 1:
            raise PaddleOCRClientError(
                f"PaddleOCR response schema error: rec_scores[{index}] must be between 0 and 1."
            )
        if not text.strip():
            continue
        lines.append(RecognitionLine(text=text.strip(), score=numeric_score, box=_box(box, index)))
    return lines


def ocr_image(image: Image.Image, config: PaddleOCRConfig) -> list[RecognitionLine]:
    """POST one page to PaddleX and return its validated, ordered text lines."""
    url = config.url
    payload = {
        "file": _png_base64(image),
        "fileType": 1,
        "visualize": False,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
    }
    headers = {"Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    connect_timeout = _timeout_value(config.connect_timeout, "connect")
    read_timeout = _timeout_value(config.read_timeout, "read")
    try:
        timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        verify = _tls_verify(config.verify_tls)
        http = httpx.Client(timeout=timeout, verify=verify)
    except PaddleOCRClientError:
        raise
    except Exception as error:
        raise PaddleOCRClientError(
            "PaddleOCR could not construct its HTTP client; check TLS and timeout configuration."
        ) from error

    with http:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as error:
                raise _request_error(error, url) from error
            if response.status_code in {429, 502, 503, 504} and attempt < _MAX_RETRIES:
                delay = _retry_after(response)
                if delay is None:
                    delay = min(0.5 * (2**attempt), _MAX_RETRY_AFTER_SECONDS)
                log.warning(
                    "PaddleOCR request received HTTP %d; retrying in %.1f seconds (%d/%d).",
                    response.status_code,
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise _status_error(response.status_code, url)
            try:
                return parse_response(response.json())
            except (json.JSONDecodeError, ValueError) as error:
                raise PaddleOCRClientError(
                    f"PaddleOCR returned invalid JSON at {url}; check the service endpoint."
                ) from error
    raise AssertionError("unreachable")
