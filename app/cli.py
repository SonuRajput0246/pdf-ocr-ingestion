"""Command-line interface for the PDF/OCR ingestion demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .api import create_app
from .config import Settings
from .models import JobOptions, JobRecord
from .ocr import TesseractOCREngine
from .service import IngestionService
from .store import FileJobStore


def _build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    overrides: dict[str, object] = {}
    if getattr(args, "data_dir", None):
        overrides["data_dir"] = Path(args.data_dir)
    if getattr(args, "log_level", None):
        overrides["log_level"] = args.log_level
    return settings.with_overrides(**overrides) if overrides else settings


def _build_service(args: argparse.Namespace) -> tuple[Settings, IngestionService]:
    settings = _build_settings(args)
    service = IngestionService(
        settings,
        FileJobStore(settings.data_dir),
        TesseractOCREngine(settings.tesseract_cmd),
    )
    return settings, service


def _build_options(args: argparse.Namespace, settings: Settings) -> JobOptions:
    return JobOptions(
        ocr_mode=args.ocr_mode,
        language=args.language,
        dpi=args.dpi,
        min_text_chars=args.min_text_chars,
        min_alnum_ratio=args.min_alnum_ratio,
        preprocess_grayscale=not args.no_grayscale,
        preprocess_autocontrast=not args.no_autocontrast,
        preprocess_threshold=args.preprocess_threshold,
        remove_furniture=not args.no_furniture,
        furniture_margin=args.furniture_margin,
        furniture_threshold=args.furniture_threshold,
        expand_contractions=not args.no_contractions,
        lowercase_text=args.lowercase,
        psm=args.psm,
    )


def _print_job_summary(job: JobRecord) -> None:
    print(
        "\t".join(
            [
                job.job_id,
                job.status,
                f"{job.pages_done}/{job.pages_total}",
                f"text={job.pages_text}",
                f"ocr={job.pages_ocr}",
                f"empty={job.pages_empty}",
                f"failed={job.pages_failed}",
                job.source_name,
            ]
        )
    )


def _iter_pdfs(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(path.rglob("*.pdf")))
        elif path.is_file():
            found.append(path)
    return found


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        help="Job storage directory (default: DATA_DIR or .data)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Logging level (default: LOG_LEVEL or INFO)",
    )


def _add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant", required=True, help="Tenant identifier")
    parser.add_argument(
        "--application", required=True, help="Application identifier"
    )


def _add_extraction_options(
    parser: argparse.ArgumentParser, settings: Settings
) -> None:
    parser.add_argument(
        "--ocr-mode",
        choices=("auto", "always", "never"),
        default=settings.ocr_mode,
    )
    parser.add_argument("--language", default=settings.ocr_language)
    parser.add_argument("--dpi", type=int, default=settings.ocr_dpi)
    parser.add_argument("--psm", type=int, default=settings.ocr_psm)
    parser.add_argument(
        "--min-text-chars", type=int, default=settings.min_text_chars
    )
    parser.add_argument(
        "--min-alnum-ratio", type=float, default=settings.min_alnum_ratio
    )
    parser.add_argument(
        "--preprocess-threshold",
        type=int,
        default=settings.preprocess_threshold,
    )
    parser.add_argument("--no-grayscale", action="store_true")
    parser.add_argument("--no-autocontrast", action="store_true")
    parser.add_argument("--no-furniture", action="store_true")
    parser.add_argument(
        "--furniture-margin", type=float, default=settings.furniture_margin
    )
    parser.add_argument(
        "--furniture-threshold",
        type=float,
        default=settings.furniture_threshold,
    )
    parser.add_argument("--no-contractions", action="store_true")
    parser.add_argument("--lowercase", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Resumable PDF text extraction and OCR ingestion demo.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Create and run jobs for PDFs")
    ingest.add_argument("paths", nargs="+", help="PDF files or directories")
    _add_scope(ingest)
    _add_common(ingest)
    _add_extraction_options(ingest, settings)
    ingest.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry failed page checkpoints when resuming an existing job",
    )
    ingest.add_argument("--json", action="store_true", help="Print full job JSON")

    list_parser = subparsers.add_parser("list", help="List jobs")
    _add_common(list_parser)
    list_parser.add_argument("--tenant", required=True)
    list_parser.add_argument("--application", default=None)
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status", help="Show one job")
    status.add_argument("job_id")
    _add_scope(status)
    _add_common(status)

    result = subparsers.add_parser("result", help="Print a job result")
    result.add_argument("job_id")
    _add_scope(result)
    _add_common(result)
    result.add_argument(
        "--format",
        choices=("json", "markdown", "jsonl", "csv"),
        default="json",
    )
    result.add_argument("--output", help="Write to a file instead of stdout")

    export = subparsers.add_parser("export", help="Regenerate export files")
    export.add_argument("job_id")
    _add_scope(export)
    _add_common(export)

    resume = subparsers.add_parser("resume", help="Resume an interrupted job")
    resume.add_argument("job_id")
    _add_scope(resume)
    _add_common(resume)
    resume.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--json", action="store_true")

    delete = subparsers.add_parser("delete", help="Delete a job and its files")
    delete.add_argument("job_id")
    _add_scope(delete)
    _add_common(delete)
    delete.add_argument("--yes", action="store_true")

    health = subparsers.add_parser("health", help="Show OCR/runtime health")
    _add_common(health)

    serve = subparsers.add_parser("serve", help="Start the Flask API")
    _add_common(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--debug", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        settings = _build_settings(args)
        app = create_app(settings=settings)
        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0

    if args.command == "health":
        settings, service = _build_service(args)
        try:
            available = service.ocr_engine.available()
        except Exception:
            available = False
        print(
            json.dumps(
                {
                    "version": __version__,
                    "data_dir": str(settings.data_dir),
                    "ocr_engine": service.ocr_engine.name,
                    "tesseract_available": available,
                    "running_jobs": service.running_count,
                },
                indent=2,
            )
        )
        return 0 if available else 1

    _, service = _build_service(args)

    if args.command == "ingest":
        settings = _build_settings(args)
        options = _build_options(args, settings)
        pdfs = _iter_pdfs(args.paths)
        if not pdfs:
            print("No PDF files found.", file=sys.stderr)
            return 2
        exit_code = 0
        for pdf in pdfs:
            job, _ = service.create_job(
                pdf,
                args.tenant,
                args.application,
                options=options,
                source_name=pdf.name,
            )
            job = service.run_job(
                args.tenant,
                args.application,
                job.job_id,
                retry_failed=args.retry_failed,
            )
            if args.json:
                print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
            else:
                _print_job_summary(job)
            if job.status == "failed":
                exit_code = 1
        return exit_code

    if args.command == "list":
        jobs = service.list_jobs(args.tenant, args.application)
        selected = jobs[args.offset : args.offset + max(args.limit, 0)]
        if args.json:
            print(
                json.dumps(
                    [job.to_dict() for job in selected],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("JOB ID\tSTATUS\tPAGES\tTEXT\tOCR\tFAILED\tSOURCE")
            for job in selected:
                print(
                    "\t".join(
                        [
                            job.job_id,
                            job.status,
                            f"{job.pages_done}/{job.pages_total}",
                            str(job.pages_text),
                            str(job.pages_ocr),
                            str(job.pages_failed),
                            job.source_name,
                        ]
                    )
                )
        return 0

    if args.command == "status":
        job = service.require_job(args.tenant, args.application, args.job_id)
        print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "result":
        job = service.require_job(args.tenant, args.application, args.job_id)
        export_dir = service.store.export_dir(
            args.tenant, args.application, args.job_id
        )
        if args.format == "json":
            content = json.dumps(
                service.get_result(
                    args.tenant,
                    args.application,
                    args.job_id,
                    partial=job.status not in {"completed", "completed_with_errors"},
                ),
                ensure_ascii=False,
                indent=2,
            )
        else:
            filename = {
                "markdown": "document.md",
                "jsonl": "pages.jsonl",
                "csv": "pages.csv",
            }[args.format]
            path = export_dir / filename
            if not path.exists():
                service.export(args.tenant, args.application, args.job_id)
            content = path.read_text(encoding="utf-8")
        if args.output:
            Path(args.output).write_text(content, encoding="utf-8")
            print(args.output)
        else:
            print(content)
        return 0

    if args.command == "export":
        export_dir = service.export(
            args.tenant, args.application, args.job_id
        )
        for filename in sorted(path.name for path in export_dir.iterdir()):
            print(export_dir / filename)
        return 0

    if args.command == "resume":
        job = service.run_job(
            args.tenant,
            args.application,
            args.job_id,
            retry_failed=args.retry_failed,
        )
        if args.json:
            print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_job_summary(job)
        return 0 if job.status != "failed" else 1

    if args.command == "delete":
        if not args.yes:
            answer = input(f"Delete job {args.job_id}? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Aborted.")
                return 1
        service.delete_job(args.tenant, args.application, args.job_id)
        print(f"Deleted {args.job_id}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
