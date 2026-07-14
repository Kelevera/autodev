"""Tests for the FastAPI dashboard (autodev.web.app)."""

import pytest
from fastapi.testclient import TestClient

from autodev.db.store import Store
from autodev.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTODEV_DB_PATH", str(tmp_path / "web-test.db"))
    monkeypatch.setenv("AUTODEV_REPO_PATH", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def seed_job(tmp_path, **updates):
    store = Store(tmp_path / "web-test.db")
    job_id = store.create_job("add_tests", "src/mod.py", description="cover mod")
    if updates:
        store.update_job(job_id, **updates)
    store.close()
    return job_id


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/dashboard"


def test_dashboard_renders(client, tmp_path):
    seed_job(tmp_path)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "autodev" in response.text
    assert "src/mod.py" in response.text
    assert "Trigger Scan" in response.text


def test_job_detail_renders_diff(client, tmp_path):
    job_id = seed_job(
        tmp_path,
        status="completed",
        branch_name="autodev/x",
        diff_summary="+added line\n-removed line",
    )
    response = client.get(f"/job/{job_id}")
    assert response.status_code == 200
    assert "added line" in response.text
    assert "completed" in response.text


def test_job_detail_404(client):
    assert client.get("/job/9999").status_code == 404


def test_api_jobs_and_metrics(client, tmp_path):
    seed_job(tmp_path)
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["type"] == "add_tests"
    assert client.get("/api/metrics").json() == []


def test_trigger_scan_creates_jobs_and_metrics(client):
    response = client.post("/api/trigger-scan")
    assert response.status_code == 200
    assert response.json() == {"status": "scan started"}
    # TestClient runs background tasks before returning, so data is ready:
    metrics = client.get("/api/metrics").json()
    assert any(m["file_path"].endswith("mod.py") for m in metrics)
    assert len(client.get("/api/jobs").json()) >= 1
