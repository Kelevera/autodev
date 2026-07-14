"""Tests for the typer CLI (LLM mocked via provider=mock)."""

import pytest
from git import Repo
from typer.testing import CliRunner

from autodev.cli import app
from autodev.db.store import Store

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (src / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    repo = Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "t")
        config.set_value("user", "email", "t@t.local")
    repo.git.add("-A")
    repo.git.commit("-m", "initial")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTODEV_DB_PATH", str(tmp_path / "autodev-test.db"))
    monkeypatch.setenv("AUTODEV_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("AUTODEV_LLM_PROVIDER", "mock")
    return tmp_path


def test_init_creates_env(project):
    (project / ".env").unlink(missing_ok=True)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "AUTODEV_LLM_PROVIDER" in (project / ".env").read_text(encoding="utf-8")

    again = runner.invoke(app, ["init"])
    assert "already exists" in again.stdout


def test_scan_reports_issues_and_stores_metrics(project):
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    assert "missing_docstring" in result.stdout
    assert "missing_tests" in result.stdout

    store = Store(project / "autodev-test.db")
    metrics = store.get_latest_metrics()
    store.close()
    assert any(m["file_path"].endswith("mod.py") for m in metrics)


def test_scan_fails_without_src(project, monkeypatch):
    monkeypatch.setenv("AUTODEV_SRC_DIR", "nonexistent")
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 1


def test_plan_queues_jobs(project):
    result = runner.invoke(app, ["plan"])
    assert result.exit_code == 0
    assert "new jobs queued" in result.stdout

    store = Store(project / "autodev-test.db")
    pending = store.get_pending_jobs()
    store.close()
    assert len(pending) >= 1

    rerun = runner.invoke(app, ["plan"])
    assert "0 new jobs queued" in rerun.stdout


def test_status_reports_counts(project):
    runner.invoke(app, ["plan"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "pending jobs:" in result.stdout
    assert "avg coverage:" in result.stdout


def test_execute_without_jobs(project):
    result = runner.invoke(app, ["execute"])
    assert result.exit_code == 0
    assert "No pending jobs" in result.stdout


def test_review_without_jobs(project):
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "No completed jobs" in result.stdout


def test_review_with_completed_job(project):
    store = Store(project / "autodev-test.db")
    job_id = store.create_job("refactor", "src/pkg/mod.py")
    store.update_job(job_id, status="completed", branch_name="autodev/x",
                     diff_summary="+ improved = True")
    store.close()
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "mock response" in result.stdout
