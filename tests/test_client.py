"""PaddleX request encoding, response validation, and retry mapping."""

from __future__ import annotations

import base64
import ssl
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
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
        if callable(value):
            value()
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
    assert client.join_url("http://host:8080", "/ocr") == "http://host:8080/ocr"
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


def test_request_omits_authorization_without_token(monkeypatch):
    captured = _install_http(monkeypatch, [_response()])
    client.ocr_image(Image.new("RGB", (2, 2)), _config(api_key=""))
    assert "Authorization" not in captured["http"].calls[0][1]["headers"]


def test_disabled_tls_is_forwarded(monkeypatch):
    captured = _install_http(monkeypatch, [_response()])
    client.ocr_image(Image.new("RGB", (2, 2)), _config(verify_tls=False))
    assert captured["http"].kwargs["verify"] is False


def test_custom_ca_is_constructed_as_ssl_context(monkeypatch, tmp_path):
    ca = tmp_path / "custom-ca.pem"
    ca.write_text("not parsed by mocked context factory", encoding="utf-8")
    context = ssl.create_default_context()
    calls = []
    monkeypatch.setattr(
        client.ssl,
        "create_default_context",
        lambda *, cafile: calls.append(cafile) or context,
    )
    captured = _install_http(monkeypatch, [_response()])
    client.ocr_image(Image.new("RGB", (2, 2)), _config(verify_tls=str(ca)))
    assert calls == [str(ca)]
    assert captured["http"].kwargs["verify"] is context


def test_ca_and_http_client_construction_errors_are_actionable(monkeypatch):
    monkeypatch.setattr(
        client.ssl,
        "create_default_context",
        lambda *, cafile: (_ for _ in ()).throw(ssl.SSLError("bad certificate")),
    )
    with pytest.raises(client.PaddleOCRClientError, match="CA bundle"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config(verify_tls="/bad-ca.pem"))
    monkeypatch.setattr(
        client.httpx, "Client", lambda **kwargs: (_ for _ in ()).throw(ValueError())
    )
    with pytest.raises(client.PaddleOCRClientError, match="construct.*HTTP client"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())


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


@pytest.mark.parametrize("retry_after", ["not-a-delay", "61", "nan", "inf"])
def test_invalid_or_oversized_retry_after_uses_bounded_backoff(monkeypatch, retry_after):
    _install_http(monkeypatch, [_response(429, headers={"Retry-After": retry_after}), _response()])
    pauses = []
    monkeypatch.setattr(client.time, "sleep", pauses.append)
    client.ocr_image(Image.new("RGB", (2, 2)), _config())
    assert pauses == [0.5]


def test_http_date_retry_after_is_honoured_when_bounded(monkeypatch):
    retry_after = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    _install_http(monkeypatch, [_response(429, headers={"Retry-After": retry_after}), _response()])
    pauses = []
    monkeypatch.setattr(client.time, "sleep", pauses.append)
    client.ocr_image(Image.new("RGB", (2, 2)), _config())
    assert len(pauses) == 1
    assert 0 <= pauses[0] <= 5


def test_retry_exhaustion_stops_after_three_attempts(monkeypatch):
    captured = _install_http(monkeypatch, [_response(503), _response(503), _response(503)])
    monkeypatch.setattr(client.time, "sleep", lambda delay: None)
    with pytest.raises(client.PaddleOCRClientError, match="HTTP 503"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config())
    assert len(captured["http"].calls) == 3


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

    def tls_error():
        try:
            raise ssl.SSLError("certificate verify failed")
        except ssl.SSLError as error:
            raise httpx.ConnectError("tls") from error

    _install_http(monkeypatch, [tls_error])
    with pytest.raises(client.PaddleOCRClientError, match="TLS failure"):
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


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload["result"].update({"ocrResults": []}), "exactly one"),
        (lambda payload: payload["result"].update({"ocrResults": [{}, {}]}), "exactly one"),
        (
            lambda payload: payload["result"]["ocrResults"][0]["prunedResult"].update(
                {"rec_texts": [1]}
            ),
            "string",
        ),
        (
            lambda payload: payload["result"]["ocrResults"][0]["prunedResult"].update(
                {"rec_scores": ["high"]}
            ),
            "number",
        ),
        (
            lambda payload: payload["result"]["ocrResults"][0]["prunedResult"].update(
                {"rec_boxes": ["box"]}
            ),
            "four coordinates",
        ),
    ],
)
def test_response_recognition_types_and_single_page_are_validated(mutate, match):
    payload = _payload()
    mutate(payload)
    with pytest.raises(client.PaddleOCRClientError, match=match):
        client.parse_response(payload)


def test_polygons_and_nonfinite_values_are_validated():
    payload = _payload()
    payload["result"]["ocrResults"][0]["prunedResult"]["rec_polys"] = [
        [[0, 0], [10, 0], [10, 5], [0, 5]]
    ]
    assert client.parse_response(payload)[0].text == "Grüße Köln"

    for key, value in (("rec_scores", [float("nan")]), ("rec_boxes", [[0, 0, float("inf"), 1]])):
        payload = _payload()
        payload["result"]["ocrResults"][0]["prunedResult"][key] = value
        with pytest.raises(client.PaddleOCRClientError, match="finite"):
            client.parse_response(payload)

    payload = _payload()
    payload["result"]["ocrResults"][0]["prunedResult"]["rec_polys"] = [[[0, float("nan")]]]
    with pytest.raises(client.PaddleOCRClientError, match="finite"):
        client.parse_response(payload)


@pytest.mark.parametrize(
    "name,value", [("connect_timeout", float("nan")), ("read_timeout", float("inf"))]
)
def test_nonfinite_timeouts_are_rejected_before_client_construction(monkeypatch, name, value):
    _install_http(monkeypatch, [_response()])
    with pytest.raises(client.PaddleOCRClientError, match="finite positive"):
        client.ocr_image(Image.new("RGB", (2, 2)), _config(**{name: value}))
