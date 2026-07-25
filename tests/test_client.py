"""PaddleX request encoding, response validation, and retry mapping."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from paperless_paddleocr.engine import client


def _config(**overrides):
    values = {
        "server_url": "https://ocr.example/service",
        "endpoint": "/ocr",
        "api_key": "secret",
        "connect_timeout": 10,
        "read_timeout": 300,
        "verify_tls": True,
    }
    values.update(overrides)
    return client.PaddleOCRConfig(**values)


def _payload(**overrides):
    result = {
        "errorCode": 0,
        "result": {
            "ocrResults": [
                {
                    "prunedResult": {
                        "rec_texts": ["Grüße Köln"],
                        "rec_scores": [0.876],
                        "rec_boxes": [[-3, 4, 99, 50]],
                    }
                }
            ]
        },
    }
    result.update(overrides)
    return result


class _HTTP:
    def __init__(self, responses, **kwargs):
        self.responses = iter(responses)
        self.kwargs = kwargs
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def _response(status=200, payload=None, headers=None):
    return httpx.Response(status, json=_payload() if payload is None else payload, headers=headers)


def _install_http(monkeypatch, responses):
    captured = {}

    def factory(**kwargs):
        http = _HTTP(responses, **kwargs)
        captured["http"] = http
        return http

    monkeypatch.setattr(client.httpx, "Client", factory)
    return captured


def test_url_validation_and_joining():
    assert client.join_url("https://host/base/", "ocr") == "https://host/base/ocr"
    with pytest.raises(client.PaddleOCRClientError, match="HTTP"):
        client.normalize_server_url("host/ocr")
    with pytest.raises(client.PaddleOCRClientError, match="path"):
        client.normalize_endpoint("https://host/ocr")


def test_request_is_lossless_png_base64_with_auth_and_options(monkeypatch):
    captured = _install_http(monkeypatch, [_response()])
    lines = client.ocr_image(Image.new("RGB", (8, 6), "white"), _config())
    http = captured["http"]
    url, request = http.calls[0]
    assert url == "https://ocr.example/service/ocr"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"] | {"file": "present"} == {
        "file": "present",
        "fileType": 1,
        "visualize": False,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
    }
    assert base64.b64decode(request["json"]["file"]).startswith(b"\x89PNG")
    assert lines[0].text == "Grüße Köln"
    assert http.kwargs["verify"] is True


@pytest.mark.parametrize("verify", [False, "/tmp/custom-ca.pem"])
def test_tls_configuration_is_forwarded(monkeypatch, verify):
    captured = _install_http(monkeypatch, [_response()])
    client.ocr_image(Image.new("RGB", (2, 2)), _config(verify_tls=verify))
    assert captured["http"].kwargs["verify"] == verify


def test_timeout_values_are_forwarded(monkeypatch):
    captured = _install_http(monkeypatch, [_response()])
    client.ocr_image(Image.new("RGB", (2, 2)), _config(connect_timeout=7, read_timeout=42))
    timeout = captured["http"].kwargs["timeout"]
    assert timeout.connect == 7
    assert timeout.read == 42


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retryable_statuses_are_retried_at_most_twice(monkeypatch, status):
    captured = _install_http(monkeypatch, [_response(status), _response(status), _response()])
    pauses = []
    monkeypatch.setattr(client.time, "sleep", pauses.append)
    client.ocr_image(Image.new("RGB", (2, 2)), _config())
    assert len(captured["http"].calls) == 3
    assert pauses == [0.5, 1.0]


def test_retry_after_is_honoured_when_bounded(monkeypatch):
    _install_http(monkeypatch, [_response(429, headers={"Retry-After": "3"}), _response()])
    pauses = []
    monkeypatch.setattr(client.time, "sleep", pauses.append)
    client.ocr_image(Image.new("RGB", (2, 2)), _config())
    assert pauses == [3]


@pytest.mark.parametrize(
    "status,match",
    [(400, "HTTP 400"), (401, "authentication"), (403, "authentication"), (500, "HTTP 500")],
)
def test_nonretryable_statuses_are_actionable(monkeypatch, status, match):
    _install_http(monkeypatch, [_response(status)])
    with pytest.raises(client.PaddleOCRClientError, match=match):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())


def test_transport_errors_are_actionable(monkeypatch):
    _install_http(monkeypatch, [httpx.ConnectError("no route")])
    with pytest.raises(client.PaddleOCRClientError, match="connect"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())
    _install_http(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(client.PaddleOCRClientError, match="timed out"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())


def test_invalid_json_is_mapped_without_response_body(monkeypatch):
    response = SimpleNamespace(
        status_code=200, json=lambda: (_ for _ in ()).throw(ValueError("not json"))
    )
    _install_http(monkeypatch, [response])
    with pytest.raises(client.PaddleOCRClientError, match="invalid JSON"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())


def test_empty_response_and_schema_errors():
    payload = _payload()
    payload["result"]["ocrResults"][0]["prunedResult"] = {
        "rec_texts": [],
        "rec_scores": [],
        "rec_boxes": [],
    }
    assert client.parse_response(payload) == []
    payload = _payload()
    payload["result"]["ocrResults"][0]["prunedResult"]["rec_scores"] = []
    with pytest.raises(client.PaddleOCRClientError, match="different lengths"):
        client.parse_response(payload)
    with pytest.raises(client.PaddleOCRClientError, match="errorCode 7"):
        client.parse_response(_payload(errorCode=7))
