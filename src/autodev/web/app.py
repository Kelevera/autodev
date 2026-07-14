"""FastAPI web dashboard for autodev."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from autodev.config import get_settings
from autodev.db.store import Store

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open the store for the app's lifetime."""
    settings = get_settings()
    state["settings"] = settings
    state["store"] = Store(settings.db_path)
    yield
    state["store"].close()
    state.clear()


app = FastAPI(title="autodev", lifespan=lifespan)


def _run_scan() -> None:
    """Background task: scan the configured repo, record metrics, queue jobs."""
    from autodev.core import planner, scanner
    from autodev.core.executor import create_jobs_from_plans

    settings = state["settings"]
    src = Path(settings.repo_path) / settings.src_dir
    if not src.is_dir():
        return
    issues = scanner.scan_project(src, Path(settings.repo_path) / settings.tests_dir)
    store: Store = state["store"]
    coverage_map = scanner.load_coverage_map(Path(settings.repo_path))
    for module in sorted(src.rglob("*.py")):
        if module.name == "__init__.py":
            continue
        metrics = scanner.file_metrics(module, coverage=coverage_map.get(str(module.resolve())))
        store.store_metrics(
            metrics["file_path"],
            metrics["complexity"],
            metrics["coverage"],
            metrics["lines_of_code"],
        )
    create_jobs_from_plans(store, planner.build_plans(issues))


@app.get("/")
def root() -> RedirectResponse:
    """Redirect to the dashboard."""
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
def dashboard(request: Request):
    """Render the main dashboard: job table, metrics chart, scan trigger."""
    store: Store = state["store"]
    jobs = store.get_all_jobs()
    metrics = store.get_latest_metrics()
    counts = {
        "pending": sum(1 for j in jobs if j["status"] == "pending"),
        "running": sum(1 for j in jobs if j["status"] == "running"),
        "completed": sum(1 for j in jobs if j["status"] == "completed"),
        "failed": sum(1 for j in jobs if j["status"] == "failed"),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"jobs": jobs[:50], "metrics": metrics, "counts": counts},
    )


@app.get("/job/{job_id}")
def job_detail(request: Request, job_id: int):
    """Render one job with its full diff."""
    job = state["store"].get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return templates.TemplateResponse(request, "job_detail.html", {"job": job})


@app.get("/api/jobs")
def api_jobs() -> list[dict[str, Any]]:
    """All jobs as JSON, newest first."""
    return state["store"].get_all_jobs()


@app.get("/api/metrics")
def api_metrics() -> list[dict[str, Any]]:
    """Latest metrics snapshot per file as JSON."""
    return state["store"].get_latest_metrics()


@app.post("/api/trigger-scan")
def trigger_scan(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Kick off a scan in the background."""
    background_tasks.add_task(_run_scan)
    return {"status": "scan started"}
