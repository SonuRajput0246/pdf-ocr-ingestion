"""PyMuPDF page extraction and rendering helpers."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image

from .errors import PDFValidationError


@dataclass(frozen=True)
class PageLine:
    text: str
    bbox: tuple[float, float, float, float]


def _check_document(doc: fitz.Document, source: Path | str) -> None:
    if not getattr(doc, "is_pdf", True):
        raise PDFValidationError(f"{source} is not a PDF document")
    if doc.needs_pass:
        raise PDFValidationError(
            "Encrypted PDFs are not supported; remove the password before ingestion"
        )
    if doc.page_count < 1:
        raise PDFValidationError("The PDF has no pages")


def validate_pdf(path: Path) -> int:
    """Open a PDF, validate it, and return its page count."""

    try:
        doc = fitz.open(path)
    except Exception as exc:  # PyMuPDF raises several exception types
        raise PDFValidationError(f"Could not open PDF: {exc}") from exc

    try:
        _check_document(doc, path)
        return doc.page_count
    finally:
        doc.close()


def open_pdf(path: Path) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFValidationError(f"Could not open PDF: {exc}") from exc

    try:
        _check_document(doc, path)
    except Exception:
        doc.close()
        raise
    return doc


def extract_page_lines(page: fitz.Page) -> list[PageLine]:
    """Extract text lines with bounding boxes in reading order.

    PyMuPDF's block order is usually good. Sorting by vertical then horizontal
    position keeps simple single-column documents stable and makes the
    header/footer detector easy to reason about. Multi-column layouts would
    need a layout-aware extractor.
    """

    lines: list[PageLine] = []
    try:
        data = page.get_text("dict")
    except Exception:
        data = {}

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(
                str(span.get("text", "")) for span in line.get("spans", [])
            ).strip()
            if not text:
                continue
            raw_bbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
            bbox = tuple(float(value) for value in raw_bbox)
            lines.append(PageLine(text=text, bbox=bbox))  # type: ignore[arg-type]

    if not lines:
        try:
            blocks = page.get_text("blocks")
        except Exception:
            blocks = []
        for block in blocks:
            text = str(block[4]).strip()
            if not text:
                continue
            bbox = tuple(float(value) for value in block[:4])
            lines.append(PageLine(text=text, bbox=bbox))  # type: ignore[arg-type]

    lines.sort(key=lambda item: (round(item.bbox[1], 1), round(item.bbox[0], 1)))
    return lines


def join_lines(lines: list[PageLine]) -> str:
    return "\n".join(line.text for line in lines)


def render_page(page: fitz.Page, dpi: int) -> Image.Image:
    """Render one page to a Pillow image for OCR."""

    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
