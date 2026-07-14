"""End-to-end Executor tests using a real temp repo and the MockLLMClient."""

import pytest
from git import Repo

from autodev.core.executor import Executor
from autodev.core.git_manager import GitManager
from autodev.core.planner import ImprovementPlan
from autodev.db.store import Store
from autodev.llm.client import MockLLMClient

PASSING_TEST = "def test_ok():\n    assert 1 + 1 == 2\n"
FAILING_TEST = "def test_bad():\n    assert False\n"
BROKEN_CODE = "def broken(:\n"


@pytest.fixture
def repo_dir(tmp_path):
    repo = Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "autodev-test")
        config.set_value("user", "email", "autodev@test.local")
    (tmp_path / "calc.py").write_text(
        'def add(a, b):\n    return a + b\n', encoding="utf-8"
    )
    repo.git.add("calc.py")
    repo.git.commit("-m", "initial")
    return tmp_path


@pytest.fixture
def store(tmp_path_factory):
    s = Store(tmp_path_factory.mktemp("db") / "test.db")
    yield s
    s.close()


def make_executor(repo_dir, store, responses, max_retries=2):
    llm = MockLLMClient(responses=responses)
    executor = Executor(
        store=store,
        git=GitManager(repo_dir),
        llm=llm,
        repo_path=repo_dir,
        max_retries=max_retries,
    )
    return executor, llm


def test_add_tests_job_success(repo_dir, store):
    executor, llm = make_executor(repo_dir, store, [PASSING_TEST])
    job_id = store.create_job("add_tests", str(repo_dir / "calc.py"))

    assert executor.execute_job(store.get_job(job_id)) is True

    job = store.get_job(job_id)
    assert job["status"] == "completed"
    assert job["branch_name"].startswith("autodev/")
    assert "test_calc.py" in job["diff_summary"]
    git = GitManager(repo_dir)
    assert git.get_current_branch() == "main"
    assert job["branch_name"] in {h.name for h in git.repo.heads}
    assert "importable as `calc`" in llm.calls[0]["prompt"]


def test_syntax_errors_exhaust_retries_and_revert(repo_dir, store):
    executor, llm = make_executor(repo_dir, store, [BROKEN_CODE] * 3)
    job_id = store.create_job("add_tests", str(repo_dir / "calc.py"))

    assert executor.execute_job(store.get_job(job_id)) is False

    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert "syntax error" in job["result"]
    assert len(llm.calls) == 3
    assert "syntax error" in llm.calls[1]["prompt"]  # error fed back into retry
    git = GitManager(repo_dir)
    assert git.get_current_branch() == "main"
    assert not any(h.name.startswith("autodev/") for h in git.repo.heads)
    assert not (repo_dir / "tests" / "test_calc.py").exists()


def test_failing_tests_feed_error_back(repo_dir, store):
    executor, llm = make_executor(repo_dir, store, [FAILING_TEST, PASSING_TEST])
    job_id = store.create_job("add_tests", str(repo_dir / "calc.py"))

    assert executor.execute_job(store.get_job(job_id)) is True
    assert store.get_job(job_id)["result"] == "tests passed on attempt 2"
    assert "previous attempt failed" in llm.calls[1]["prompt"]


def test_refactor_job_rewrites_target(repo_dir, store):
    improved = 'def add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n'
    executor, _ = make_executor(repo_dir, store, [improved])
    job_id = store.create_job("refactor", str(repo_dir / "calc.py"))

    assert executor.execute_job(store.get_job(job_id)) is True

    job = store.get_job(job_id)
    assert "-> int" in job["diff_summary"]
    # main branch is untouched until a human merges
    assert (repo_dir / "calc.py").read_text(encoding="utf-8").startswith("def add(a, b):")


def test_llm_exception_marks_job_failed(repo_dir, store):
    executor, llm = make_executor(repo_dir, store, [])

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    llm.generate = boom
    job_id = store.create_job("add_tests", str(repo_dir / "calc.py"))
    assert executor.execute_job(store.get_job(job_id)) is False
    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert "provider down" in job["result"]


def test_create_jobs_from_plans_dedupes(repo_dir, store):
    executor, _ = make_executor(repo_dir, store, [])
    plan = ImprovementPlan(
        target_file="calc.py", job_type="add_tests", priority="critical",
        suggested_changes=["line 1: no tests"], estimated_effort="low",
    )
    first = executor.create_jobs_from_plans([plan, plan])
    second = executor.create_jobs_from_plans([plan])
    assert len(first) == 1
    assert second == []


def test_execute_pending_respects_max_jobs(repo_dir, store):
    executor, _ = make_executor(repo_dir, store, [PASSING_TEST])
    for name in ("calc.py",):
        store.create_job("add_tests", str(repo_dir / name))
    store.create_job("add_tests", str(repo_dir / "calc.py"))

    results = executor.execute_pending(max_jobs=1)
    assert len(results) == 1
    assert results[0][1] is True
