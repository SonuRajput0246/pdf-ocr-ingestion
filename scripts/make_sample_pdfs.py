"""Generate synthetic sample PDFs and gold text for the demo.

The PDFs contain no client data. They are deliberately simple: a three-page
text-layer document, an image-only version of the same document, and a mixed
document whose first page has a text layer and whose remaining pages are scans.
"""

from __future__ import annotations

from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GOLD_DIR = DATA_DIR / "gold"

PAGES = [
    {
        "title": "Synthetic Community Health Study Protocol",
        "sections": [
            (
                "1. Purpose",
                "This synthetic document exists only to exercise PDF text extraction and OCR. "
                "It describes a fictional community health study and contains no real participant, "
                "client or protocol data. The text is intentionally ordinary so that extraction "
                "quality can be compared with a known reference.",
            ),
            (
                "2. Study design",
                "The fictional study is a two-site, cross-sectional survey of household water "
                "storage practices. Adults aged eighteen years or older are invited to complete "
                "a short questionnaire during a routine community visit. The survey has no "
                "intervention, no biological sample collection and no follow-up visit.",
            ),
            (
                "3. Participant selection",
                "Participants are selected through a simple random sample of households in two "
                "fictional districts. Exclusion criteria are limited to people who cannot provide "
                "informed consent. The sample size is fixed at four hundred households, with an "
                "equal allocation between the two sites.",
            ),
        ],
    },
    {
        "title": None,
        "sections": [
            (
                "4. Consent procedure",
                "A trained field worker reads the information sheet aloud and answers questions "
                "before any data are recorded. Consent is documented with a signature or a "
                "witnessed thumbprint. Participation is voluntary and can be stopped at any time "
                "without affecting access to routine services.",
            ),
            (
                "5. Data protection",
                "Paper forms are stored in a locked cabinet at each site. Electronic records use "
                "study codes rather than names. The linkage file is held separately by the site "
                "coordinator and is available only to the named investigators. Data are retained "
                "for five years after the end of the fictional study.",
            ),
            (
                "6. Risks and benefits",
                "The expected risk is limited to the time needed to complete the questionnaire. "
                "There is no direct individual benefit. The fictional study may help the district "
                "plan water-storage advice, but no participant should expect a personal benefit "
                "from taking part.",
            ),
        ],
    },
    {
        "title": None,
        "sections": [
            (
                "7. Data management",
                "Each completed form is checked for missing values before it leaves the site. "
                "Double entry is used for the first fifty forms, after which a ten percent random "
                "sample is verified. Discrepancies are resolved against the paper form by the "
                "site coordinator.",
            ),
            (
                "8. Community considerations",
                "The fictional districts are invited to comment on the questionnaire wording "
                "before fieldwork begins. A community liaison point is available during the "
                "survey. Results will be summarised in a short plain-language note for local "
                "health committees.",
            ),
            (
                "9. Approval and contact",
                "This synthetic protocol is not a real ethics submission. It exists only as demo "
                "data for the PDF and OCR ingestion pipeline. Any resemblance to a real study is "
                "coincidental. The named contact is the demo maintainer.",
            ),
        ],
    },
]


def _write_page(page: fitz.Page, content: dict, page_number: int, total: int) -> None:
    width = page.rect.width
    height = page.rect.height
    margin = 72.0

    page.insert_text(
        (margin, 36),
        "Synthetic Community Health Study Protocol - Confidential",
        fontsize=8,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )
    page.insert_text(
        (margin, height - 30),
        f"Page {page_number} of {total}",
        fontsize=8,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )
    page.insert_text(
        (width - margin - 155, height - 30),
        "Demo document - no client data",
        fontsize=8,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )

    y = 76.0
    if content["title"]:
        rect = fitz.Rect(margin, y, width - margin, y + 52)
        remaining = page.insert_textbox(
            rect,
            content["title"],
            fontsize=18,
            fontname="hebo",
            lineheight=1.2,
        )
        if remaining < 0:
            raise RuntimeError("Title did not fit on the sample page")
        y += rect.height - remaining + 18

    for heading, body in content["sections"]:
        heading_rect = fitz.Rect(margin, y, width - margin, y + 24)
        remaining = page.insert_textbox(
            heading_rect,
            heading,
            fontsize=12,
            fontname="hebo",
            lineheight=1.2,
        )
        if remaining < 0:
            raise RuntimeError(f"Heading did not fit: {heading}")
        y += heading_rect.height - remaining + 4

        body_rect = fitz.Rect(margin, y, width - margin, height - 64)
        remaining = page.insert_textbox(
            body_rect,
            body,
            fontsize=10.5,
            fontname="helv",
            lineheight=1.35,
        )
        if remaining < 0:
            raise RuntimeError(f"Body did not fit on page {page_number}: {heading}")
        y += body_rect.height - remaining + 16

    if y > height - 64:
        raise RuntimeError(f"Content overflowed page {page_number}")


def _gold_page(content: dict) -> str:
    parts: list[str] = []
    if content["title"]:
        parts.append(content["title"])
    for heading, body in content["sections"]:
        parts.extend([heading, body])
    return "\n\n".join(parts)


def _write_gold(name: str) -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    for index, content in enumerate(PAGES, start=1):
        chunks.append(f"--- page {index} ---\n{_gold_page(content)}")
    (GOLD_DIR / name).write_text("\n\n".join(chunks) + "\n", encoding="utf-8")


def _make_text_pdf(path: Path) -> None:
    doc = fitz.open()
    for index, content in enumerate(PAGES, start=1):
        page = doc.new_page(width=595, height=842)
        _write_page(page, content, index, len(PAGES))
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def _make_scanned_pdf(source_path: Path, path: Path) -> None:
    source = fitz.open(source_path)
    output = fitz.open()
    try:
        for page in source:
            pixmap = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
            image_page = output.new_page(
                width=page.rect.width, height=page.rect.height
            )
            image_page.insert_image(image_page.rect, stream=pixmap.tobytes("png"))
        output.save(path, garbage=4, deflate=True)
    finally:
        output.close()
        source.close()


def _make_mixed_pdf(source_path: Path, path: Path) -> None:
    source = fitz.open(source_path)
    output = fitz.open()
    try:
        first = output.new_page(width=595, height=842)
        _write_page(first, PAGES[0], 1, len(PAGES))
        for index in range(1, source.page_count):
            page = source[index]
            pixmap = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
            image_page = output.new_page(
                width=page.rect.width, height=page.rect.height
            )
            image_page.insert_image(
                image_page.rect, stream=pixmap.tobytes("png")
            )
        output.save(path, garbage=4, deflate=True)
    finally:
        output.close()
        source.close()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    text_pdf = DATA_DIR / "sample_text_layer.pdf"
    scanned_pdf = DATA_DIR / "sample_scanned.pdf"
    mixed_pdf = DATA_DIR / "sample_mixed.pdf"

    _make_text_pdf(text_pdf)
    _make_scanned_pdf(text_pdf, scanned_pdf)
    _make_mixed_pdf(text_pdf, mixed_pdf)

    for name in (
        "sample_text_layer.txt",
        "sample_scanned.txt",
        "sample_mixed.txt",
    ):
        _write_gold(name)

    print(f"Wrote {text_pdf}")
    print(f"Wrote {scanned_pdf}")
    print(f"Wrote {mixed_pdf}")
    print(f"Wrote gold text under {GOLD_DIR}")


if __name__ == "__main__":
    main()
