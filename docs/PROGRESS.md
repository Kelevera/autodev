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
- [~] Phase 10 — GitHub publish (needs username/repo from user)

## Notes

- Environment: Windows 11, Python 3.14.2, git 2.54, uv installed via pip
  (`python -m uv`), gh CLI not detected (Phase 10 will use plain git push).
- Repo root: `autodev/` inside the project workspace.
- One test file was authored by autodev itself (tests/test_prompts.py); two
  modules carry LLM-written docstrings (executor, git_manager), human-reviewed.

## Skipped tests

(none — all 79 tests pass unskipped)

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
