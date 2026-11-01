from __future__ import annotations

import io
import time

from tests.helpers import make_text_pdf


def _upload(client, pdf, **fields):
    data = {
        "tenant_id": "tenant-a",
        "application_id": "app-a",
        "wait": "true",
    }
    data.update(fields)
    data["file"] = (io.BytesIO(pdf.read_bytes()), pdf.name)
    return client.post("/jobs", data=data, content_type="multipart/form-data")


def _query():
    return "?tenant_id=tenant-a&application_id=app-a"


def test_health(api):
    client, service, engine = api
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["ocr_engine"] == "stub"
    assert payload["storage"] == "file"


def test_ingest_and_read_endpoints(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=3)

    response = _upload(client, pdf)
    assert response.status_code == 201
    job = response.get_json()
    job_id = job["job_id"]
    assert job["status"] == "completed"
    assert job["pages_total"] == 3
    assert job["progress"] == 1.0

    response = client.get(f"/jobs/{job_id}{_query()}")
    assert response.status_code == 200
    assert response.get_json()["job_id"] == job_id

    response = client.get(f"/jobs/{job_id}/pages{_query()}")
    assert response.status_code == 200
    pages = response.get_json()["pages"]
    assert len(pages) == 3
    assert "text" not in pages[0]
    assert "preview" in pages[0]

    response = client.get(f"/jobs/{job_id}/pages/1{_query()}")
    assert response.status_code == 200
    assert "Page 1 body text." in response.get_json()["text"]

    response = client.get(f"/jobs/{job_id}/result{_query()}")
    assert response.status_code == 200
    result = response.get_json()
    assert result["job"]["job_id"] == job_id
    assert len(result["pages"]) == 3

    response = client.get(f"/jobs/{job_id}/markdown{_query()}")
    assert response.status_code == 200
    assert "Page 1" in response.get_data(as_text=True)

    response = client.get("/jobs?tenant_id=tenant-a&application_id=app-a")
    assert response.status_code == 200
    assert response.get_json()["total"] == 1

    response = client.get(f"/jobs/{job_id}/exports/result.json{_query()}")
    assert response.status_code == 200
    assert response.get_json()["job"]["job_id"] == job_id

    response = client.delete(f"/jobs/{job_id}{_query()}")
    assert response.status_code == 204
    assert client.get(f"/jobs/{job_id}{_query()}").status_code == 404


def test_tenant_isolation(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=1)
    job = _upload(client, pdf).get_json()
    response = client.get(
        f"/jobs/{job['job_id']}?tenant_id=tenant-b&application_id=app-a"
    )
    assert response.status_code == 404


def test_missing_scope_is_rejected(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=1)
    response = client.post(
        "/jobs",
        data={
            "application_id": "app-a",
            "file": (io.BytesIO(pdf.read_bytes()), "text.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert client.get("/jobs").status_code == 400


def test_invalid_pdf_is_rejected(api):
    client, service, engine = api
    response = client.post(
        "/jobs",
        data={
            "tenant_id": "tenant-a",
            "application_id": "app-a",
            "file": (io.BytesIO(b"not a pdf"), "bad.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_missing_file_is_rejected(api):
    client, service, engine = api
    response = client.post(
        "/jobs",
        data={"tenant_id": "tenant-a", "application_id": "app-a"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_resume_completed_job(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=2)
    job = _upload(client, pdf).get_json()
    response = client.post(
        f"/jobs/{job['job_id']}/resume{_query()}",
        data={"retry_failed": "false", "wait": "true"},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"


def test_result_before_completion_is_conflict(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=1)
    job, _ = service.create_job(pdf, "tenant-a", "app-a")
    response = client.get(f"/jobs/{job.job_id}/result{_query()}")
    assert response.status_code == 409


def test_async_ingest(api, tmp_path):
    client, service, engine = api
    pdf = make_text_pdf(tmp_path / "text.pdf", pages=2)
    response = _upload(client, pdf, wait="false")
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]

    for _ in range(50):
        response = client.get(f"/jobs/{job_id}{_query()}")
        if response.get_json()["status"] in {
            "completed",
            "completed_with_errors",
            "failed",
        }:
            break
        time.sleep(0.05)

    assert response.get_json()["status"] == "completed"
