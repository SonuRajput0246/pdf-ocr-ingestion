"""Resumable page-by-page PDF extraction pipeline."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import fitz

from .clean import clean_text
from .export import export_job
from .extractor import PageLine, extract_page_lines, join_lines, open_pdf, render_page
from .layout import FurnitureProfile, detect_furniture
from .models import JobOptions, JobRecord, PageRecord, utc_now
from .ocr import OCREngine
from .preprocess import preprocess_image
from .quality import assess_text
from .store import FileJobStore

logger = logging.getLogger(__name__)


def _duration_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(int((end - start).total_seconds() * 1000), 0)


class IngestionPipeline:
    """Extract text from one PDF, checkpointing after every page.

    A checkpoint is written for both successful and failed pages. A later resume
    skips successful pages and, when ``retry_failed=True``, re-runs only the
    pages that previously failed.
    """

    def __init__(
        self,
        store: FileJobStore,
        ocr_engine: OCREngine,
        *,
        low_confidence_threshold: float = 0.60,
    ) -> None:
        self.store = store
        self.ocr_engine = ocr_engine
        self.low_confidence_threshold = low_confidence_threshold

    def run(self, job: JobRecord, *, retry_failed: bool = False) -> JobRecord:
        if job.is_terminal and not retry_failed:
            return job

        doc: fitz.Document | None = None
        try:
            source = self.store.source_path(
                job.tenant_id, job.application_id, job.job_id
            )
            doc = open_pdf(source)
            job.pages_total = doc.page_count
            job.status = "running"
            job.stage = "layout"
            job.error = None
            job.finished_at = None
            job.duration_ms = None
            if not job.started_at:
                job.started_at = utc_now()
            self._recompute_counts(job)
            self.store.update_job(job)

            options = JobOptions.from_dict(job.options)
            profile = self._load_or_detect_layout(job, doc, options)
            logger.info(
                "job=%s pages=%s ocr_mode=%s furniture_keys=%s",
                job.job_id,
                job.pages_total,
                options.ocr_mode,
                len(profile.keys),
            )

            for page_index in range(doc.page_count):
                page_number = page_index + 1
                existing = self.store.read_page(
                    job.tenant_id, job.application_id, job.job_id, page_number
                )
                if existing is not None and (
                    existing.status == "ok" or not retry_failed
                ):
                    continue

                if existing is not None:
                    logger.info(
                        "job=%s retrying page=%s previous_error=%s",
                        job.job_id,
                        page_number,
                        existing.error,
                    )

                job.stage = "extracting"
                self.store.update_job(job)
                page_record = self._process_page(
                    doc[page_index],
                    page_number=page_number,
                    options=options,
                    profile=profile,
                )
                self.store.write_page(
                    job.tenant_id,
                    job.application_id,
                    job.job_id,
                    page_record,
                )
                self._recompute_counts(job)
                self.store.update_job(job)
                logger.info(
                    "job=%s page=%s/%s method=%s quality=%s chars=%s",
                    job.job_id,
                    page_number,
                    job.pages_total,
                    page_record.method,
                    page_record.quality,
                    page_record.char_count,
                )

            job.stage = "exporting"
            self.store.update_job(job)
            pages = self.store.list_pages(
                job.tenant_id, job.application_id, job.job_id
            )
            self._finalize(job, pages)
            export_job(self.store, job, pages)
            self.store.update_job(job)
            logger.info(
                "job=%s status=%s pages=%s ocr=%s failed=%s",
                job.job_id,
                job.status,
                job.pages_done,
                job.pages_ocr,
                job.pages_failed,
            )
            return job
        except Exception as exc:  # Keep a resumable record of unexpected failures.
            job.status = "failed"
            job.stage = "failed"
            job.error = str(exc)
            job.finished_at = utc_now()
            job.updated_at = job.finished_at
            job.duration_ms = _duration_ms(job.started_at, job.finished_at)
            self.store.update_job(job)
            logger.exception("job=%s failed", job.job_id)
            return job
        finally:
            if doc is not None:
                doc.close()

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def _load_or_detect_layout(
        self,
        job: JobRecord,
        doc: fitz.Document,
        options: JobOptions,
    ) -> FurnitureProfile:
        if not options.remove_furniture:
            return FurnitureProfile()

        cached = self.store.read_layout(
            job.tenant_id, job.application_id, job.job_id
        )
        if cached is not None:
            return FurnitureProfile.from_dict(cached)

        profile = detect_furniture(
            doc,
            margin=options.furniture_margin,
            threshold=options.furniture_threshold,
        )
        self.store.write_layout(
            job.tenant_id,
            job.application_id,
            job.job_id,
            profile.to_dict(),
        )
        return profile

    def _process_page(
        self,
        page: fitz.Page,
        *,
        page_number: int,
        options: JobOptions,
        profile: FurnitureProfile,
    ) -> PageRecord:
        started = time.perf_counter()
        try:
            text_lines = extract_page_lines(page)
            text_lines, text_furniture_removed = profile.remove(text_lines)
            text_layer = join_lines(text_lines)
            text_quality = assess_text(
                text_layer,
                min_chars=options.min_text_chars,
                min_alnum_ratio=options.min_alnum_ratio,
            )

            text = text_layer
            method = "text" if text_layer.strip() else "empty"
            confidence: float | None = None
            furniture_removed = text_furniture_removed
            ocr_attempted = False
            ocr_error: str | None = None
            status = "ok"

            should_ocr = options.ocr_mode == "always" or (
                options.ocr_mode == "auto" and not text_quality.usable
            )
            if should_ocr:
                ocr_attempted = True
                try:
                    image = render_page(page, options.dpi)
                    image = preprocess_image(
                        image,
                        grayscale=options.preprocess_grayscale,
                        autocontrast=options.preprocess_autocontrast,
                        threshold=options.preprocess_threshold,
                    )
                    result = self.ocr_engine.image_to_text(
                        image,
                        language=options.language,
                        psm=options.psm,
                    )
                    if result.text.strip():
                        ocr_lines = [
                            PageLine(text=line.strip(), bbox=(0.0, 0.0, 0.0, 0.0))
                            for line in result.text.splitlines()
                            if line.strip()
                        ]
                        ocr_lines, ocr_furniture_removed = profile.remove(ocr_lines)
                        text = join_lines(ocr_lines)
                        method = "ocr"
                        confidence = result.confidence
                        furniture_removed = ocr_furniture_removed
                    else:
                        ocr_error = "OCR returned no text"
                        status = "error"
                except Exception as exc:
                    ocr_error = str(exc)
                    status = "error"
                    logger.warning(
                        "job page=%s OCR failed: %s", page_number, exc
                    )

            cleaned = clean_text(
                text,
                lowercase=options.lowercase_text,
                expand_contractions_enabled=options.expand_contractions,
            )

            if status == "error":
                quality = "error" if not cleaned else "low"
            elif not cleaned:
                quality = "empty"
            elif (
                method == "ocr"
                and confidence is not None
                and confidence < self.low_confidence_threshold
            ):
                quality = "low"
            elif not assess_text(
                cleaned,
                min_chars=options.min_text_chars,
                min_alnum_ratio=options.min_alnum_ratio,
            ).usable:
                quality = "low"
            else:
                quality = "good"

            return PageRecord(
                page_number=page_number,
                status=status,
                method=method,
                text=cleaned,
                confidence=confidence,
                quality=quality,
                ocr_attempted=ocr_attempted,
                ocr_error=ocr_error,
                furniture_removed=furniture_removed,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=ocr_error if status == "error" else None,
            )
        except Exception as exc:
            logger.exception("page=%s extraction failed", page_number)
            return PageRecord(
                page_number=page_number,
                status="error",
                method="error",
                text="",
                quality="error",
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------
    def _recompute_counts(self, job: JobRecord) -> None:
        pages = self.store.list_pages(
            job.tenant_id, job.application_id, job.job_id
        )
        job.pages_done = len(pages)
        job.pages_text = sum(page.method == "text" for page in pages)
        job.pages_ocr = sum(page.method == "ocr" for page in pages)
        job.pages_empty = sum(page.method == "empty" for page in pages)
        job.pages_failed = sum(page.status == "error" for page in pages)
        job.pages_low_confidence = sum(page.quality == "low" for page in pages)

        confidences = [
            page.confidence
            for page in pages
            if page.method == "ocr" and page.confidence is not None
        ]
        job.mean_ocr_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )
        job.errors = [
            f"page {page.page_number}: {page.error}"
            for page in pages
            if page.status == "error" and page.error
        ][:50]

    def _finalize(self, job: JobRecord, pages: list[PageRecord]) -> None:
        self._recompute_counts(job)
        job.status = "completed_with_errors" if job.pages_failed else "completed"
        job.stage = "done"
        job.finished_at = utc_now()
        job.updated_at = job.finished_at
        job.duration_ms = _duration_ms(job.started_at, job.finished_at)
        job.error = None
        job.document_type = self._document_type(job)

    @staticmethod
    def _document_type(job: JobRecord) -> str:
        if job.pages_total <= 0:
            return "unknown"
        if job.pages_failed == job.pages_total:
            return "failed"
        if job.pages_ocr == job.pages_total:
            return "scanned"
        if job.pages_ocr > 0:
            return "mixed"
        if job.pages_text > 0:
            return "text"
        if job.pages_empty == job.pages_total:
            return "empty"
        return "unknown"
