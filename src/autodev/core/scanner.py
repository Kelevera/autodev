"""AST-based code scanner: detects quality issues and computes per-file metrics."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

MAX_FUNCTION_LINES = 50
MAX_CLASS_LINES = 300
COMPLEXITY_THRESHOLD = 10

SEVERITIES = {
    "missing_tests": "critical",
    "high_complexity": "high",
    "long_function": "high",
    "large_class": "high",
    "missing_docstring": "medium",
    "missing_type_hints": "low",
}


class Issue(BaseModel):
    """A single code-quality finding."""

    file_path: str
    line_no: int
    issue_type: str
    severity: str
    description: str


def _issue(path: Path, line: int, issue_type: str, description: str) -> Issue:
    return Issue(
        file_path=str(path),
        line_no=line,
        issue_type=issue_type,
        severity=SEVERITIES[issue_type],
        description=description,
    )


def _node_length(node: ast.stmt) -> int:
    end = getattr(node, "end_lineno", None) or node.lineno
    return end - node.lineno + 1


def _is_public(name: str) -> bool:
    return not (name.startswith("__") and name.endswith("__")) or name == "__init__"


def _check_function(node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path) -> list[Issue]:
    """Check one function for docstring, type-hint, and length issues."""
    issues: list[Issue] = []
    if _is_public(node.name) and ast.get_docstring(node) is None:
        description = f"Function '{node.name}' has no docstring"
        issues.append(_issue(path, node.lineno, "missing_docstring", description))
    args = [a for a in [*node.args.args, *node.args.kwonlyargs] if a.arg not in ("self", "cls")]
    unannotated = [a.arg for a in args if a.annotation is None]
    needs_return = node.returns is None and node.name != "__init__"
    if unannotated or needs_return:
        missing = unannotated + (["return"] if needs_return else [])
        issues.append(
            _issue(
                path,
                node.lineno,
                "missing_type_hints",
                f"Function '{node.name}' is missing type hints: {', '.join(missing)}",
            )
        )
    length = _node_length(node)
    if length > MAX_FUNCTION_LINES:
        issues.append(
            _issue(
                path,
                node.lineno,
                "long_function",
                f"Function '{node.name}' is {length} lines (max {MAX_FUNCTION_LINES})",
            )
        )
    return issues


def scan_file(path: Path) -> list[Issue]:
    """Scan one Python file for structural issues (skips unparseable files)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            issues.extend(_check_function(node, path))
        elif isinstance(node, ast.ClassDef) and _node_length(node) > MAX_CLASS_LINES:
            issues.append(
                _issue(
                    path,
                    node.lineno,
                    "large_class",
                    f"Class '{node.name}' is {_node_length(node)} lines (max {MAX_CLASS_LINES})",
                )
            )
    issues.extend(complexity_issues(path))
    return issues


def complexity_issues(path: Path) -> list[Issue]:
    """Flag functions whose radon cyclomatic complexity exceeds the threshold."""
    try:
        from radon.complexity import cc_visit

        blocks = cc_visit(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        _issue(
            path,
            block.lineno,
            "high_complexity",
            f"'{block.name}' has cyclomatic complexity {block.complexity}"
            f" (max {COMPLEXITY_THRESHOLD})",
        )
        for block in blocks
        if block.complexity > COMPLEXITY_THRESHOLD
    ]


def average_complexity(path: Path) -> float:
    """Return the mean cyclomatic complexity of all blocks in a file."""
    try:
        from radon.complexity import cc_visit

        blocks = cc_visit(path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    if not blocks:
        return 0.0
    return round(sum(b.complexity for b in blocks) / len(blocks), 2)


def find_missing_tests(src_dir: Path, tests_dir: Path) -> list[Issue]:
    """Flag source modules that have no matching test file under tests_dir."""
    existing = {p.name for p in tests_dir.rglob("test*.py")} if tests_dir.is_dir() else set()
    issues: list[Issue] = []
    for module in sorted(src_dir.rglob("*.py")):
        if module.name == "__init__.py":
            continue
        stem = module.stem
        covered = (
            f"test_{stem}.py" in existing
            or f"{stem}_test.py" in existing
            or any(n.startswith("test") and n.endswith(f"_{stem}.py") for n in existing)
        )
        if not covered:
            issues.append(
                _issue(module, 1, "missing_tests", f"No test file found for {module.name}")
            )
    return issues


def file_metrics(path: Path, coverage: float | None = None) -> dict[str, Any]:
    """Compute a metrics snapshot (complexity, loc, optional coverage) for a file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    loc = sum(1 for line in lines if line.strip())
    return {
        "file_path": str(path),
        "complexity": average_complexity(path),
        "coverage": coverage,
        "lines_of_code": loc,
    }


def run_coverage(repo_path: Path, timeout: int = 600) -> bool:
    """Run pytest under coverage in repo_path to refresh the .coverage data file."""
    proc = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode == 0


def load_coverage_map(repo_path: Path) -> dict[str, float]:
    """Read per-file coverage percentages from an existing .coverage SQLite file.

    Returns a mapping of resolved absolute file path -> percent covered.
    Returns an empty dict when no coverage data exists.
    """
    data_file = repo_path / ".coverage"
    if not data_file.exists():
        return {}
    try:
        import coverage

        cov = coverage.Coverage(data_file=str(data_file))
        cov.load()
        result: dict[str, float] = {}
        for measured in cov.get_data().measured_files():
            try:
                _, statements, _, missing, _ = cov.analysis2(measured)
            except Exception:
                continue
            if statements:
                pct = 100.0 * (len(statements) - len(missing)) / len(statements)
                result[str(Path(measured).resolve())] = round(pct, 1)
        return result
    except Exception:
        return {}


def scan_project(src_dir: Path, tests_dir: Path | None = None) -> list[Issue]:
    """Scan every Python file under src_dir; optionally check test presence."""
    issues: list[Issue] = []
    for module in sorted(src_dir.rglob("*.py")):
        issues.extend(scan_file(module))
    if tests_dir is not None:
        issues.extend(find_missing_tests(src_dir, tests_dir))
    return issues
