"""Exercise the real PaddleX Basic Serving OCR contract without dependencies."""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import struct
import time
import urllib.error
import urllib.request
import zlib
from typing import Any
from urllib.parse import urljoin

_FONT = {
    " ": ("000",) * 7,
    "A": ("010", "101", "101", "111", "101", "101", "101"),
    "E": ("111", "100", "100", "110", "100", "100", "111"),
    "G": ("011", "100", "100", "101", "101", "101", "011"),
    "K": ("101", "101", "110", "100", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "100", "100", "111"),
    "N": ("101", "111", "111", "101", "101", "101", "101"),
    "O": ("010", "101", "101", "101", "101", "101", "010"),
    "R": ("110", "101", "101", "110", "101", "101", "101"),
    "S": ("011", "100", "100", "010", "001", "001", "110"),
    "U": ("101", "101", "101", "101", "101", "101", "111"),
    "Ü": ("101", "000", "101", "101", "101", "101", "111"),
    "Ö": ("101", "000", "010", "101", "101", "101", "010"),
}
_TRANSIENT_HTTP_STATUSES = {500, 502, 503, 504}
_MAX_ERROR_BODY_BYTES = 512


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def _german_test_image() -> str:
    """Encode a dependency-free PNG visibly reading ``GRÜSSE AUS KÖLN``."""
    text, scale, width, height = "GRÜSSE AUS KÖLN", 8, 480, 96
    pixels = bytearray(b"\xff" * (width * height * 3))
    x, y = 20, 20
    for char in text:
        for row, bits in enumerate(_FONT[char]):
            for column, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            offset = ((y + row * scale + dy) * width + x + column * scale + dx) * 3
                            pixels[offset : offset + 3] = b"\x00\x00\x00"
        x += 4 * scale
    rows = b"".join(
        b"\x00" + pixels[row * width * 3 : (row + 1) * width * 3] for row in range(height)
    )
    png = b"\x89PNG\r\n\x1a\n" + _chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    )
    png += _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def _validate(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("errorCode") != 0:
        raise SystemExit(f"PaddleX returned unsuccessful response: {payload!r}")
    try:
        result = payload["result"]["ocrResults"]
        pruned = result[0]["prunedResult"]
        arrays = [
            pruned["rec_texts"],
            pruned["rec_scores"],
            pruned["rec_boxes"],
            pruned["rec_polys"],
        ]
    except (KeyError, IndexError, TypeError) as error:
        raise SystemExit(
            f"PaddleX response does not match the PP-OCRv6 contract: {payload!r}"
        ) from error
    if len(result) != 1 or not all(isinstance(value, list) for value in arrays):
        raise SystemExit("PaddleX response needs one ocrResults entry and four result arrays.")
    if len({len(value) for value in arrays}) != 1:
        raise SystemExit("PaddleX recognition result arrays have inconsistent lengths.")
    texts, scores, boxes, polygons = arrays
    if not texts:
        raise SystemExit("PaddleX returned no recognition results for the German smoke image.")
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            continue
        score, box, polygon = scores[index], boxes[index], polygons[index]
        if (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
            and isinstance(box, list)
            and len(box) == 4
            and isinstance(polygon, list)
            and polygon
        ):
            return
        raise SystemExit(
            "PaddleX recognized text without a matching nonempty score, box, and polygon entry."
        )
    raise SystemExit("PaddleX returned only blank recognition strings for the German smoke image.")


def _bounded_error_body(error: urllib.error.HTTPError) -> str:
    body = error.read(_MAX_ERROR_BODY_BYTES).decode("utf-8", errors="replace").strip()
    # Do not print accidental credentials if a proxy returns an echoed header/body.
    return re.sub(
        r"(?i)(authorization|api[_-]?key|token|password)\s*[=:]\s*[^\s,}]+",
        r"\1=[redacted]",
        body,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080", help="PaddleX service base URL")
    parser.add_argument(
        "--timeout", type=int, default=900, help="maximum model-startup wait in seconds"
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    endpoint = urljoin(args.url.rstrip("/") + "/", "ocr")
    request_body = json.dumps(
        {
            "file": _german_test_image(),
            "fileType": 1,
            "visualize": False,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": False,
        }
    ).encode()
    deadline, last_error = time.monotonic() + args.timeout, "service has not answered"
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                endpoint,
                data=request_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                _validate(json.loads(response.read()))
            print("PaddleX PP-OCRv6 /ocr contract smoke passed")
            return
        except urllib.error.HTTPError as error:
            body = _bounded_error_body(error)
            detail = f"HTTP {error.code}" + (f": {body}" if body else "")
            if error.code not in _TRANSIENT_HTTP_STATUSES:
                raise SystemExit(
                    f"PaddleX rejected the smoke request permanently ({detail})."
                ) from error
            last_error = detail
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        except ValueError as error:
            raise SystemExit(f"PaddleX returned an invalid /ocr response: {error}") from error
        if time.monotonic() < deadline:
            time.sleep(5)
    raise SystemExit(f"PaddleX did not become inference-ready within {args.timeout}s: {last_error}")


if __name__ == "__main__":
    main()
