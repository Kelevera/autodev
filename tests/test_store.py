import pytest
from autodev.db.store import Store

def test_create_job():
    store = Store(":memory:")
    job_id = store.create_job("test", "path/to/file.py")
    assert isinstance(job_id, int)
    job = store.get_job(job_id)
    assert job["status"] == "pending"
    assert job["type"] == "test"
    assert job["target_file"] == "path/to/file.py"

def test_update_job():
    store = Store(":memory:")
    job_id = store.create_job("test", "path/to/file.py")
    store.update_job(job_id, status="running")
    updated_job = store.get_job(job_id)
    assert updated_job["status"] == "running"

def test_get_pending_jobs():
    store = Store(":memory:")
    store.create_job("test1", "path/to/file1.py")
    store.create_job("test2", "path/to/file2.py")
    pending_jobs = store.get_pending_jobs()
    assert len(pending_jobs) == 2
    for job in pending_jobs:
        assert job["status"] == "pending"

def test_get_completed_jobs():
    store = Store(":memory:")
    store.create_job("test1", "path/to/file1.py")
    store.update_job(1, status="completed")
    completed_jobs = store.get_completed_jobs()
    assert len(completed_jobs) == 1
    assert completed_jobs[0]["status"] == "completed"

def test_get_all_jobs():
    store = Store(":memory:")
    store.create_job("test1", "path/to/file1.py")
    store.create_job("test2", "path/to/file2.py")
    all_jobs = store.get_all_jobs()
    assert len(all_jobs) == 2

def test_has_open_job_for():
    store = Store(":memory:")
    job_id = store.create_job("test", "path/to/file.py")
    assert not store.has_open_job_for("path/to/otherfile.py")
    store.update_job(job_id, status="running")
    assert store.has_open_job_for("path/to/file.py")

def test_store_metrics():
    store = Store(":memory:")
    metric_id = store.store_metrics("path/to/file.py", 10.5, 80.0, 200)
    assert isinstance(metric_id, int)

def test_get_metrics_history():
    store = Store(":memory:")
    store.store_metrics("path/to/file.py", 10.5, 80.0, 200)
    metrics_history = store.get_metrics_history()
    assert len(metrics_history) == 1

def test_get_latest_metrics_for_file():
    store = Store(":memory:")
    metric_id = store.store_metrics("path/to/file.py", 10.5, 80.0, 200)
    latest_metric = store.get_latest_metrics_for_file("path/to/file.py")
    assert latest_metric["id"] == metric_id

def test_get_latest_metrics():
    store = Store(":memory:")
    file_path1 = "path/to/file1.py"
    file_path2 = "path/to/file2.py"
    store.store_metrics(file_path1, 10.5, 80.0, 200)
    store.store_metrics(file_path2, 12.3, 90.0, 300)
    latest_metrics = store.get_latest_metrics()
    assert len(latest_metrics) == 2
