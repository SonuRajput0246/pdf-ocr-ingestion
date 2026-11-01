"""File-backed job store with atomic JSON writes and tenant-scoped paths."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .errors import InvalidIdentifier, JobNotFound
from .models import JobRecord, PageRecord

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_JOB_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def validate_identifier(value: str, name: str) -> str:
    """Validate a tenant or application identifier before using it in a path."""

    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise InvalidIdentifier(
            f"{name} must start with a letter or digit and contain only "
            "letters, digits, dot, underscore or hyphen (max 64 characters)"
        )
    return value


def validate_job_id(value: str) -> str:
    if not isinstance(value, str) or not _JOB_ID_RE.fullmatch(value):
        raise InvalidIdentifier("job_id must be a UUID string")
    return value


class FileJobStore:
    """Store jobs as JSON files under ``<root>/<tenant>/<application>/<job>``.

    The layout is intentionally inspectable during development. It is not a
    replacement for a transactional queue when multiple worker processes share
    the same directory.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    def tenant_root(self, tenant_id: str) -> Path:
        return self.root / validate_identifier(tenant_id, "tenant_id")

    def application_root(self, tenant_id: str, application_id: str) -> Path:
        return self.tenant_root(tenant_id) / validate_identifier(
            application_id, "application_id"
        )

    def job_dir(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.application_root(tenant_id, application_id) / validate_job_id(job_id)

    def source_path(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.job_dir(tenant_id, application_id, job_id) / "source.pdf"

    def job_json_path(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.job_dir(tenant_id, application_id, job_id) / "job.json"

    def layout_path(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.job_dir(tenant_id, application_id, job_id) / "layout.json"

    def pages_dir(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.job_dir(tenant_id, application_id, job_id) / "pages"

    def page_path(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        page_number: int,
    ) -> Path:
        return self.pages_dir(tenant_id, application_id, job_id) / (
            f"page-{page_number:04d}.json"
        )

    def export_dir(self, tenant_id: str, application_id: str, job_id: str) -> Path:
        return self.job_dir(tenant_id, application_id, job_id) / "exports"

    # ------------------------------------------------------------------
    # Atomic JSON helpers
    # ------------------------------------------------------------------
    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        with self._write_lock:
            try:
                temp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def create_job(self, job: JobRecord) -> JobRecord:
        path = self.job_json_path(job.tenant_id, job.application_id, job.job_id)
        if path.exists():
            existing = self.get_job(job.tenant_id, job.application_id, job.job_id)
            if existing is not None:
                return existing
        self._atomic_write_json(path, job.to_dict())
        return job

    def update_job(self, job: JobRecord) -> None:
        job.touch()
        self._atomic_write_json(
            self.job_json_path(job.tenant_id, job.application_id, job.job_id),
            job.to_dict(),
        )

    def get_job(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> JobRecord | None:
        path = self.job_json_path(tenant_id, application_id, job_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return JobRecord.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def require_job(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> JobRecord:
        job = self.get_job(tenant_id, application_id, job_id)
        if job is None:
            raise JobNotFound(
                f"Job {job_id} was not found for tenant {tenant_id} "
                f"and application {application_id}"
            )
        return job

    def list_jobs(
        self,
        tenant_id: str,
        application_id: str | None = None,
    ) -> list[JobRecord]:
        tenant_root = self.tenant_root(tenant_id)
        if not tenant_root.exists():
            return []

        if application_id is not None:
            application_dirs = [
                self.application_root(tenant_id, application_id)
            ]
        else:
            application_dirs = [
                path for path in tenant_root.iterdir() if path.is_dir()
            ]

        jobs: list[JobRecord] = []
        for application_dir in application_dirs:
            if not application_dir.exists():
                continue
            for job_dir in application_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                job_file = job_dir / "job.json"
                if not job_file.exists():
                    continue
                try:
                    data = json.loads(job_file.read_text(encoding="utf-8"))
                    jobs.append(JobRecord.from_dict(data))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue

        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs

    def delete_job(self, tenant_id: str, application_id: str, job_id: str) -> None:
        path = self.job_dir(tenant_id, application_id, job_id)
        if not path.exists():
            raise JobNotFound(f"Job {job_id} was not found")

        # On Windows, an open download response can briefly keep an export
        # file locked after the client has consumed it.  Retry a few times
        # instead of returning a 500 for a deletion that is otherwise valid.
        for attempt in range(10):
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))

    # ------------------------------------------------------------------
    # Layout and pages
    # ------------------------------------------------------------------
    def write_layout(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        layout: dict[str, Any],
    ) -> None:
        self._atomic_write_json(
            self.layout_path(tenant_id, application_id, job_id), layout
        )

    def read_layout(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> dict[str, Any] | None:
        path = self.layout_path(tenant_id, application_id, job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def write_page(
        self, tenant_id: str, application_id: str, job_id: str, page: PageRecord
    ) -> None:
        self._atomic_write_json(
            self.page_path(tenant_id, application_id, job_id, page.page_number),
            page.to_dict(),
        )

    def read_page(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        page_number: int,
    ) -> PageRecord | None:
        path = self.page_path(
            tenant_id, application_id, job_id, page_number
        )
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PageRecord.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def list_pages(
        self, tenant_id: str, application_id: str, job_id: str
    ) -> list[PageRecord]:
        pages_dir = self.pages_dir(tenant_id, application_id, job_id)
        if not pages_dir.exists():
            return []

        pages: list[PageRecord] = []
        for path in sorted(pages_dir.glob("page-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pages.append(PageRecord.from_dict(data))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        pages.sort(key=lambda item: item.page_number)
        return pages
