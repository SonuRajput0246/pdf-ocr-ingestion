from pathlib import Path

import pytest

from app.errors import InvalidIdentifier, JobNotFound
from app.models import PageRecord
from app.store import FileJobStore, validate_identifier
from tests.helpers import make_job_record


def test_job_and_page_round_trip(tmp_path):
    store = FileJobStore(tmp_path / "store")
    job = make_job_record()
    assert store.create_job(job).job_id == job.job_id
    assert store.get_job(job.tenant_id, job.application_id, job.job_id) is not None

    job.status = "running"
    store.update_job(job)
    assert store.require_job(job.tenant_id, job.application_id, job.job_id).status == "running"

    page = PageRecord(
        page_number=1,
        method="text",
        text="Synthetic page text with enough characters.",
        quality="good",
    )
    store.write_page(job.tenant_id, job.application_id, job.job_id, page)
    loaded = store.read_page(job.tenant_id, job.application_id, job.job_id, 1)
    assert loaded is not None
    assert loaded.text == page.text
    assert len(store.list_pages(job.tenant_id, job.application_id, job.job_id)) == 1


def test_layout_round_trip(tmp_path):
    store = FileJobStore(tmp_path / "store")
    job = make_job_record()
    store.create_job(job)
    store.write_layout(
        job.tenant_id,
        job.application_id,
        job.job_id,
        {"keys": ["header"], "margin": 72, "threshold": 0.6, "page_count": 3},
    )
    assert store.read_layout(job.tenant_id, job.application_id, job.job_id) == {
        "keys": ["header"],
        "margin": 72,
        "threshold": 0.6,
        "page_count": 3,
    }


def test_list_jobs_and_delete(tmp_path):
    store = FileJobStore(tmp_path / "store")
    first = make_job_record(job_id="11111111-1111-1111-1111-111111111111")
    second = make_job_record(
        job_id="22222222-2222-2222-2222-222222222222",
        application_id="app-b",
    )
    store.create_job(first)
    store.create_job(second)

    assert len(store.list_jobs(first.tenant_id)) == 2
    assert len(store.list_jobs(first.tenant_id, "app-a")) == 1

    store.delete_job(first.tenant_id, first.application_id, first.job_id)
    assert store.get_job(first.tenant_id, first.application_id, first.job_id) is None
    with pytest.raises(JobNotFound):
        store.delete_job(first.tenant_id, first.application_id, first.job_id)


def test_tenant_isolation_for_same_job_id(tmp_path):
    store = FileJobStore(tmp_path / "store")
    job = make_job_record(job_id="33333333-3333-3333-3333-333333333333")
    store.create_job(job)
    assert store.get_job("tenant-b", job.application_id, job.job_id) is None


def test_invalid_identifiers_are_rejected(tmp_path):
    store = FileJobStore(tmp_path / "store")
    with pytest.raises(InvalidIdentifier):
        validate_identifier("../escape", "tenant_id")
    with pytest.raises(InvalidIdentifier):
        store.get_job("..", "app-a", "33333333-3333-3333-3333-333333333333")


def test_job_store_creates_root(tmp_path: Path):
    root = tmp_path / "nested" / "store"
    FileJobStore(root)
    assert root.is_dir()
