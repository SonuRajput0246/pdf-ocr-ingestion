"""Flask ingress for creating and inspecting ingestion jobs."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from . import __version__
from .config import Settings
from .errors import (
    IngestionError,
    JobAlreadyRunning,
    JobNotCompleted,
    JobNotFound,
    OCREngineUnavailable,
)
from .models import JobOptions, JobRecord, TERMINAL_JOB_STATUSES
from .ocr import TesseractOCREngine
from .service import IngestionService
from .store import FileJobStore, validate_identifier

logger = logging.getLogger(__name__)

EXPORT_MIME_TYPES = {
    "document.md": "text/markdown; charset=utf-8",
    "pages.jsonl": "application/x-ndjson; charset=utf-8",
    "pages.csv": "text/csv; charset=utf-8",
    "result.json": "application/json; charset=utf-8",
}


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: object, name: str, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value))
    except ValueError as exc:
        abort(400, description=f"{name} must be an integer")
        raise exc  # pragma: no cover - abort raises


def _as_float(value: object, name: str, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value))
    except ValueError as exc:
        abort(400, description=f"{name} must be a number")
        raise exc  # pragma: no cover - abort raises


def _request_value(name: str) -> object | None:
    if name in request.form:
        return request.form.get(name)
    if name in request.args:
        return request.args.get(name)
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload.get(name)
    return None


def _validated_tenant_pair(*, require_application: bool = True) -> tuple[str, str | None]:
    tenant = _request_value("tenant_id")
    application = _request_value("application_id")

    if not tenant:
        abort(400, description="tenant_id is required")
    try:
        tenant_id = validate_identifier(str(tenant), "tenant_id")
    except IngestionError as exc:
        abort(400, description=str(exc))
        raise exc  # pragma: no cover

    if application is None or str(application).strip() == "":
        if require_application:
            abort(400, description="application_id is required")
        return tenant_id, None

    try:
        application_id = validate_identifier(str(application), "application_id")
    except IngestionError as exc:
        abort(400, description=str(exc))
        raise exc  # pragma: no cover
    return tenant_id, application_id


def _job_payload(job: JobRecord) -> dict[str, object]:
    payload = job.to_dict()
    payload["progress"] = job.progress
    query = urlencode(
        {"tenant_id": job.tenant_id, "application_id": job.application_id}
    )
    payload["links"] = {
        "self": f"/jobs/{job.job_id}?{query}",
        "result": f"/jobs/{job.job_id}/result?{query}",
        "pages": f"/jobs/{job.job_id}/pages?{query}",
        "markdown": f"/jobs/{job.job_id}/markdown?{query}",
    }
    return payload


def _options_from_request(settings: Settings) -> JobOptions:
    threshold_raw = _request_value("preprocess_threshold")
    threshold = (
        None
        if threshold_raw is None or str(threshold_raw).strip() == ""
        else _as_int(threshold_raw, "preprocess_threshold", 0)
    )
    try:
        return JobOptions(
            ocr_mode=str(_request_value("ocr_mode") or settings.ocr_mode),
            language=str(
                _request_value("language")
                or _request_value("ocr_language")
                or settings.ocr_language
            ),
            dpi=_as_int(_request_value("dpi"), "dpi", settings.ocr_dpi),
            min_text_chars=_as_int(
                _request_value("min_text_chars"),
                "min_text_chars",
                settings.min_text_chars,
            ),
            min_alnum_ratio=_as_float(
                _request_value("min_alnum_ratio"),
                "min_alnum_ratio",
                settings.min_alnum_ratio,
            ),
            preprocess_grayscale=_as_bool(
                _request_value("preprocess_grayscale"),
                settings.preprocess_grayscale,
            ),
            preprocess_autocontrast=_as_bool(
                _request_value("preprocess_autocontrast"),
                settings.preprocess_autocontrast,
            ),
            preprocess_threshold=threshold,
            remove_furniture=_as_bool(
                _request_value("remove_furniture"),
                settings.remove_furniture,
            ),
            furniture_margin=_as_float(
                _request_value("furniture_margin"),
                "furniture_margin",
                settings.furniture_margin,
            ),
            furniture_threshold=_as_float(
                _request_value("furniture_threshold"),
                "furniture_threshold",
                settings.furniture_threshold,
            ),
            expand_contractions=_as_bool(
                _request_value("expand_contractions"),
                settings.expand_contractions,
            ),
            lowercase_text=_as_bool(
                _request_value("lowercase_text"),
                settings.lowercase_text,
            ),
            psm=_as_int(_request_value("psm"), "psm", settings.ocr_psm),
        )
    except ValueError as exc:
        abort(400, description=str(exc))
        raise exc  # pragma: no cover


def create_app(
    settings: Settings | None = None,
    service: IngestionService | None = None,
) -> Flask:
    if settings is None and service is not None:
        settings = service.settings
    settings = settings or Settings.from_env()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - Flask < 2.3 compatibility
        pass

    if service is None:
        service = IngestionService(
            settings,
            FileJobStore(settings.data_dir),
            TesseractOCREngine(settings.tesseract_cmd),
        )

    app.extensions["ingestion_service"] = service
    app.extensions["settings"] = settings

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(exc: RequestEntityTooLarge):
        return (
            jsonify(
                {
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Upload exceeds {settings.max_upload_mb} MB",
                    }
                }
            ),
            413,
        )

    @app.errorhandler(IngestionError)
    def handle_ingestion_error(exc: IngestionError):
        if isinstance(exc, JobNotFound):
            status = 404
            code = "job_not_found"
        elif isinstance(exc, JobNotCompleted):
            status = 409
            code = "job_not_completed"
        elif isinstance(exc, JobAlreadyRunning):
            status = 409
            code = "job_already_running"
        elif isinstance(exc, OCREngineUnavailable):
            status = 503
            code = "ocr_unavailable"
        else:
            status = 400
            code = "invalid_request"
        return jsonify({"error": {"code": code, "message": str(exc)}}), status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        code = (exc.name or "http_error").lower().replace(" ", "_")
        return (
            jsonify({"error": {"code": code, "message": exc.description}}),
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        logger.exception("unhandled API error")
        return (
            jsonify(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Unexpected server error",
                    }
                }
            ),
            500,
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @app.get("/health")
    def health():
        try:
            tesseract_available = bool(service.ocr_engine.available())
        except Exception:
            tesseract_available = False
        return jsonify(
            {
                "status": "ok",
                "version": __version__,
                "ocr_engine": getattr(service.ocr_engine, "name", "unknown"),
                "tesseract_available": tesseract_available,
                "storage": "file",
                "running_jobs": service.running_count,
            }
        )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    @app.post("/jobs")
    def create_job():
        tenant_id, application_id = _validated_tenant_pair()
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            abort(400, description="file is required")

        options = _options_from_request(settings)
        wait = _as_bool(_request_value("wait"), default=True)

        descriptor, temporary_name = tempfile.mkstemp(suffix=".pdf")
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            upload.save(temporary_path)
            job, created = service.create_job(
                temporary_path,
                tenant_id,
                application_id,
                options=options,
                source_name=upload.filename,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

        if wait:
            job = service.run_job(tenant_id, application_id, job.job_id)
            status = 201 if created else 200
        else:
            if job.status not in TERMINAL_JOB_STATUSES or _as_bool(
                _request_value("retry_failed"), default=False
            ):
                service.run_job_async(
                    tenant_id,
                    application_id,
                    job.job_id,
                    retry_failed=_as_bool(
                        _request_value("retry_failed"), default=False
                    ),
                )
            status = 202 if created or job.status not in TERMINAL_JOB_STATUSES else 200

        response = jsonify(_job_payload(job))
        response.status_code = status
        query = urlencode(
            {"tenant_id": tenant_id, "application_id": application_id}
        )
        response.headers["Location"] = f"/jobs/{job.job_id}?{query}"
        return response

    @app.get("/jobs")
    def list_jobs():
        tenant_id, application_id = _validated_tenant_pair(
            require_application=False
        )
        limit = max(1, min(_as_int(_request_value("limit"), "limit", 50), 200))
        offset = max(0, _as_int(_request_value("offset"), "offset", 0))
        jobs = service.list_jobs(tenant_id, application_id)
        total = len(jobs)
        selected = jobs[offset : offset + limit]
        return jsonify(
            {
                "jobs": [_job_payload(job) for job in selected],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @app.get("/jobs/<job_id>")
    def get_job(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        job = service.require_job(tenant_id, application_id, job_id)
        return jsonify(_job_payload(job))

    @app.get("/jobs/<job_id>/pages")
    def list_pages(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        include_text = _as_bool(_request_value("include_text"), default=False)
        pages = service.list_pages(tenant_id, application_id, job_id)
        return jsonify(
            {
                "job_id": job_id,
                "total": len(pages),
                "pages": [
                    page.to_dict() if include_text else page.summary()
                    for page in pages
                ],
            }
        )

    @app.get("/jobs/<job_id>/pages/<int:page_number>")
    def get_page(job_id: str, page_number: int):
        tenant_id, application_id = _validated_tenant_pair()
        page = service.get_page(
            tenant_id, application_id, job_id, page_number
        )
        if page is None:
            abort(404, description=f"Page {page_number} has not been extracted")
        return jsonify(page.to_dict())

    @app.get("/jobs/<job_id>/result")
    def get_result(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        partial = _as_bool(_request_value("partial"), default=False)
        return jsonify(
            service.get_result(
                tenant_id,
                application_id,
                job_id,
                partial=partial,
            )
        )

    @app.get("/jobs/<job_id>/markdown")
    def get_markdown(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        job = service.require_job(tenant_id, application_id, job_id)
        if job.status not in TERMINAL_JOB_STATUSES:
            abort(409, description="Job has not completed yet")
        path = (
            service.store.export_dir(tenant_id, application_id, job_id)
            / "document.md"
        )
        if not path.exists():
            abort(404, description="Markdown export is not available")
        return send_file(
            path,
            mimetype="text/markdown; charset=utf-8",
            as_attachment=False,
            download_name="document.md",
        )

    @app.get("/jobs/<job_id>/exports/<filename>")
    def download_export(job_id: str, filename: str):
        tenant_id, application_id = _validated_tenant_pair()
        if filename not in EXPORT_MIME_TYPES:
            abort(404, description="Unknown export")
        job = service.require_job(tenant_id, application_id, job_id)
        if job.status not in TERMINAL_JOB_STATUSES:
            abort(409, description="Job has not completed yet")
        path = (
            service.store.export_dir(tenant_id, application_id, job_id)
            / filename
        )
        if not path.exists():
            abort(404, description="Export is not available")
        return send_file(
            path,
            mimetype=EXPORT_MIME_TYPES[filename],
            as_attachment=True,
            download_name=filename,
        )

    @app.post("/jobs/<job_id>/resume")
    def resume_job(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        if service.is_running(job_id):
            raise JobAlreadyRunning(f"Job {job_id} is already running")
        retry_failed = _as_bool(
            _request_value("retry_failed"), default=False
        )
        wait = _as_bool(_request_value("wait"), default=True)
        if wait:
            job = service.run_job(
                tenant_id,
                application_id,
                job_id,
                retry_failed=retry_failed,
            )
            return jsonify(_job_payload(job))

        service.run_job_async(
            tenant_id,
            application_id,
            job_id,
            retry_failed=retry_failed,
        )
        job = service.require_job(tenant_id, application_id, job_id)
        response = jsonify(_job_payload(job))
        response.status_code = 202
        return response

    @app.delete("/jobs/<job_id>")
    def delete_job(job_id: str):
        tenant_id, application_id = _validated_tenant_pair()
        service.delete_job(tenant_id, application_id, job_id)
        return "", 204

    return app
