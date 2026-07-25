"""Deterministic stdlib-only PaddleX Basic Serving ``/ocr`` stub for E2E."""

from __future__ import annotations

import base64
import binascii
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

STUB_MARKER = "PAPERLESS PADDLEOCR STUB OK"
_EXPECTED_FLAGS = {
    "fileType": 1,
    "visualize": False,
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
}


def _request_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "JSON body must be an object"
    file = payload.get("file")
    if not isinstance(file, str) or not file:
        return "file must be a non-empty Base64 image string"
    try:
        image = base64.b64decode(file, validate=True)
    except (binascii.Error, ValueError):
        return "file is not valid Base64"
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "file must encode a PNG image"
    for key, expected in _EXPECTED_FLAGS.items():
        if payload.get(key) != expected:
            return f"{key} must be {expected!r}"
    return None


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/ocr":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "only POST /ocr is available"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {error}"})
            return
        error = _request_error(payload)
        if error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": error})
            return
        self._send_json(
            HTTPStatus.OK,
            {
                "errorCode": 0,
                "result": {
                    "ocrResults": [
                        {
                            "prunedResult": {
                                "rec_texts": [STUB_MARKER, "Stub Rechnung 2026-0042"],
                                "rec_scores": [0.99, 0.98],
                                "rec_boxes": [[60, 40, 940, 120], [60, 160, 940, 240]],
                                "rec_polys": [
                                    [[60, 40], [940, 40], [940, 120], [60, 120]],
                                    [[60, 160], [940, 160], [940, 240], [60, 240]],
                                ],
                            }
                        }
                    ]
                },
            },
        )

    def log_message(self, fmt: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    print("PaddleX /ocr stub listening on :8080", flush=True)
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
