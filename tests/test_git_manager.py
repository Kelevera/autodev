"""Tests for autodev.core.git_manager against real temporary repositories."""

import pytest
from git import Repo

from autodev.core.git_manager import GitManager, slugify


@pytest.fixture
def repo_dir(tmp_path):
    repo = Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "autodev-test")
        config.set_value("user", "email", "autodev@test.local")
    (tmp_path / "hello.py").write_text("x = 1\n", encoding="utf-8")
    repo.git.add("hello.py")
    repo.git.commit("-m", "initial")
    return tmp_path


@pytest.fixture
def git(repo_dir):
    return GitManager(repo_dir)


def test_slugify():
    assert slugify("Add tests for Scanner Module!") == "add-tests-for-scanner-module"
    assert slugify("___") == "job"
    assert len(slugify("x" * 100)) <= 40


def test_detects_main_branch(git):
    assert git.main_branch == "main"
    assert git.get_current_branch() == "main"


def test_branch_name_format(git):
    name = git.branch_name_for("add tests calc")
    assert name.startswith("autodev/")
    assert name.endswith("-add-tests-calc")


def test_create_checkout_and_delete_branch(git):
    git.create_branch("autodev/test-branch")
    assert git.get_current_branch() == "autodev/test-branch"
    git.checkout("main")
    assert git.get_current_branch() == "main"
    git.delete_branch("autodev/test-branch")
    assert "autodev/test-branch" not in {h.name for h in git.repo.heads}
    git.delete_branch("does-not-exist")  # no error


def test_stage_commit_and_diff(git, repo_dir):
    git.create_branch("autodev/change")
    (repo_dir / "hello.py").write_text("x = 2\n", encoding="utf-8")
    git.stage_files([repo_dir / "hello.py"])
    sha = git.commit("autodev: tweak hello")
    assert len(sha) == 40
    diff = git.diff_against_main()
    assert "-x = 1" in diff and "+x = 2" in diff
    assert git.repo.head.commit.message.startswith("autodev: tweak hello")


def test_revert_to_main_discards_everything(git, repo_dir):
    git.create_branch("autodev/doomed")
    (repo_dir / "hello.py").write_text("broken\n", encoding="utf-8")
    stray = repo_dir / "tests" / "test_generated.py"
    stray.parent.mkdir()
    stray.write_text("junk\n", encoding="utf-8")

    git.revert_to_main(remove_paths=[stray])

    assert git.get_current_branch() == "main"
    assert (repo_dir / "hello.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not stray.exists()


def test_get_diff_of_working_tree(git, repo_dir):
    (repo_dir / "hello.py").write_text("x = 3\n", encoding="utf-8")
    assert "+x = 3" in git.get_diff()
