"""PaddleOCR option validation remains local and does not probe inference."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from paperless_paddleocr import ocrmypdf_plugin
from paperless_paddleocr.engine.engine import PaddleOCREngine


def _options(**overrides):
    values = {
        "paddleocr_server_url": "https://ocr.example",
        "paddleocr_endpoint": "/ocr",
        "paddleocr_api_key": "secret",
        "paddleocr_connect_timeout": 10,
        "paddleocr_read_timeout": 300,
        "paddleocr_verify_tls": "true",
        "paddleocr_ca_bundle": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_engine_binding_and_valid_defaults():
    assert isinstance(ocrmypdf_plugin.get_ocr_engine(), PaddleOCREngine)
    options = _options()
    ocrmypdf_plugin.check_options(options)
    assert options.paddleocr_verify_tls is True


@pytest.mark.parametrize(
    "name,value", [("paddleocr_connect_timeout", 0), ("paddleocr_read_timeout", "bad")]
)
def test_timeouts_must_be_positive(name, value):
    with pytest.raises(ValueError, match="positive"):
        ocrmypdf_plugin.check_options(_options(**{name: value}))


def test_url_endpoint_and_ca_bundle_validation(tmp_path):
    with pytest.raises(ValueError, match="absolute HTTP"):
        ocrmypdf_plugin.check_options(_options(paddleocr_server_url="ocr:8080"))
    with pytest.raises(ValueError, match="path"):
        ocrmypdf_plugin.check_options(_options(paddleocr_endpoint="https://ocr/ocr"))
    with pytest.raises(ValueError, match="readable"):
        ocrmypdf_plugin.check_options(_options(paddleocr_ca_bundle="/no/such/ca.pem"))
    ca = tmp_path / "ca.pem"
    ca.write_text("certificate", encoding="utf-8")
    options = _options(paddleocr_ca_bundle=str(ca))
    ocrmypdf_plugin.check_options(options)
    assert options.paddleocr_verify_tls == str(ca)


def test_disabled_tls_warns_and_conflicts_with_ca(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        options = _options(paddleocr_verify_tls="false")
        ocrmypdf_plugin.check_options(options)
    assert options.paddleocr_verify_tls is False
    assert "disabled" in caplog.text
    ca = tmp_path / "ca.pem"
    ca.write_text("certificate", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be combined"):
        ocrmypdf_plugin.check_options(
            _options(paddleocr_verify_tls=False, paddleocr_ca_bundle=str(ca))
        )
