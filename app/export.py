"""Export a completed job to Markdown, JSONL, CSV and JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import JobRecord, PageRecord
from .store import FileJobStore

EXPORT_FILENAMES = (
    "document.md",
    "pages.jsonl",
    "pages.csv",
    "result.json",
)


def build_result(job: JobRecord, pages: list[PageRecord]) -> dict[str, Any]:
    return {
        "job": job.to_dict(),
        "pages": [page.to_dict() for page in pages],
    }


def render_markdown(job: JobRecord, pages: list[PageRecord]) -> str:
    lines: list[str] = [
        f"# {job.source_name}",
        "",
        f"- Job: `{job.job_id}`",
        f"- Tenant: `{job.tenant_id}`",
        f"- Application: `{job.application_id}`",
        f"- Status: `{job.status}`",
        f"- Document type: `{job.document_type}`",
        f"- Pages: {job.pages_total}",
        f"- Text-layer pages: {job.pages_text}",
        f"- OCR pages: {job.pages_ocr}",
        f"- Empty pages: {job.pages_empty}",
        f"- Failed pages: {job.pages_failed}",
    ]
    if job.mean_ocr_confidence is not None:
        lines.append(f"- Mean OCR confidence: {job.mean_ocr_confidence:.3f}")
    lines.extend(["", "---", ""])

    for page in pages:
        heading = f"## Page {page.page_number} · {page.method} · {page.quality}"
        lines.append(heading)
        lines.append("")
        if page.confidence is not None:
            lines.append(f"OCR confidence: {page.confidence:.3f}")
            lines.append("")
        if page.error:
            lines.append(f"> Extraction issue: {page.error}")
            lines.append("")
        lines.append(page.text if page.text else "_No text extracted._")
        lines.extend(["", "---", ""])

    return "\n".join(lines).rstrip() + "\n"


def export_job(
    store: FileJobStore,
    job: JobRecord,
    pages: list[PageRecord],
) -> Path:
    export_dir = store.export_dir(job.tenant_id, job.application_id, job.job_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    result = build_result(job, pages)
    (export_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (export_dir / "pages.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for page in pages:
            handle.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")

    with (export_dir / "pages.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "page_number",
            "status",
            "method",
            "quality",
            "char_count",
            "word_count",
            "confidence",
            "ocr_attempted",
            "furniture_removed",
            "duration_ms",
            "error",
            "text",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for page in pages:
            row = page.to_dict()
            writer.writerow({field: row.get(field) for field in fieldnames})

    (export_dir / "document.md").write_text(
        render_markdown(job, pages),
        encoding="utf-8",
    )
    return export_dir
