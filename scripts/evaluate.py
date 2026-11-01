"""Evaluate extraction against the synthetic gold text.

The text-layer sample does not need Tesseract. The scanned and mixed samples do.
Run this inside the Docker image (which installs Tesseract) for the full path.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from app.config import Settings
from app.metrics import character_error_rate, word_error_rate
from app.models import JobOptions
from app.ocr import TesseractOCREngine
from app.service import IngestionService
from app.store import FileJobStore

PAGE_MARKER_RE = re.compile(r"^--- page \d+ ---\s*$", re.MULTILINE)


def parse_gold(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    parts = PAGE_MARKER_RE.split(text)
    return [part.strip() for part in parts if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--ocr-mode", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--tenant", default="evaluation")
    parser.add_argument("--application", default="synthetic-samples")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.data_dir:
        settings = settings.with_overrides(data_dir=Path(args.data_dir))

    engine = TesseractOCREngine(settings.tesseract_cmd)
    if not engine.available():
        print(
            "Tesseract is not available. The text-layer sample can still be "
            "evaluated, but scanned pages will be empty. Use the Docker image "
            "for the full OCR path.",
            file=sys.stderr,
        )

    service = IngestionService(
        settings,
        FileJobStore(settings.data_dir),
        engine,
    )
    root = Path(__file__).resolve().parents[1]
    samples = [
        ("sample_text_layer.pdf", "sample_text_layer.txt"),
        ("sample_scanned.pdf", "sample_scanned.txt"),
        ("sample_mixed.pdf", "sample_mixed.txt"),
    ]

    exit_code = 0
    for pdf_name, gold_name in samples:
        pdf_path = root / "data" / pdf_name
        gold_path = root / "data" / "gold" / gold_name
        if not pdf_path.exists() or not gold_path.exists():
            print(f"Missing sample: {pdf_name}", file=sys.stderr)
            exit_code = 2
            continue

        options = JobOptions(ocr_mode=args.ocr_mode)
        job, _ = service.create_job(
            pdf_path,
            args.tenant,
            args.application,
            options=options,
            source_name=pdf_name,
        )
        job = service.run_job(
            args.tenant,
            args.application,
            job.job_id,
            retry_failed=True,
        )
        result = service.get_result(
            args.tenant,
            args.application,
            job.job_id,
            partial=True,
        )
        pages = result["pages"]
        gold_pages = parse_gold(gold_path)
        reference = "\n".join(gold_pages)
        hypothesis = "\n".join(page["text"] for page in pages)
        cer = character_error_rate(reference, hypothesis)
        wer = word_error_rate(reference, hypothesis)
        print(
            f"{pdf_name}: status={job.status} pages={job.pages_total} "
            f"ocr={job.pages_ocr} failed={job.pages_failed} "
            f"CER={cer:.4f} WER={wer:.4f}"
        )
        if job.status == "failed":
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
