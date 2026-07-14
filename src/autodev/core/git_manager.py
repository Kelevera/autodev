"""Git operations for autodev: branching, committing, diffing, reverting."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from git import Repo


def slugify(text: str, max_len: int = 40) -> str:
    """Turn arbitrary text into a git-branch-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "job"


class GitManager:
    """Thin wrapper around gitpython for autodev's branch-per-job workflow."""

    def __init__(self, repo_path: str | Path = ".") -> None:
        self.repo = Repo(repo_path)
        self.repo_path = Path(self.repo.working_dir)
        self.main_branch = self._detect_main_branch()

    def _detect_main_branch(self) -> str:
        names = {head.name for head in self.repo.heads}
        for candidate in ("main", "master"):
            if candidate in names:
                return candidate
        return self.repo.active_branch.name

    def get_current_branch(self) -> str:
        """Name of the currently checked-out branch."""
        return self.repo.active_branch.name

    def branch_name_for(self, description: str) -> str:
        """Build an `autodev/{timestamp}-{slug}` branch name."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"autodev/{stamp}-{slugify(description)}"

    def create_branch(self, name: str) -> str:
        """Create and check out a new branch; return its name."""
        self.repo.git.checkout("-b", name)
        return name

    def checkout(self, branch: str) -> None:
        """Check out an existing branch."""
        self.repo.git.checkout(branch)

    def stage_files(self, file_paths: list[str | Path]) -> None:
        """Stage the given files."""
        self.repo.git.add(*[str(p) for p in file_paths])

    def commit(self, message: str) -> str:
        """Commit staged changes; return the new commit's hexsha."""
        self.repo.git.commit("-m", message)
        return self.repo.head.commit.hexsha

    def get_diff(self, ref: str = "HEAD") -> str:
        """Diff of the working tree against a ref (default HEAD)."""
        return self.repo.git.diff(ref)

    def diff_against_main(self) -> str:
        """Diff of the current branch tip against the main branch."""
        return self.repo.git.diff(f"{self.main_branch}...HEAD")

    def revert_to_main(self, remove_paths: list[str | Path] | None = None) -> None:
        """Abandon current work: hard-reset tracked changes, drop the given
        untracked files, and return to the main branch."""
        self.repo.git.reset("--hard")
        for path in remove_paths or []:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = self.repo_path / candidate
            candidate.unlink(missing_ok=True)
        if self.get_current_branch() != self.main_branch:
            self.repo.git.checkout(self.main_branch)

    def delete_branch(self, name: str) -> None:
        """Force-delete a branch (used to clean up failed jobs)."""
        if name in {head.name for head in self.repo.heads}:
            self.repo.git.branch("-D", name)
