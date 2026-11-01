from __future__ import annotations

import pytest

from app.errors import JobNotFound, OCREngineUnavailable, PDFValidationError
from app.models import JobOptions
from app.ocr import OCRResult
from tests.helpers import (
    make_encrypted_pdf,
    make_image_pdf,
    make_mixed_pdf,
    make_service,
    make_text_pdf,
)


class FlakyOCREngine:
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def image_to_text(self, image, *, language: str = "eng", psm: int = 3):
        self.calls += 1
        if self.calls == 1:
            raise OCREngineUnavailable("simulated OCR failure")
        return OCRResult(
            text="Recovered OCR text with enough alphanumeric characters.",
            confidence=0.9,
            engine=self.name,
        )


def test_text_pdf_uses_text_layer_and_removes_furniture(tmp_path):
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=3)
    settings, service, engine = make_service(tmp_path)

    job, created = service.create_job(pdf, "tenant-a", "app-a")
    assert created is True
    assert job.pages_total == 3

    job = service.run_job("tenant-a", "app-a", job.job_id)
    assert job.status == "completed"
    assert job.pages_text == 3
    assert job.pages_ocr == 0
    assert job.pages_failed == 0
    assert job.document_type == "text"
    assert engine.calls == 0

    pages = service.list_pages("tenant-a", "app-a", job.job_id)
    assert len(pages) == 3
    first = pages[0]
    assert first.method == "text"
    assert first.quality == "good"
    assert "Synthetic Header" not in first.text
    assert "Page 1 of 3" not in first.text
    assert "Page 1 body text." in first.text
    assert first.furniture_removed >= 2

    result = service.get_result("tenant-a", "app-a", job.job_id)
    assert len(result["pages"]) == 3


def test_image_pdf_falls_back_to_ocr(tmp_path):
    pdf = make_image_pdf(tmp_path / "scan.pdf", pages=2)
    settings, service, engine = make_service(tmp_path)

    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    job = service.run_job("tenant-a", "app-a", job.job_id)

    assert job.status == "completed"
    assert job.pages_ocr == 2
    assert job.pages_text == 0
    assert job.pages_failed == 0
    assert job.document_type == "scanned"
    assert engine.calls == 2
    assert job.mean_ocr_confidence == 0.95

    pages = service.list_pages("tenant-a", "app-a", job.job_id)
    assert all(page.method == "ocr" for page in pages)
    assert all(page.confidence == 0.95 for page in pages)


def test_ocr_mode_never_leaves_image_pages_empty(tmp_path):
    pdf = make_image_pdf(tmp_path / "scan.pdf", pages=2)
    settings, service, engine = make_service(tmp_path, ocr_mode="never")

    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    job = service.run_job("tenant-a", "app-a", job.job_id)

    assert job.status == "completed"
    assert job.pages_empty == 2
    assert job.pages_ocr == 0
    assert job.document_type == "empty"
    assert engine.calls == 0


def test_ocr_mode_always_ocrs_text_pages(tmp_path):
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=3)
    settings, service, engine = make_service(tmp_path, ocr_mode="always")

    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    job = service.run_job("tenant-a", "app-a", job.job_id)

    assert job.status == "completed"
    assert job.pages_ocr == 3
    assert job.pages_text == 0
    assert engine.calls == 3


def test_failed_page_is_checkpointed_and_retried(tmp_path):
    pdf = make_image_pdf(tmp_path / "scan.pdf", pages=2)
    flaky = FlakyOCREngine()
    settings, service, engine = make_service(tmp_path, ocr_engine=flaky)

    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    job = service.run_job("tenant-a", "app-a", job.job_id)

    assert job.status == "completed_with_errors"
    assert job.pages_done == 2
    assert job.pages_failed == 1
    assert flaky.calls == 2
    pages = service.list_pages("tenant-a", "app-a", job.job_id)
    assert pages[0].status == "error"
    assert pages[0].error
    assert pages[1].status == "ok"

    job = service.run_job(
        "tenant-a", "app-a", job.job_id, retry_failed=True
    )
    assert job.status == "completed"
    assert job.pages_failed == 0
    assert flaky.calls == 3
    pages = service.list_pages("tenant-a", "app-a", job.job_id)
    assert pages[0].status == "ok"
    assert pages[0].method == "ocr"


def test_create_job_is_idempotent_and_rerun_skips_pages(tmp_path):
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=3)
    settings, service, engine = make_service(tmp_path)

    first, first_created = service.create_job(pdf, "tenant-a", "app-a")
    second, second_created = service.create_job(pdf, "tenant-a", "app-a")

    assert first_created is True
    assert second_created is False
    assert first.job_id == second.job_id
    assert service.store.source_path("tenant-a", "app-a", first.job_id).exists()

    first = service.run_job("tenant-a", "app-a", first.job_id)
    assert first.status == "completed"
    assert engine.calls == 0

    second = service.run_job("tenant-a", "app-a", second.job_id)
    assert second.status == "completed"
    assert engine.calls == 0


def test_options_and_tenant_change_the_job_id(tmp_path):
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=2)
    settings, service, _ = make_service(tmp_path)

    automatic, _ = service.create_job(pdf, "tenant-a", "app-a")
    always, _ = service.create_job(
        pdf,
        "tenant-a",
        "app-a",
        options=JobOptions(ocr_mode="always"),
    )
    other_tenant, _ = service.create_job(pdf, "tenant-b", "app-a")

    assert automatic.job_id != always.job_id
    assert automatic.job_id != other_tenant.job_id
    assert service.get_job("tenant-b", "app-a", automatic.job_id) is None


def test_mixed_document_reports_text_and_ocr_pages(tmp_path):
    pdf = make_mixed_pdf(tmp_path / "mixed.pdf")
    settings, service, engine = make_service(tmp_path)

    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    job = service.run_job("tenant-a", "app-a", job.job_id)

    assert job.status == "completed"
    assert job.pages_text == 1
    assert job.pages_ocr == 2
    assert job.document_type == "mixed"
    assert engine.calls == 2


def test_encrypted_pdf_is_rejected(tmp_path):
    pdf = make_encrypted_pdf(tmp_path / "encrypted.pdf")
    settings, service, _ = make_service(tmp_path)

    with pytest.raises(PDFValidationError):
        service.create_job(pdf, "tenant-a", "app-a")


def test_missing_job_raises(tmp_path):
    settings, service, _ = make_service(tmp_path)
    with pytest.raises(JobNotFound):
        service.run_job(
            "tenant-a", "app-a", "44444444-4444-4444-4444-444444444444"
        )
