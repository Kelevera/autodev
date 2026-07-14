# Autodev Architecture

Autodev is a self-improving codebase: it scans Python source for quality issues,
plans improvements, uses an LLM to generate fixes on isolated git branches, runs
the test suite, and commits only what passes.

## Tech stack

| Concern      | Choice                                    |
|--------------|-------------------------------------------|
| Language     | Python 3.12+                               |
| Packaging    | uv (pip fallback)                          |
| CLI          | typer                                      |
| Web          | FastAPI + Jinja2 (Tailwind/htmx/Chart.js via CDN) |
| Database     | sqlite3 (stdlib, no ORM)                   |
| Git          | gitpython                                  |
| Testing      | pytest + pytest-cov + coverage             |
| Lint/metrics | ruff, radon                                |
| HTTP         | httpx                                      |
| Config       | pydantic-settings (`AUTODEV_*` env vars, `.env`) |

## Data flow

```
scan  →  Issues  →  analyze  →  ImprovementPlans  →  jobs (SQLite)
                                                        │
        ┌───────────────────────────────────────────────┘
        ▼
execute: branch → LLM generates code → ast.parse validation →
         atomic write → pytest → commit (pass) / revert + delete branch (fail)
```

Successful jobs live on `autodev/{timestamp}-{slug}` branches for human review;
autodev never merges to main by itself.

## Modules (src/autodev/)

- `config.py` — `Settings` (pydantic-settings), env prefix `AUTODEV_`.
- `cli.py` — typer commands: init, scan, plan, execute, loop, dashboard, status, review.
- `core/scanner.py` — ast-based issue detection (missing docstrings/type hints,
  long functions >50 lines, large classes >300 lines, missing test files),
  radon cyclomatic complexity (>10 flagged), coverage.py integration
  (`run_coverage`, `load_coverage_map`), per-file metrics. Emits `Issue` models.
- `core/analyzer.py` — prioritizes issues (missing tests=critical,
  complexity=high, docstrings=medium, type hints=low), groups per file, emits
  `ImprovementPlan` models with a `job_type`: add_tests | refactor | add_docstrings.
- `core/executor.py` — runs a job end to end (see data flow). Retries up to 2
  times feeding pytest errors back into the prompt. All writes atomic
  (tmp file + os.replace).
- `core/git_manager.py` — `GitManager`: create_branch, checkout, stage_files,
  commit, get_diff, diff_against_main, revert_to_main, delete_branch.
  Branch names `autodev/{ts}-{slug}`; conventional commits (`autodev: ...`).
- `llm/client.py` — `LLMClient` ABC + Anthropic / OpenAI-compatible / Ollama /
  Mock implementations over httpx. Retries 429/5xx/connection errors
  (default wait 60s, 3 retries). `create_client()` factory.
- `llm/prompts.py` — TEST_GENERATION / REFACTOR / DOCSTRING / REVIEW prompt
  templates; all demand raw code or JSON, never markdown.
- `db/store.py` — thread-safe (threading.Lock) SQLite `Store`.
  Tables: `jobs(id, status, type, target_file, description, branch_name,
  created_at, completed_at, result, diff_summary)`,
  `metrics(id, file_path, complexity, coverage, lines_of_code, timestamp)`.
- `web/app.py` — FastAPI: GET / (redirect), /dashboard, /job/{id},
  /api/jobs, /api/metrics, POST /api/trigger-scan (BackgroundTasks).
- `utils/file_utils.py` — atomic_write, strip_code_fences, module_name_for.

## CLI semantics

- `scan` — detect issues, store metrics, print summary (read-only, no jobs).
- `plan` — scan + convert plans into pending jobs in SQLite.
- `execute --max-jobs N` — run up to N pending jobs.
- `loop --interval S` — scan → plan → execute forever; Ctrl-C safe.

## Conventions

- Every file < 300 lines, functions < 30 lines where practical.
- Pydantic models for all cross-module data (`Issue`, `ImprovementPlan`).
- Jobs statuses: pending → running → completed | failed.
