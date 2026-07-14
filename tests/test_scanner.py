"""Tests for autodev.core.scanner."""

import textwrap

from autodev.core import scanner

BAD_MODULE = textwrap.dedent(
    '''
    """Module docstring."""

    def documented(x: int) -> int:
        """Has everything."""
        return x

    def undocumented(x):
        return x + 1
    '''
)


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_scan_file_flags_missing_docstring_and_hints(tmp_path):
    path = _write(tmp_path, "mod.py", BAD_MODULE)
    issues = scanner.scan_file(path)
    types = {(i.issue_type, i.description.split("'")[1]) for i in issues}
    assert ("missing_docstring", "undocumented") in types
    assert ("missing_type_hints", "undocumented") in types
    assert not any(
        "documented'" in i.description and i.issue_type == "missing_docstring"
        for i in issues
        if "un" not in i.description
    )


def test_scan_file_clean_function_has_no_issues(tmp_path):
    path = _write(
        tmp_path,
        "clean.py",
        '''
        """Clean module."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        ''',
    )
    assert scanner.scan_file(path) == []


def test_scan_file_flags_long_function(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(60))
    path = _write(tmp_path, "long.py", f'def big() -> None:\n    """Doc."""\n{body}\n')
    issues = scanner.scan_file(path)
    assert any(i.issue_type == "long_function" for i in issues)


def test_scan_file_flags_large_class(tmp_path):
    methods = "\n".join(
        f'    def m{i}(self) -> None:\n        """Doc."""\n        pass\n' for i in range(110)
    )
    path = _write(tmp_path, "bigclass.py", f'class Huge:\n    """Doc."""\n{methods}')
    issues = scanner.scan_file(path)
    assert any(i.issue_type == "large_class" for i in issues)


def test_scan_file_skips_syntax_errors(tmp_path):
    path = _write(tmp_path, "broken.py", "def broken(:\n")
    assert scanner.scan_file(path) == []


def test_complexity_issue_detected(tmp_path):
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    code = f'def switch(x: int) -> int:\n    """Doc."""\n{branches}\n    return -1\n'
    path = _write(tmp_path, "complex.py", code)
    issues = scanner.complexity_issues(path)
    assert len(issues) == 1
    assert issues[0].issue_type == "high_complexity"
    assert issues[0].severity == "high"


def test_average_complexity(tmp_path):
    path = _write(
        tmp_path,
        "avg.py",
        """
        def a(x: int) -> int:
            return x

        def b(x: int) -> int:
            if x:
                return 1
            return 0
        """,
    )
    assert 1.0 <= scanner.average_complexity(path) <= 2.0


def test_find_missing_tests(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "covered.py").write_text("x = 1\n")
    (src / "uncovered.py").write_text("y = 2\n")
    (src / "client.py").write_text("z = 3\n")
    (src / "__init__.py").write_text("")
    (tests / "test_covered.py").write_text("def test_x(): pass\n")
    (tests / "test_llm_client.py").write_text("def test_z(): pass\n")

    issues = scanner.find_missing_tests(src, tests)
    flagged = {i.file_path.split("\\")[-1].split("/")[-1] for i in issues}
    assert flagged == {"uncovered.py"}
    assert all(i.severity == "critical" for i in issues)


def test_file_metrics(tmp_path):
    path = _write(
        tmp_path,
        "metrics.py",
        """
        def f(x: int) -> int:
            return x
        """,
    )
    metrics = scanner.file_metrics(path, coverage=75.0)
    assert metrics["lines_of_code"] == 2
    assert metrics["coverage"] == 75.0
    assert metrics["complexity"] >= 1.0


def test_load_coverage_map_missing_file(tmp_path):
    assert scanner.load_coverage_map(tmp_path) == {}


def test_scan_project(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write(src, "mod.py", BAD_MODULE)
    issues = scanner.scan_project(src, tests_dir=tmp_path / "tests")
    types = {i.issue_type for i in issues}
    assert "missing_docstring" in types
    assert "missing_tests" in types
