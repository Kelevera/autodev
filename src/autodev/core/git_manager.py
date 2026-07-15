from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from git import Repo


def slugify(text: str, max_len: int = 40) -> str:
    """Turn arbitrary text into a git-branch-safe slug.

    Args:
        text (str): The input text to be slugified.
        max_len (int, optional): Maximum length of the slug. Defaults to 40.

    Returns:
        str: A git-branch-safe slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "job"


class GitManager:
    """Thin wrapper around gitpython for autodev's branch-per-job workflow.

    Attributes:
        repo (Repo): The Git repository object.
        repo_path (Path): Path to the working directory of the repository.
        main_branch (str): Name of the main branch in the repository.
    """

    def __init__(self, repo_path: str | Path = ".") -> None:
        """Initialize a new instance of GitManager.

        Args:
            repo_path (str | Path, optional): The path to the git repository. Defaults to '.'.
        """
        self.repo = Repo(repo_path)
        self.repo_path = Path(self.repo.working_dir)
        self.main_branch = self._detect_main_branch()

    def _detect_main_branch(self) -> str:
        """Detect the main branch name from available branches.

        Returns:
            str: The name of the main branch.
        """
        names = {head.name for head in self.repo.heads}
        for candidate in ("main", "master"):
            if candidate in names:
                return candidate
        return self.repo.active_branch.name

    def get_current_branch(self) -> str:
        """Name of the currently checked-out branch.

        Returns:
            str: The name of the current branch.
        """
        return self.repo.active_branch.name

    def branch_name_for(self, description: str) -> str:
        """Build an `autodev/{timestamp}-{slug}` branch name.

        Args:
            description (str): Description to be slugified and appended to the timestamp.

        Returns:
            str: The new branch name.
        """
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"autodev/{stamp}-{slugify(description)}"

    def create_branch(self, name: str) -> str:
        """Create and check out a new branch; return its name.

        Args:
            name (str): The name of the new branch to be created.

        Returns:
            str: The name of the newly created branch.
        """
        self.repo.git.checkout("-b", name)
        return name

    def checkout(self, branch: str) -> None:
        """Check out an existing branch.

        Args:
            branch (str): The name of the branch to check out.
        """
        self.repo.git.checkout(branch)

    def stage_files(self, file_paths: list[str | Path]) -> None:
        """Stage the given files.

        Args:
            file_paths (list[str | Path]): List of file paths to be staged.
        """
        self.repo.git.add(*[str(p) for p in file_paths])

    def commit(self, message: str) -> str:
        """Commit staged changes; return the new commit's hexsha.

        Args:
            message (str): The commit message.

        Returns:
            str: The hexadecimal SHA of the new commit.
        """
        self.repo.git.commit("-m", message)
        return self.repo.head.commit.hexsha

    def get_diff(self, ref: str = "HEAD") -> str:
        """Diff of the working tree against a ref (default HEAD).

        Args:
            ref (str, optional): The reference to diff against. Defaults to "HEAD".

        Returns:
            str: The diff output.
        """
        return self.repo.git.diff(ref)

    def diff_against_main(self) -> str:
        """Diff of the current branch tip against the main branch.

        Returns:
            str: The diff output.
        """
        return self.repo.git.diff(f"{self.main_branch}...HEAD")

    def revert_to_main(self, remove_paths: list[str | Path] | None = None) -> None:
        """Abandon current work: hard-reset tracked changes, drop the given
        untracked files, and return to the main branch.

        Args:
            remove_paths (list[str | Path] | None, optional): Paths to delete.
                Defaults to None.
        """
        self.repo.git.reset("--hard")
        for path in remove_paths or []:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = self.repo_path / candidate
            candidate.unlink(missing_ok=True)
        if self.get_current_branch() != self.main_branch:
            self.repo.git.checkout(self.main_branch)

    def delete_branch(self, name: str) -> None:
        """Force-delete a branch (used to clean up failed jobs).

        Args:
            name (str): The name of the branch to be deleted.
        """
        if name in {head.name for head in self.repo.heads}:
            self.repo.git.branch("-D", name)
