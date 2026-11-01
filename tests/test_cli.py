from __future__ import annotations

import json

from app.cli import main
from tests.helpers import make_text_pdf


def _run_ingest(monkeypatch, tmp_path, pdf):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "cli-data"))
    monkeypatch.setenv("OCR_MODE", "auto")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return main(
        [
            "ingest",
            str(pdf),
            "--tenant",
            "tenant-a",
            "--application",
            "app-a",
            "--json",
        ]
    )


def test_cli_ingest_list_status_result_resume_and_delete(
    monkeypatch, tmp_path, capsys
):
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=2)
    assert _run_ingest(monkeypatch, tmp_path, pdf) == 0
    output = capsys.readouterr().out
    job = json.loads(output)
    job_id = job["job_id"]
    assert job["status"] == "completed"
    assert job["pages_total"] == 2

    assert (
        main(
            [
                "list",
                "--tenant",
                "tenant-a",
                "--application",
                "app-a",
                "--json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["job_id"] == job_id

    assert (
        main(
            [
                "status",
                job_id,
                "--tenant",
                "tenant-a",
                "--application",
                "app-a",
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["job_id"] == job_id

    assert (
        main(
            [
                "result",
                job_id,
                "--tenant",
                "tenant-a",
                "--application",
                "app-a",
                "--format",
                "markdown",
            ]
        )
        == 0
    )
    assert "Page 1" in capsys.readouterr().out

    assert (
        main(
            [
                "resume",
                job_id,
                "--tenant",
                "tenant-a",
                "--application",
                "app-a",
                "--json",
            ]
        )
        == 0
    )
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "completed"

    assert (
        main(
            [
                "delete",
                job_id,
                "--tenant",
                "tenant-a",
                "--application",
                "app-a",
                "--yes",
            ]
        )
        == 0
    )
    capsys.readouterr()
