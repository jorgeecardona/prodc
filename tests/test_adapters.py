"""Adapters: pytest class-based node ids (#6) and the files adapter (#7)."""

from __future__ import annotations

from pathlib import Path

from prodc.adapters import AcceptAdapter, FilesAdapter, FrontmatterAdapter, PytestAdapter
from prodc.model import ProofState


def _pytest_file(tmp_path: Path) -> PytestAdapter:
    (tmp_path / "test_x.py").write_text(
        "class TestX:\n"
        "    def test_y(self):\n"
        "        assert True\n"
        "\n"
        "def test_z():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    return PytestAdapter(root=tmp_path, results=None)


def test_pytest_resolves_class_based_node_id(tmp_path: Path) -> None:
    adapter = _pytest_file(tmp_path)
    r = adapter.resolve("test_x.py::TestX::test_y")
    assert r.state is ProofState.DELIVERED and r.declared  # existence only


def test_pytest_resolves_plain_function(tmp_path: Path) -> None:
    assert _pytest_file(tmp_path).resolve("test_x.py::test_z").state is ProofState.DELIVERED


def test_pytest_missing_method_in_class_is_broken(tmp_path: Path) -> None:
    assert _pytest_file(tmp_path).resolve("test_x.py::TestX::test_nope").state is ProofState.BROKEN


def test_pytest_missing_class_is_broken(tmp_path: Path) -> None:
    assert _pytest_file(tmp_path).resolve("test_x.py::TestNope::test_y").state is ProofState.BROKEN


def test_pytest_strips_parametrisation(tmp_path: Path) -> None:
    r = _pytest_file(tmp_path).resolve("test_x.py::TestX::test_y[case1]")
    assert r.state is ProofState.DELIVERED


def test_files_adapter_existence_is_declared(tmp_path: Path) -> None:
    (tmp_path / "verify.py").write_text("# a model\n", encoding="utf-8")
    r = FilesAdapter(root=tmp_path).resolve("verify.py")
    assert r.state is ProofState.DELIVERED and r.declared  # existence != passing


def test_files_adapter_missing_is_broken(tmp_path: Path) -> None:
    assert FilesAdapter(root=tmp_path).resolve("gone.py").state is ProofState.BROKEN


def _frontmatter(tmp_path: Path) -> FrontmatterAdapter:
    (tmp_path / "issues").mkdir()
    (tmp_path / "issues" / "reg.md").write_text(
        "# A-1 Partida doble\n\nbody\n\n## A-6 Factura electrónica\n", encoding="utf-8"
    )
    return FrontmatterAdapter(root=tmp_path, paths=["issues/*.md"])


def test_frontmatter_resolves_existing_heading(tmp_path: Path) -> None:
    a = _frontmatter(tmp_path)
    assert a.resolve("reg.md#A-1").ok
    assert a.resolve("reg.md#A-6").ok  # matches "## A-6 Factura electrónica"


def test_frontmatter_dangling_anchor_or_no_anchor(tmp_path: Path) -> None:
    a = _frontmatter(tmp_path)
    assert not a.resolve("reg.md#A-9").ok  # no such heading
    assert not a.resolve("reg.md#").ok  # no anchor at all


def test_accept_adapter_is_declared_delivered() -> None:
    r = AcceptAdapter().resolve("jane@2026-09-20")
    assert r.state is ProofState.DELIVERED and r.declared  # a human sign-off, not a test
    assert "accepted by jane" in r.detail and "2026-09-20" in r.detail
