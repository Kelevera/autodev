"""Tests for autodev.db.store."""

import threading

import pytest

from autodev.db.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_create_and_get_job(store):
    job_id = store.create_job("add_tests", "src/foo.py", description="needs tests")
    job = store.get_job(job_id)
    assert job["id"] == job_id
    assert job["status"] == "pending"
    assert job["type"] == "add_tests"
    assert job["target_file"] == "src/foo.py"
    assert job["description"] == "needs tests"
    assert job["created_at"]
    assert job["completed_at"] is None


def test_get_missing_job_returns_none(store):
    assert store.get_job(999) is None


def test_update_job(store):
    job_id = store.create_job("refactor", "src/bar.py")
    store.update_job(job_id, status="completed", result="ok", branch_name="autodev/x")
    job = store.get_job(job_id)
    assert job["status"] == "completed"
    assert job["result"] == "ok"
    assert job["branch_name"] == "autodev/x"


def test_update_job_rejects_unknown_field(store):
    job_id = store.create_job("refactor", "src/bar.py")
    with pytest.raises(ValueError, match="unknown job fields"):
        store.update_job(job_id, evil_column="x")


def test_pending_and_completed_queries(store):
    first = store.create_job("add_tests", "a.py")
    second = store.create_job("refactor", "b.py")
    store.update_job(second, status="completed")

    pending = store.get_pending_jobs()
    assert [j["id"] for j in pending] == [first]

    completed = store.get_completed_jobs()
    assert [j["id"] for j in completed] == [second]

    assert len(store.get_all_jobs()) == 2


def test_pending_jobs_are_fifo(store):
    ids = [store.create_job("add_tests", f"f{i}.py") for i in range(3)]
    assert [j["id"] for j in store.get_pending_jobs()] == ids


def test_has_open_job_for(store):
    store.create_job("add_tests", "src/foo.py")
    assert store.has_open_job_for("src/foo.py")
    assert not store.has_open_job_for("src/other.py")


def test_has_open_job_ignores_finished(store):
    job_id = store.create_job("add_tests", "src/foo.py")
    store.update_job(job_id, status="failed")
    assert not store.has_open_job_for("src/foo.py")


def test_store_and_read_metrics(store):
    store.store_metrics("src/foo.py", complexity=3.2, coverage=81.0, lines_of_code=120)
    store.store_metrics("src/foo.py", complexity=2.1, coverage=90.5, lines_of_code=110)
    store.store_metrics("src/bar.py", complexity=1.0, coverage=None, lines_of_code=30)

    history = store.get_metrics_history("src/foo.py")
    assert len(history) == 2
    assert history[0]["coverage"] == 81.0

    latest = store.get_latest_metrics_for_file("src/foo.py")
    assert latest["coverage"] == 90.5
    assert latest["lines_of_code"] == 110

    assert store.get_latest_metrics_for_file("missing.py") is None

    all_history = store.get_metrics_history()
    assert len(all_history) == 3


def test_get_latest_metrics_one_row_per_file(store):
    store.store_metrics("a.py", 1.0, 50.0, 10)
    store.store_metrics("a.py", 1.5, 60.0, 12)
    store.store_metrics("b.py", 2.0, 70.0, 20)

    latest = store.get_latest_metrics()
    assert len(latest) == 2
    by_file = {m["file_path"]: m for m in latest}
    assert by_file["a.py"]["coverage"] == 60.0
    assert by_file["b.py"]["coverage"] == 70.0


def test_concurrent_writes_are_safe(store):
    def writer(n):
        for i in range(20):
            store.create_job("add_tests", f"file_{n}_{i}.py")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.get_all_jobs()) == 100
