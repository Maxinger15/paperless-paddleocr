"""Local Tesseract OSD used only for page rotation."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("paperless.paddleocr.osd")
_TIMEOUT_SECONDS = 60.0
_osd_warned = False


def _parse_tesseract_output(output: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.decode(errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        fields[key.strip()] = value.strip()
    return fields


def detect_orientation(input_file: Path) -> tuple[int, float]:
    global _osd_warned
    try:
        proc = subprocess.run(
            ["tesseract", "-l", "osd", "--psm", "0", str(input_file), "stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        if not _osd_warned:
            log.warning("Tesseract OSD is unavailable; pages keep their stored orientation.")
            _osd_warned = True
        return 0, 0.0
    except subprocess.CalledProcessError as error:
        output = error.output or b""
        if b"Too few characters" in output or b"Image too large" in output:
            return 0, 0.0
        if not _osd_warned:
            log.warning(
                "Tesseract OSD failed; pages keep their stored orientation. Output: %s",
                output.decode(errors="replace").strip()[:200],
            )
            _osd_warned = True
        return 0, 0.0
    except subprocess.TimeoutExpired:
        return 0, 0.0
    fields = _parse_tesseract_output(proc.stdout)
    return int(fields.get("Orientation in degrees", 0)), float(
        fields.get("Orientation confidence", 0.0)
    )
