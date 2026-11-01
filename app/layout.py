"""Statistical header/footer detection and removal."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import fitz

from .extractor import PageLine, extract_page_lines

_DIGITS_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")


def furniture_key(text: str) -> str:
    """Normalise a line for repetition counting.

    Replacing digits means ``Page 1 of 3`` and ``Page 2 of 3`` collapse to the
    same key, which is what makes dynamic page-number footers detectable.
    """

    collapsed = _WHITESPACE_RE.sub(" ", text.casefold()).strip()
    return _DIGITS_RE.sub("#", collapsed)


@dataclass(frozen=True)
class FurnitureProfile:
    keys: tuple[str, ...] = ()
    margin: float = 72.0
    threshold: float = 0.60
    page_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "keys": list(self.keys),
            "margin": self.margin,
            "threshold": self.threshold,
            "page_count": self.page_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FurnitureProfile:
        return cls(
            keys=tuple(str(key) for key in data.get("keys", [])),
            margin=float(data.get("margin", 72.0)),
            threshold=float(data.get("threshold", 0.60)),
            page_count=int(data.get("page_count", 0)),
        )

    def remove(self, lines: list[PageLine]) -> tuple[list[PageLine], int]:
        if not self.keys:
            return lines, 0

        kept: list[PageLine] = []
        removed = 0
        for line in lines:
            if furniture_key(line.text) in self.keys:
                removed += 1
            else:
                kept.append(line)
        return kept, removed


def detect_furniture(
    doc: fitz.Document,
    *,
    margin: float = 72.0,
    threshold: float = 0.60,
    min_pages: int = 2,
) -> FurnitureProfile:
    """Detect lines in the top/bottom margin that repeat across pages.

    A line must appear on at least ``max(min_pages, ceil(page_count * threshold))``
    pages. A single-page document is never treated as having furniture, because
    repetition cannot be measured.
    """

    page_count = doc.page_count
    if page_count < min_pages:
        return FurnitureProfile(
            margin=margin, threshold=threshold, page_count=page_count
        )

    occurrences: dict[str, set[int]] = {}
    for page_index in range(page_count):
        try:
            page = doc[page_index]
            page_height = page.rect.height
            lines = extract_page_lines(page)
        except Exception:
            continue

        for line in lines:
            y0, y1 = line.bbox[1], line.bbox[3]
            if y0 >= margin and y1 <= page_height - margin:
                continue
            key = furniture_key(line.text)
            if len(key) < 3:
                continue
            occurrences.setdefault(key, set()).add(page_index)

    required = max(min_pages, math.ceil(page_count * threshold))
    keys = tuple(
        sorted(key for key, pages in occurrences.items() if len(pages) >= required)
    )
    return FurnitureProfile(
        keys=keys,
        margin=margin,
        threshold=threshold,
        page_count=page_count,
    )
