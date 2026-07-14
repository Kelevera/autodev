"""Issue prioritization and grouping."""

from __future__ import annotations

from collections import defaultdict

from autodev.core.scanner import Issue

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def prioritize(issues: list[Issue]) -> list[Issue]:
    """Sort issues by severity (critical first), then file and line."""
    return sorted(issues, key=lambda i: (PRIORITY_RANK[i.severity], i.file_path, i.line_no))


def group_by_file(issues: list[Issue]) -> dict[str, list[Issue]]:
    """Group issues by target file, preserving prioritized order within each file."""
    grouped: dict[str, list[Issue]] = defaultdict(list)
    for issue in prioritize(issues):
        grouped[issue.file_path].append(issue)
    return dict(grouped)


def top_severity(issues: list[Issue]) -> str:
    """Return the most severe level present in a list of issues."""
    if not issues:
        return "low"
    return min(issues, key=lambda i: PRIORITY_RANK[i.severity]).severity


def summarize(issues: list[Issue]) -> dict[str, int]:
    """Count issues per type (for CLI/report output)."""
    counts: dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue.issue_type] += 1
    return dict(counts)
