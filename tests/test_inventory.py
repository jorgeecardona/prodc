"""``inventory()`` on the pytest and vitest proof kinds, which ``suggest`` reads."""

from __future__ import annotations

from pathlib import Path

from prodc.adapters import PytestAdapter, VitestAdapter
from prodc.model import ProofState


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pytest_inventory_lists_functions_and_class_methods(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_a.py",
        "def helper(): ...\n"
        "def test_one(): ...\n"
        "async def test_two(): ...\n"
        "class TestX:\n    def test_three(self): ...\n    def other(self): ...\n"
        "class Helper:\n    def test_no(self): ...\n",
    )
    _write(tmp_path, "tests/test_broken.py", "def (:\n")
    _write(tmp_path, ".venv/lib/test_dep.py", "def test_dep(): ...\n")
    adapter = PytestAdapter(tmp_path, None)
    assert adapter.inventory() == [
        "tests/test_a.py::TestX::test_three",
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two",
    ]
    for proof in adapter.inventory():
        assert adapter.resolve(proof).state is ProofState.DELIVERED


def test_vitest_inventory_lists_titles_and_skips_computed_ones(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/a.test.ts",
        'describe("group", () => {\n'
        '  it("adds", () => {});\n'
        "  test.skip('subtracts', () => {});\n"
        "  it.each([1])(`case ${n}`, () => {});\n"
        "  it(`row ${n}`, () => {});\n"
        '  split("not a test");\n'
        "});\n",
    )
    _write(tmp_path, "node_modules/x/b.test.ts", 'it("dep", () => {});\n')
    adapter = VitestAdapter(tmp_path, None)
    assert adapter.inventory() == ["src/a.test.ts#adds", "src/a.test.ts#subtracts"]
    for proof in adapter.inventory():
        assert adapter.resolve(proof).state is ProofState.DELIVERED


def test_paths_limit_the_inventory(tmp_path: Path) -> None:
    _write(tmp_path, "a/test_a.py", "def test_a(): ...\n")
    _write(tmp_path, "b/test_b.py", "def test_b(): ...\n")
    assert PytestAdapter(tmp_path, None, ["a/*.py"]).inventory() == ["a/test_a.py::test_a"]


def test_discovery_skips_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    (tmp_path / "test_bad.py").write_bytes(b"\xff\xfe")
    _write(tmp_path, "test_ok.py", "def test_ok(): ...\n")
    assert PytestAdapter(tmp_path, None).inventory() == ["test_ok.py::test_ok"]


def test_star_star_matches_the_top_folder_and_star_stays_in_one(tmp_path: Path) -> None:
    _write(tmp_path, "test_top.py", "def test_t(): ...\n")
    _write(tmp_path, "a/b/test_deep.py", "def test_d(): ...\n")
    assert PytestAdapter(tmp_path, None, ["**/test_*.py"]).inventory() == [
        "a/b/test_deep.py::test_d",
        "test_top.py::test_t",
    ]
    assert PytestAdapter(tmp_path, None, ["*/test_*.py"]).inventory() == []
