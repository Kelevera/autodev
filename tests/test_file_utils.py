"""Tests for autodev.utils.file_utils."""

from autodev.utils.file_utils import atomic_write, module_name_for, strip_code_fences


def test_atomic_write_creates_parents_and_content(tmp_path):
    target = tmp_path / "deep" / "nested" / "file.py"
    atomic_write(target, "x = 1\n")
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert not target.with_suffix(".py.tmp").exists()


def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "f.py"
    atomic_write(target, "old")
    atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_strip_code_fences_plain_code():
    assert strip_code_fences("x = 1") == "x = 1\n"


def test_strip_code_fences_single_block():
    assert strip_code_fences("```python\nx = 1\n```") == "x = 1\n"
    assert strip_code_fences("```\nx = 1\n```") == "x = 1\n"


def test_strip_code_fences_with_prose_picks_largest_block():
    text = "Here you go:\n```python\nshort\n```\nand\n```python\nmuch_longer_block = True\n```"
    assert strip_code_fences(text) == "much_longer_block = True\n"


def test_module_name_for_src_layout():
    assert module_name_for("src/autodev/core/scanner.py") == "autodev.core.scanner"
    assert module_name_for("C:\\repo\\src\\pkg\\mod.py".replace("\\", "/")) == "pkg.mod"


def test_module_name_for_flat_file():
    assert module_name_for("scripts/helper.py") == "helper"
