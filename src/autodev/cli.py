"""autodev command-line interface (typer)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autodev.config import Settings, get_settings
from autodev.core import analyzer, planner, scanner
from autodev.core.executor import create_jobs_from_plans
from autodev.db.store import Store

app = typer.Typer(help="autodev — a codebase that maintains itself.", no_args_is_help=True)
console = Console()

ENV_TEMPLATE = """\
# autodev configuration — defaults favor free local Ollama.
AUTODEV_LLM_PROVIDER=ollama
AUTODEV_MODEL=qwen2.5-coder:7b
# AUTODEV_BASE_URL=http://localhost:11434

# Hosted providers instead:
# AUTODEV_LLM_PROVIDER=anthropic
# AUTODEV_API_KEY=sk-ant-...
# AUTODEV_MODEL=claude-sonnet-5

AUTODEV_DB_PATH=autodev.db
AUTODEV_REPO_PATH=.
AUTODEV_SRC_DIR=src
AUTODEV_TESTS_DIR=tests
AUTODEV_MAX_JOBS_PER_RUN=3
"""


def _llm(settings: Settings):
    from autodev.llm.client import create_client

    return create_client(
        settings.llm_provider,
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        max_tokens=settings.max_tokens,
    )


def _executor(settings: Settings, store: Store):
    from autodev.core.executor import Executor
    from autodev.core.git_manager import GitManager

    return Executor(
        store=store,
        git=GitManager(settings.repo_path),
        llm=_llm(settings),
        repo_path=settings.repo_path,
        tests_dir=settings.tests_dir,
    )


def _scan_issues(settings: Settings) -> list[scanner.Issue]:
    src = Path(settings.repo_path) / settings.src_dir
    if not src.is_dir():
        console.print(f"[red]Source directory not found: {src}[/red]")
        raise typer.Exit(1)
    return scanner.scan_project(src, Path(settings.repo_path) / settings.tests_dir)


def _record_metrics(settings: Settings, store: Store) -> None:
    src = Path(settings.repo_path) / settings.src_dir
    coverage_map = scanner.load_coverage_map(Path(settings.repo_path))
    for module in sorted(src.rglob("*.py")):
        if module.name == "__init__.py":
            continue
        metrics = scanner.file_metrics(module, coverage=coverage_map.get(str(module.resolve())))
        store.store_metrics(
            metrics["file_path"], metrics["complexity"],
            metrics["coverage"], metrics["lines_of_code"],
        )


@app.command()
def init() -> None:
    """Create a .env configuration template in the current directory."""
    env_path = Path(".env")
    if env_path.exists():
        console.print(".env already exists — leaving it untouched.")
        raise typer.Exit()
    env_path.write_text(ENV_TEMPLATE, encoding="utf-8")
    console.print("[green]Created .env[/green] — edit it, then run: autodev scan")


@app.command()
def scan() -> None:
    """Scan the source tree for issues and record per-file metrics."""
    settings = get_settings()
    issues = _scan_issues(settings)
    store = Store(settings.db_path)
    _record_metrics(settings, store)
    store.close()

    table = Table(title=f"autodev scan — {len(issues)} issues")
    table.add_column("Severity")
    table.add_column("Type")
    table.add_column("File")
    table.add_column("Line", justify="right")
    for issue in analyzer.prioritize(issues)[:40]:
        table.add_row(issue.severity, issue.issue_type, issue.file_path, str(issue.line_no))
    console.print(table)
    if len(issues) > 40:
        console.print(f"...and {len(issues) - 40} more.")
    for issue_type, count in sorted(analyzer.summarize(issues).items()):
        console.print(f"  {issue_type}: {count}")


@app.command()
def plan() -> None:
    """Turn scan results into pending improvement jobs."""
    settings = get_settings()
    plans = planner.build_plans(_scan_issues(settings))
    store = Store(settings.db_path)
    job_ids = create_jobs_from_plans(store, plans)
    store.close()
    console.print(f"[green]{len(job_ids)} new jobs queued[/green] ({len(plans)} plans total).")
    for item in plans[: len(job_ids) or 5]:
        console.print(f"  [{item.priority}] {item.job_type}: {item.target_file}")


@app.command()
def execute(
    max_jobs: int = typer.Option(None, help="Max jobs to run (default from settings)."),
) -> None:
    """Execute pending jobs: branch, improve via LLM, test, commit."""
    settings = get_settings()
    store = Store(settings.db_path)
    executor = _executor(settings, store)
    results = executor.execute_pending(max_jobs or settings.max_jobs_per_run)
    for job_id, success in results:
        job = store.get_job(job_id)
        color = "green" if success else "red"
        console.print(
            f"[{color}]job {job_id} {job['status']}[/{color}] {job['type']}"
            f" {job['target_file']} ({job['result']})"
        )
    if not results:
        console.print("No pending jobs. Run: autodev plan")
    store.close()


@app.command()
def loop(interval: int = typer.Option(3600, help="Seconds between cycles.")) -> None:
    """Run scan -> plan -> execute continuously."""
    settings = get_settings()
    console.print(f"autodev loop started (interval {interval}s). Ctrl-C to stop.")
    try:
        while True:
            plans = planner.build_plans(_scan_issues(settings))
            store = Store(settings.db_path)
            _record_metrics(settings, store)
            queued = create_jobs_from_plans(store, plans)
            console.print(f"cycle: {len(queued)} jobs queued")
            executor = _executor(settings, store)
            executor.execute_pending(settings.max_jobs_per_run)
            store.close()
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\nautodev loop stopped.")


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    """Serve the web dashboard."""
    import uvicorn

    uvicorn.run("autodev.web.app:app", host=host, port=port)


@app.command()
def status() -> None:
    """Show pending jobs, today's completions, and current coverage."""
    settings = get_settings()
    store = Store(settings.db_path)
    pending = store.get_pending_jobs()
    completed = store.get_completed_jobs()
    today = datetime.now(UTC).date().isoformat()
    completed_today = [j for j in completed if (j["completed_at"] or "").startswith(today)]
    latest = store.get_latest_metrics()
    store.close()

    covered = [m["coverage"] for m in latest if m["coverage"] is not None]
    avg_cov = f"{sum(covered) / len(covered):.1f}%" if covered else "n/a (run coverage first)"
    console.print(f"pending jobs:    {len(pending)}")
    console.print(f"completed today: {len(completed_today)} (all time: {len(completed)})")
    console.print(f"avg coverage:    {avg_cov}")
    for job in pending[:10]:
        console.print(f"  #{job['id']} [{job['type']}] {job['target_file']}")


@app.command()
def review() -> None:
    """LLM-review the diff of the most recent completed job."""
    from autodev.llm import prompts
    from autodev.utils.file_utils import strip_code_fences

    settings = get_settings()
    store = Store(settings.db_path)
    completed = store.get_completed_jobs()
    store.close()
    if not completed:
        console.print("No completed jobs to review.")
        raise typer.Exit()
    job = completed[0]
    diff = job["diff_summary"] or "(empty diff)"
    raw = _llm(settings).generate(prompts.REVIEW_PROMPT.format(diff=diff[:12000]))
    console.print(f"Review of job #{job['id']} ({job['branch_name']}):")
    try:
        verdict = json.loads(strip_code_fences(raw))
        approved = "[green]APPROVED[/green]" if verdict.get("approved") else "[red]REJECTED[/red]"
        console.print(f"{approved} confidence={verdict.get('confidence')}")
        for problem in verdict.get("issues", []):
            console.print(f"  - {problem}")
    except json.JSONDecodeError:
        console.print(raw)


if __name__ == "__main__":
    app()
