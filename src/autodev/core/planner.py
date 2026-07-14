"""Improvement plan generation from prioritized issues."""

from __future__ import annotations

from pydantic import BaseModel

from autodev.core.analyzer import PRIORITY_RANK, group_by_file, top_severity
from autodev.core.scanner import Issue

# Which job addresses which issue type; the plan's job_type comes from the
# most severe issue in the file.
JOB_FOR_ISSUE = {
    "missing_tests": "add_tests",
    "high_complexity": "refactor",
    "long_function": "refactor",
    "large_class": "refactor",
    "missing_docstring": "add_docstrings",
    "missing_type_hints": "add_docstrings",
}


class ImprovementPlan(BaseModel):
    """A per-file plan describing what autodev should improve and how."""

    target_file: str
    job_type: str
    priority: str
    suggested_changes: list[str]
    estimated_effort: str


def _effort(issue_count: int) -> str:
    if issue_count > 10:
        return "high"
    if issue_count > 3:
        return "medium"
    return "low"


def plan_for_file(file_path: str, issues: list[Issue]) -> ImprovementPlan:
    """Build one plan for a file from its (already prioritized) issues."""
    severity = top_severity(issues)
    lead = next(i for i in issues if i.severity == severity)
    changes = [f"line {i.line_no}: {i.description}" for i in issues]
    return ImprovementPlan(
        target_file=file_path,
        job_type=JOB_FOR_ISSUE[lead.issue_type],
        priority=severity,
        suggested_changes=changes,
        estimated_effort=_effort(len(issues)),
    )


def build_plans(issues: list[Issue]) -> list[ImprovementPlan]:
    """Group issues per file and emit plans, most urgent first."""
    grouped = group_by_file(issues)
    plans = [plan_for_file(path, file_issues) for path, file_issues in grouped.items()]
    return sorted(plans, key=lambda p: (PRIORITY_RANK[p.priority], p.target_file))
