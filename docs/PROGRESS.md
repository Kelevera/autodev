# Progress Tracker

Status legend: [ ] pending · [~] in progress · [x] done

- [x] Phase 0 — Bootstrap: structure, deps, git init, docs
- [x] Phase 1 — Database & state (db/store.py + tests) — 11 tests passing
- [x] Phase 2 — Scanner & analyzer (+ planner.py per spec layout) — 19 tests passing
- [x] Phase 3 — LLM client & prompts + utils — 19 tests passing
- [x] Phase 4 — Git manager & executor — 14 tests passing (63 total)
- [x] Phase 5 — CLI + config.py — 8 tests passing (71 total)
- [x] Phase 6 — Web dashboard — 6 tests passing (77 total); routes verified live in browser
- [x] Phase 7 — Config, Docker, CI/CD, README, LICENSE — ruff clean, 92% coverage
- [x] Phase 8 — Self-improvement demo: 3 merged LLM improvements via local Ollama
      (qwen2.5:7b), 5 failures auto-reverted
- [x] Phase 9 — Final testing & polish: 79 tests, 92.38% coverage (gate 80%),
      ruff check + format clean, final self-scan 35 → 30 issues
- [x] Phase 10 — Published to https://github.com/Kelevera/autodev (main + v1.0.0
      tag + 3 autodev/* demo branches); CI green on main (79 tests, 92.38% coverage)

## Notes

- Environment: Windows 11, Python 3.14.2, git 2.54, uv installed via pip
  (`python -m uv`), gh CLI not detected (Phase 10 will use plain git push).
- Repo root: `autodev/` inside the project workspace.
- One test file was authored by autodev itself (tests/test_prompts.py); two
  modules carry LLM-written docstrings (executor, git_manager), human-reviewed.
- Docker image verified after a slow Docker Desktop cold start: `docker build`
  succeeds and `docker run --rm autodev:v1 --help` serves the CLI from the
  container (engine 29.5.3).
- CI runs on the two docstring demo branches fail by design: they are
  pre-review snapshots and contain the style issues cleaned up on main.

## Skipped tests

(none — all 79 tests pass unskipped)

## Round 2 (post-publish, 2026-07-15)

All 8 remaining jobs executed against Ollama/qwen2.5:7b: **3 completed, 5
failed-and-reverted**. Review outcomes:

- MERGED `add_tests store.py` — 10 solid tests using `:memory:` SQLite; the
  hardened prompt eliminated round 1's timestamp flakiness (suite now 89 tests).
- MERGED `add_docstrings git_manager.py` — proper `__init__` docstring; module
  docstring dropped again and restored in review.
- REJECTED `add_docstrings cli.py` — tests passed, but the change added no
  docstrings, collapsed PEP8 blank lines, and introduced annotations referencing
  unimported names (masked by `from __future__ import annotations`). Branch
  deleted. New lesson: a green suite is necessary, not sufficient — style/lint
  gates belong in the executor's validation step (future work: run `ruff check`
  before committing a job).
- Failures: app.py tests (TestClient without lifespan), scanner refactor
  (broke public API, caught by suite), config/planner tests (env-dependent
  asserts, wrong constructor), client.py docstrings (persistent syntax errors).

## Lessons Learned

1. **Small local models write flaky tests.** qwen2.5:7b asserted on exact
   timestamps, auto-increment ids, and environment values. The fix wasn't a
   bigger model — it was a tighter prompt (explicit "never assert on..." rules)
   and trusting the pytest gate to reject the rest. After hardening, add_tests
   succeeded on attempt 1.
2. **Timeouts must fit the slowest backend.** A 210-line file at ~14 tok/s
   blows a 180s HTTP timeout; whole-file rewrites need 600s for local 7B models.
3. **Whole-file rewrites lose content.** The model silently dropped module
   docstrings while adding function docstrings. Human review before merge
   caught it; a future diff-based validation step could catch it automatically.
4. **Revert-by-default is the right architecture.** 5 of 8 LLM attempts failed;
   every failure left main untouched and cleaned up its branch. The system is
   safe to run unattended precisely because failure is cheap.
5. **Test-file naming conventions matter.** The scanner's missing-test check
   maps `mod.py -> test_mod.py`; suites named differently (test_web.py for
   app.py, test_db.py for store.py) show up as false-positive "missing tests".
   Acceptable noise; a coverage-based check would be more precise.
