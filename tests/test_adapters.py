"""Adapters: pytest class-based node ids (#6) and the files adapter (#7)."""

from __future__ import annotations

from pathlib import Path

from prodc.adapters import (
    AcceptAdapter,
    CoverageAdapter,
    External,
    FieldAdapter,
    FilesAdapter,
    FrontmatterAdapter,
    PrototypeAdapter,
    PytestAdapter,
)
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


def test_external_unresolved_when_sibling_absent(tmp_path: Path) -> None:
    ext = External(FilesAdapter(root=tmp_path / "sib"), tmp_path / "sib")  # not checked out
    r = ext.resolve("verify.py")
    assert r.state is ProofState.UNRESOLVED and not r.declared


def test_prototype_adapter_declared_delivered() -> None:
    r = PrototypeAdapter().resolve("fig-12@users@2026-09-20")
    assert r.state is ProofState.DELIVERED and r.declared
    assert "prototype fig-12" in r.detail and "users" in r.detail


def test_coverage_adapter(tmp_path: Path) -> None:
    (tmp_path / "catalog.txt").write_text(
        "billing/invoices\n# a comment\nroasting/queue\n", encoding="utf-8"
    )
    a = CoverageAdapter(root=tmp_path, catalog="catalog.txt")
    assert a.resolve("billing/invoices").state is ProofState.DELIVERED
    assert a.resolve("shipping/labels").state is ProofState.PENDING  # not yet covered


def test_field_adapter(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text(
        '{"surfaced": ["total"], "received": ["total", "tax_id"]}', encoding="utf-8"
    )
    a = FieldAdapter(root=tmp_path, schema="schema.json")
    assert a.resolve("total").state is ProofState.DELIVERED
    r = a.resolve("tax_id")
    assert r.state is ProofState.PENDING and "received but not surfaced" in r.detail
    r2 = a.resolve("missing")
    assert r2.state is ProofState.PENDING and "not received upstream" in r2.detail


def test_external_reads_sibling_and_records_rev(tmp_path: Path) -> None:
    sib = tmp_path / "sib"
    sib.mkdir()
    (sib / "verify.py").write_text("# model\n", encoding="utf-8")
    (sib / ".git").mkdir()
    (sib / ".git" / "HEAD").write_text("abc1234def5678\n", encoding="utf-8")  # detached HEAD
    r = External(FilesAdapter(root=sib), sib).resolve("verify.py")
    assert r.state is ProofState.DELIVERED
    assert "@ sib:abc1234" in r.detail  # traceable to the sibling's exact revision


def _gherkin_with_results(tmp_path: Path, feature: str, feature_name: str, results: object):
    import json as _json

    from prodc.adapters import GherkinAdapter

    (tmp_path / feature_name).write_text(feature, encoding="utf-8")
    (tmp_path / "results.json").write_text(_json.dumps(results), encoding="utf-8")
    return GherkinAdapter(
        root=tmp_path,
        paths=["*.feature"],
        delivered_tags=["@done"],
        pending_tags=[],
        results="results.json",
    )


def _passed(n: int) -> list[dict[str, object]]:
    return [{"result": {"status": "passed"}} for _ in range(n)]


def _failed() -> list[dict[str, object]]:
    return [{"result": {"status": "failed"}}]


def test_gherkin_results_no_crossfile_collision(tmp_path: Path) -> None:
    # two features, same scenario name, different outcomes — must not overwrite each other (#42)
    (tmp_path / "a.feature").write_text(
        "@done\nFeature: A\n  Scenario: Happy path\n    Given a\n    Then b\n", encoding="utf-8"
    )
    (tmp_path / "b.feature").write_text(
        "@done\nFeature: B\n  Scenario: Happy path\n    Given a\n    Then b\n", encoding="utf-8"
    )
    import json as _json

    (tmp_path / "results.json").write_text(
        _json.dumps(
            [
                {"uri": "a.feature", "elements": [{"name": "Happy path", "steps": _passed(2)}]},
                {"uri": "b.feature", "elements": [{"name": "Happy path", "steps": _failed()}]},
            ]
        ),
        encoding="utf-8",
    )
    from prodc.adapters import GherkinAdapter

    a = GherkinAdapter(
        root=tmp_path,
        paths=["*.feature"],
        delivered_tags=["@done"],
        pending_tags=[],
        results="results.json",
    )
    assert a.resolve("a.feature#Happy path").state is ProofState.DELIVERED
    assert a.resolve("b.feature#Happy path").state is ProofState.PENDING  # failing, not masked


def test_gherkin_outline_examples_anded(tmp_path: Path) -> None:
    # one outline, two example rows sharing the name; one fails → PENDING, not last-write-wins (#42)
    feature = "@done\nFeature: X\n  Scenario Outline: Export\n    Given <n>\n    Then ok\n"
    a = _gherkin_with_results(
        tmp_path,
        feature,
        "x.feature",
        [
            {
                "uri": "x.feature",
                "elements": [
                    {"name": "Export", "steps": _passed(2)},
                    {"name": "Export", "steps": _failed()},
                ],
            },
        ],
    )
    assert a.resolve("x.feature#Export").state is ProofState.PENDING


def test_gherkin_scenario_missing_from_report_not_declared(tmp_path: Path) -> None:
    # results wired but this scenario never ran — must NOT fall through to the @done tag (#41)
    feature = "@done\nFeature: X\n  Scenario: Smoke\n    Given a\n    Then b\n"
    a = _gherkin_with_results(
        tmp_path,
        feature,
        "x.feature",
        [
            {"uri": "x.feature", "elements": [{"name": "Other", "steps": _passed(1)}]},
        ],
    )
    r = a.resolve("x.feature#Smoke")
    assert r.state is ProofState.PENDING and not r.declared
    assert "not in report" in r.detail
