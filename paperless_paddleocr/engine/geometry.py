"""Geometry helpers for the invisible hOCR text layer."""

from __future__ import annotations

from collections.abc import Sequence

BBox = tuple[int, int, int, int]
_GAP_WEIGHT = 0.5


def estimate_word_boxes(words: Sequence[str], box: BBox) -> list[BBox]:
    """Partition a returned line box proportionally between its words."""
    if not words:
        return []
    x0, y0, x1, y1 = box
    if len(words) == 1:
        return [(x0, y0, x1, y1)]
    width = x1 - x0
    weights = [max(1, len(word)) for word in words]
    total = sum(weights) + _GAP_WEIGHT * (len(words) - 1)
    gap = round(width * _GAP_WEIGHT / total)
    cursor = x0
    boxes: list[BBox] = []
    for index, weight in enumerate(weights):
        right = x1 if index == len(weights) - 1 else cursor + round(width * weight / total)
        boxes.append((cursor, y0, right, y1))
        cursor = right + gap
    return boxes
