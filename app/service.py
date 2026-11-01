"""Service layer: deterministic job creation, execution and retrieval."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from .config import Settings
from .errors import (
    IngestionError,
    JobAlreadyRunning,
    JobNotCompleted,
    PDFValidationError,
)
from .export import build_result, export_job
from .extractor import validate_pdf
from .models import TERMINAL_JOB_STATUSES, JobOptions, JobRecord, PageRecord, utc_now
from .ocr import OCREngine
from .pipeline import IngestionPipeline
from .store import FileJobStore, validate_identifier

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source_name(name: str) -> str:
    cleaned = secure_filename(name) or "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:200]


class IngestionService:
    """Create idempotent jobs and run them through the resumable pipeline."""

    def __init__(
        self,
        settings: Settings,
        store: FileJobStore,
        ocr_engine: OCREngine,
        pipeline: IngestionPipeline | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.ocr_engine = ocr_engine
        self.pipeline = pipeline or IngestionPipeline(
            store,
            ocr_engine,
            low_confidence_threshold=settings.low_confidence_threshold,
        )
        self._running: set[str] = set()
        self._running_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------
    def create_job(
        self,
        source_path: Path | str,
        tenant_id: str,
        application_id: str,
        options: JobOptions | None = None,
        source_name: str | None = None,
    ) -> tuple[JobRecord, bool]:
        source = Path(source_path)
        if not source.is_file():
            raise IngestionError("Source file was not found")

        tenant_id = validate_identifier(tenant_id, "tenant_id")
        application_id = validate_identifier(application_id, "application_id")

        if source.suffix.lower() != ".pdf":
            raise PDFValidationError("Only PDF files are supported")
        with source.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise PDFValidationError("File is not a valid PDF")

        page_count = validate_pdf(source)
        options = options or JobOptions(
            ocr_mode=self.settings.ocr_mode,
            language=self.settings.ocr_language,
            dpi=self.settings.ocr_dpi,
            min_text_chars=self.settings.min_text_chars,
            min_alnum_ratio=self.settings.min_alnum_ratio,
            preprocess_grayscale=self.settings.preprocess_grayscale,
            preprocess_autocontrast=self.settings.preprocess_autocontrast,
            preprocess_threshold=self.settings.preprocess_threshold,
            remove_furniture=self.settings.remove_furniture,
            furniture_margin=self.settings.furniture_margin,
            furniture_threshold=self.settings.furniture_threshold,
            expand_contractions=self.settings.expand_contractions,
            lowercase_text=self.settings.lowercase_text,
            psm=self.settings.ocr_psm,
        )

        source_sha256 = _sha256_file(source)
        job_id = self._job_id(tenant_id, application_id, source_sha256, options)
        existing = self.store.get_job(tenant_id, application_id, job_id)
        if existing is not None:
            destination = self.store.source_path(
                tenant_id, application_id, job_id
            )
            if not destination.exists():
                self._copy_source(source, destination)
            return existing, False

        source_name = _safe_source_name(source_name or source.name)
        now = utc_now()
        job = JobRecord(
            job_id=job_id,
            tenant_id=tenant_id,
            application_id=application_id,
            source_name=source_name,
            source_sha256=source_sha256,
            source_bytes=source.stat().st_size,
            options=options.to_dict(),
            status="queued",
            stage="queued",
            pages_total=page_count,
            created_at=now,
            updated_at=now,
        )
        self.store.create_job(job)
        self._copy_source(
            source,
            self.store.source_path(tenant_id, application_id, job_id),
        )
        logger.info(
            "created job=%s tenant=%s application=%s bytes=%s",
            job.job_id,
            tenant_id,
            application_id,
            job.source_bytes,
        )
        return job, True

    @staticmethod
    def _job_id(
        tenant_id: str,
        application_id: str,
        source_sha256: str,
        options: JobOptions,
    ) -> str:
        key = (
            f"pdf-ocr-ingestion:{tenant_id}:{application_id}:"
            f"{source_sha256}:{options.fingerprint}"
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

    @staticmethod
    def _copy_source(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == destination.resolve():
            return
        temp = destination.with_name(
            f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            shutil.copyfile(source, temp)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_job(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        *,
        retry_failed: bool = False,
    ) -> JobRecord:
        job = self.store.require_job(tenant_id, application_id, job_id)
        if job.status in TERMINAL_JOB_STATUSES and not retry_failed:
            return job

        with self._running_lock:
            if job.job_id in self._running:
                return job
            self._running.add(job.job_id)

        try:
            return self.pipeline.run(job, retry_failed=retry_failed)
        finally:
            with self._running_lock:
                self._running.discard(job.job_id)

    def run_job_async(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        *,
        retry_failed: bool = False,
    ) -> threading.Thread | None:
        job = self.store.require_job(tenant_id, application_id, job_id)
        if job.status in TERMINAL_JOB_STATUSES and not retry_failed:
            return None
        if self.is_running(job_id):
            return None

        thread = threading.Thread(
            target=self._run_async,
            args=(tenant_id, application_id, job_id, retry_failed),
            name=f"ingest-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return thread

    def _run_async(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        retry_failed: bool,
    ) -> None:
        try:
            self.run_job(
                tenant_id,
                application_id,
                job_id,
                retry_failed=retry_failed,
            )
        except Exception:  # pragma: no cover - logged for an async worker
            logger.exception("async job=%s failed unexpectedly", job_id)

    def is_running(self, job_id: str) -> bool:
        with self._running_lock:
            return job_id in self._running

    @property
    def running_count(self) -> int:
        with self._running_lock:
            return len(self._running)

    # ------------------------------------------------------------------
    # Reads and maintenance
    # ------------------------------------------------------------------
    def get_job(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> JobRecord | None:
        return self.store.get_job(tenant_id, application_id, job_id)

    def require_job(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> JobRecord:
        return self.store.require_job(tenant_id, application_id, job_id)

    def list_jobs(
        self, tenant_id: str, application_id: str | None = None
    ) -> list[JobRecord]:
        return self.store.list_jobs(tenant_id, application_id)

    def list_pages(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> list[PageRecord]:
        self.store.require_job(tenant_id, application_id, job_id)
        return self.store.list_pages(tenant_id, application_id, job_id)

    def get_page(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        page_number: int,
    ) -> PageRecord | None:
        self.store.require_job(tenant_id, application_id, job_id)
        return self.store.read_page(
            tenant_id, application_id, job_id, page_number
        )

    def get_result(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        *,
        partial: bool = False,
    ) -> dict[str, object]:
        job = self.store.require_job(tenant_id, application_id, job_id)
        if not partial and job.status not in TERMINAL_JOB_STATUSES:
            raise JobNotCompleted(
                f"Job {job_id} is still {job.status}; use partial=true for a snapshot"
            )
        pages = self.store.list_pages(tenant_id, application_id, job_id)
        return build_result(job, pages)

    def export(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> Path:
        job = self.store.require_job(tenant_id, application_id, job_id)
        pages = self.store.list_pages(tenant_id, application_id, job_id)
        return export_job(self.store, job, pages)

    def delete_job(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> None:
        if self.is_running(job_id):
            raise JobAlreadyRunning(f"Job {job_id} is still running")
        self.store.delete_job(tenant_id, application_id, job_id)
