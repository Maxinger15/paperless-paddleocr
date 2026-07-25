"""PaddleOCREngine hOCR conversion and local OSD integration."""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from paperless_paddleocr.engine import client, osd
from paperless_paddleocr.engine.engine import PaddleOCREngine, _config


def _options(**overrides):
    values = {
        "paddleocr_server_url": "http://ocr:8080",
        "paddleocr_endpoint": "/ocr",
        "paddleocr_api_key": "",
        "paddleocr_connect_timeout": 10,
        "paddleocr_read_timeout": 300,
        "paddleocr_verify_tls": True,
        "languages": ["deu"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _image(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (100, 60), "white").save(path)
    return path


def test_hocr_clamps_boxes_converts_confidence_and_preserves_order(tmp_path, monkeypatch):
    lines = [
        client.RecognitionLine("Grüße Welt", 0.876, (-10, 5, 130, 40)),
        client.RecognitionLine("zweite Zeile", 0.2, (2, 41, 90, 59)),
    ]
    monkeypatch.setattr(client, "ocr_image", lambda image, config: lines)
    hocr, text = tmp_path / "out.hocr", tmp_path / "out.txt"
    PaddleOCREngine.generate_hocr(_image(tmp_path), hocr, text, _options())
    rendered = hocr.read_text(encoding="utf-8")
    assert "bbox 0 5 100 40" in rendered
    assert "x_wconf 88" in rendered
    assert text.read_text(encoding="utf-8") == "Grüße Welt\nzweite Zeile"


def test_empty_recognition_writes_empty_hocr_page(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "ocr_image", lambda image, config: [])
    hocr, text = tmp_path / "out.hocr", tmp_path / "out.txt"
    PaddleOCREngine.generate_hocr(_image(tmp_path), hocr, text, _options())
    assert text.read_text(encoding="utf-8") == ""
    assert 'class="ocr_page"' in hocr.read_text(encoding="utf-8")


def test_osd_is_only_orientation_mechanism(tmp_path, monkeypatch):
    monkeypatch.setattr(osd, "detect_orientation", lambda path: (90, 12.5))
    orientation = PaddleOCREngine.get_orientation(_image(tmp_path), _options())
    assert (orientation.angle, orientation.confidence) == (90, 12.5)


def test_languages_and_creator_tag():
    assert PaddleOCREngine.languages(_options(languages=["eng", "deu"])) >= {"eng", "deu"}
    assert "PaddleOCR" in PaddleOCREngine.creator_tag(_options())


def test_engine_config_resolves_tls_boolean_and_ca_bundle(tmp_path):
    assert _config(_options(paddleocr_verify_tls="false")).verify_tls is False
    assert _config(_options(paddleocr_verify_tls="true")).verify_tls is True
    ca = tmp_path / "ca.pem"
    ca.write_text("certificate", encoding="utf-8")
    configured = _config(_options(paddleocr_verify_tls="true", paddleocr_ca_bundle=str(ca)))
    assert configured.verify_tls == str(ca)
