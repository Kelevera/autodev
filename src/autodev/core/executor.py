"""Executes improvement jobs: LLM-generated code, validated, tested, committed.

Pipeline per job: create branch -> read target -> prompt LLM -> strip fences ->
ast.parse validation -> atomic write -> pytest -> commit (pass) or feed the
error back to the LLM and retry; after max_retries, revert and delete the branch.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from autodev.core.git_manager import GitManager
from autodev.core.planner import ImprovementPlan
from autodev.db.store import Store, utcnow
from autodev.llm import prompts
from autodev.llm.client import LLMClient
from autodev.utils.file_utils import atomic_write, module_name_for, strip_code_fences


def create_jobs_from_plans(store: Store, plans: list[ImprovementPlan]) -> list[int]:
    """
    Persist plans as pending jobs, skipping files that already have open jobs.

    Args:
        store (Store): The database store for job and plan information.
        plans (list[ImprovementPlan]): A list of improvement plans to be executed.

    Returns:
        list[int]: A list of IDs for the created jobs.
    """
    job_ids = []
    for plan in plans:
        if store.has_open_job_for(plan.target_file):
            continue
        job_ids.append(
            store.create_job(
                plan.job_type,
                plan.target_file,
                description="; ".join(plan.suggested_changes[:5]),
            )
        )
    return job_ids


class Executor:
    """
    Runs pending jobs end to end against a git repository.
    """

    def __init__(
        self,
        store: Store,
        git: GitManager,
        llm: LLMClient,
        repo_path: str | Path = ".",
        tests_dir: str = "tests",
        max_retries: int = 2,
        test_timeout: int = 300,
    ) -> None:
        """
        Initializes the Executor with necessary components.

        Args:
            store (Store): The database store for job and plan information.
            git (GitManager): Git operations manager.
            llm (LLMClient): Language model client for generating code improvements.
            repo_path (str | Path, optional): The path to the repository. Defaults to ".".
            tests_dir (str, optional): The directory containing test files. Defaults to "tests".
            max_retries (int, optional): Maximum number of retries for a job. Defaults to 2.
            test_timeout (int, optional): Timeout for running tests in seconds. Defaults to 300.
        """
        self.store = store
        self.git = git
        self.llm = llm
        self.repo_path = Path(repo_path)
        self.tests_dir = tests_dir
        self.max_retries = max_retries
        self.test_timeout = test_timeout

    # -- job creation ---------------------------------------------------------

    def create_jobs_from_plans(self, plans: list[ImprovementPlan]) -> list[int]:
        """
        Persist plans as pending jobs, skipping files with open jobs.

        Args:
            plans (list[ImprovementPlan]): A list of improvement plans to be executed.

        Returns:
            list[int]: A list of IDs for the created jobs.
        """
        return create_jobs_from_plans(self.store, plans)

    # -- job execution ----------------------------------------------------------

    def execute_job(self, job: dict) -> bool:
        """
        Run one job; returns True when the improvement was committed.

        Args:
            job (dict): The job details including type and target file.

        Returns:
            bool: True if the job was successfully executed and committed.
        """
        target = Path(job["target_file"])
        write_path = self._write_path_for(job["type"], target)
        branch = self.git.branch_name_for(f"{job['type']}-{target.stem}")
        self.store.update_job(job["id"], status="running", branch_name=branch)
        self.git.create_branch(branch)
        try:
            success, detail = self._improve(job, target, write_path)
        except Exception as exc:  # LLM/config errors must not leave a stray branch
            success, detail = False, f"error: {exc}"
        if success:
            diff = self.git.diff_against_main()
            self.git.checkout(self.git.main_branch)
            self.store.update_job(
                job["id"], status="completed", completed_at=utcnow(),
                result=detail, diff_summary=diff,
            )
            return True
        self.git.revert_to_main(remove_paths=[write_path] if write_path != target else None)
        self.git.delete_branch(branch)
        self.store.update_job(
            job["id"], status="failed", completed_at=utcnow(), result=detail,
        )
        return False

    def execute_pending(self, max_jobs: int = 3) -> list[tuple[int, bool]]:
        """
        Execute up to max_jobs pending jobs; returns (job_id, success) pairs.

        Args:
            max_jobs (int, optional): Maximum number of jobs to execute. Defaults to 3.

        Returns:
            list[tuple[int, bool]]: A list of tuples containing job IDs and their execution status.
        """
        results = []
        for job in self.store.get_pending_jobs()[:max_jobs]:
            results.append((job["id"], self.execute_job(job)))
        return results

    # -- internals ----------------------------------------------------------

    def _write_path_for(self, job_type: str, target: Path) -> Path:
        """
        Determine the write path based on the job type and target file.

        Args:
            job_type (str): The type of job.
            target (Path): The target file for the job.

        Returns:
            Path: The path to the file where the generated code will be written.
        """
        if job_type == "add_tests":
            return self.repo_path / self.tests_dir / f"test_{target.stem}.py"
        return target

    def _improve(self, job: dict, target: Path, write_path: Path) -> tuple[bool, str]:
        """
        Generate and apply code improvements.

        Args:
            job (dict): The job details including type and target file.
            target (Path): The target file for the job.
            write_path (Path): The path to the file where the generated code will be written.

        Returns:
            tuple[bool, str]: Whether the improvement succeeded, and a detail message.
        """
        source = target.read_text(encoding="utf-8")
        module = module_name_for(target)
        error = ""
        for attempt in range(1, self.max_retries + 2):
            prompt = prompts.build_prompt(job["type"], source, module_name=module, error=error)
            raw = self.llm.generate(prompt, system=prompts.SYSTEM_PROMPT)
            code = strip_code_fences(raw)
            try:
                ast.parse(code)
            except SyntaxError as exc:
                error = f"Generated code has a syntax error: {exc}"
                continue
            atomic_write(write_path, code)
            passed, output = self._run_tests(write_path if job["type"] == "add_tests" else None)
            if passed:
                self.git.stage_files([write_path])
                self.git.commit(f"autodev: {job['type'].replace('_', ' ')} for {target.name}")
                return True, f"tests passed on attempt {attempt}"
            error = output
        return False, f"failing after {self.max_retries + 1} attempts: {error[-1000:]}"

    def _run_tests(self, test_path: Path | None = None) -> tuple[bool, str]:
        """
        Run pytest (whole suite or one file for freshly generated tests).

        Args:
            test_path (Path | None, optional): The path to the test file. Defaults to None.

        Returns:
            tuple[bool, str]: A tuple indicating whether the tests passed and a detail message.
        """
        cmd = [sys.executable, "-m", "pytest", "-q", "-x"]
        if test_path is not None:
            cmd.append(str(test_path))
        proc = subprocess.run(
            cmd, cwd=self.repo_path, capture_output=True, text=True, timeout=self.test_timeout,
        )
        # Exit code 5 = "no tests collected": acceptable for a whole-suite run
        # (repo may have no tests yet), never for a freshly generated test file.
        passed = proc.returncode == 0 or (test_path is None and proc.returncode == 5)
        return passed, (proc.stdout + proc.stderr)[-4000:]
