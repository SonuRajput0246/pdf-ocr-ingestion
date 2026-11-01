"""Shared test fixtures and synthetic PDF builders."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from app.config import Settings
from app.models import JobOptions, JobRecord
from app.ocr import StubOCREngine
from app.service import IngestionService
from app.store import FileJobStore

DEFAULT_OCR_TEXT = (
    "OCR fallback text with enough alphanumeric characters to be considered usable."
)


def make_text_pdf(
    path: Path,
    *,
    pages: int = 3,
    header: str = "Synthetic Header",
    footer: bool = True,
    body: str | None = None,
) -> Path:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page(width=595, height=842)
            if header:
                page.insert_text((72, 36), header, fontsize=8)
            if footer:
                page.insert_text((72, 812), f"Page {page_number} of {pages}", fontsize=8)
            page.insert_text((72, 100), f"Page {page_number} body text.", fontsize=12)
            page.insert_text(
                (72, 130),
                body
                or (
                    "This synthetic document contains enough alphanumeric text "
                    "for extraction and OCR fallback checks."
                ),
                fontsize=10,
            )
        doc.save(path, garbage=4, deflate=True)
    finally:
        doc.close()
    return path


def _image_bytes(label: str) -> bytes:
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 580, 780), outline="black", width=2)
    draw.text((40, 40), label, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_image_pdf(path: Path, *, pages: int = 2) -> Path:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=_image_bytes(f"Scanned page {page_number}"))
        doc.save(path, garbage=4, deflate=True)
    finally:
        doc.close()
    return path


def make_mixed_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        first = doc.new_page(width=595, height=842)
        first.insert_text((72, 100), "Text layer page with enough alphanumeric content.", fontsize=12)
        for page_number in (2, 3):
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=_image_bytes(f"Scanned page {page_number}"))
        doc.save(path, garbage=4, deflate=True)
    finally:
        doc.close()
    return path


def make_encrypted_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Encrypted synthetic document.", fontsize=12)
        doc.save(
            path,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    finally:
        doc.close()
    return path


def make_service(
    tmp_path: Path,
    *,
    ocr_engine: object | None = None,
    **settings_overrides: object,
) -> tuple[Settings, IngestionService, object]:
    settings = Settings(
        data_dir=tmp_path / "data",
        ocr_mode="auto",
        min_text_chars=20,
        remove_furniture=True,
    )
    if settings_overrides:
        settings = settings.with_overrides(**settings_overrides)

    engine = ocr_engine or StubOCREngine(DEFAULT_OCR_TEXT, confidence=0.95)
    service = IngestionService(
        settings,
        FileJobStore(settings.data_dir),
        engine,  # type: ignore[arg-type]
    )
    return settings, service, engine


def make_job_record(
    *,
    tenant_id: str = "tenant-a",
    application_id: str = "app-a",
    job_id: str | None = None,
    options: JobOptions | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        application_id=application_id,
        source_name="sample.pdf",
        source_sha256="0" * 64,
        source_bytes=1234,
        options=(options or JobOptions()).to_dict(),
        pages_total=3,
    )
