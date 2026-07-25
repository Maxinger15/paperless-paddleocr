"""Local NumPy/Pillow projection-profile deskew estimation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

MAX_SKEW_DEGREES = 5.0
_COARSE_STEP = 0.5
_FINE_STEP = 0.1
_TARGET_WIDTH = 1200


def _score(image: Image.Image, angle: float) -> float:
    rotated = image.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=255)
    profile = (255 - np.asarray(rotated, dtype=np.int64)).sum(axis=1)
    delta = profile[1:] - profile[:-1]
    return float((delta * delta).sum())


def estimate_skew(input_file: Path) -> float:
    with Image.open(input_file) as raw:
        image = raw.convert("L")
        if image.width > _TARGET_WIDTH:
            image = image.resize(
                (_TARGET_WIDTH, max(1, round(image.height * _TARGET_WIDTH / image.width)))
            )
        array = np.asarray(image)
        binary = Image.fromarray(np.where(array < array.mean(), 0, 255).astype(np.uint8))
    candidates = [i * _COARSE_STEP for i in range(-10, 11)]
    best = max(candidates, key=lambda angle: _score(binary, angle))
    fine = [
        best + i * _FINE_STEP
        for i in range(-5, 6)
        if abs(best + i * _FINE_STEP) <= MAX_SKEW_DEGREES
    ]
    best = max(fine, key=lambda angle: _score(binary, angle))
    return 0.0 if abs(best) >= MAX_SKEW_DEGREES else best
