"""Test-results reports: unreadable files (#121), pytest junit keys (#122, #123), ``root`` (#124)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.adapters import (
    EvalGateAdapter,
    FieldAdapter,
    GherkinAdapter,
    OutcomeAdapter,
    PytestAdapter,
)
from prodc.config import Config
from prodc.model import ProofState


def _junit(tmp_path: Path, *cases: str) -> None:
    body = "".join(cases)
    (tmp_path / "junit.xml").write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )


def _case(classname: str, name: str, outcome: str = "passed") -> str:
    inner = {"passed": "", "failed": "<failure/>", "skipped": "<skipped/>"}[outcome]
    return f'<testcase classname="{classname}" name="{name}">{inner}</testcase>'


def _two_files(tmp_path: Path) -> PytestAdapter:
    for mod in ("test_orders", "test_invoices"):
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / f"{mod}.py").write_text(
            "def test_rejects_invalid_input():\n    pass\n", encoding="utf-8"
        )
    return PytestAdapter(root=tmp_path, results="junit.xml")


# --- #121: an empty or malformed report is "no results yet", never a crash ----------------------


def test_empty_cucumber_report_does_not_crash(tmp_path: Path) -> None:
    (tmp_path / "a.feature").write_text(
        "Feature: f\n  @done\n  Scenario: s\n    Given x\n", encoding="utf-8"
    )
    (tmp_path / "cucumber.json").write_text("", encoding="utf-8")
    adapter = GherkinAdapter(
        root=tmp_path,
        paths=["*.feature"],
        delivered_tags=["@done"],
        pending_tags=[],
        results="cucumber.json",
    )
    res = adapter.resolve("a.feature#s")
    assert res.state is ProofState.DELIVERED and res.declared
    assert "cucumber.json is empty" in res.detail


@pytest.mark.parametrize("text", ["", "<testsuites><testsuite>"])
def test_empty_or_broken_junit_report_does_not_crash(tmp_path: Path, text: str) -> None:
    (tmp_path / "test_x.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    (tmp_path / "junit.xml").write_text(text, encoding="utf-8")
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("test_x.py::test_y")
    assert res.state is ProofState.DELIVERED and res.declared
    assert "not valid junit XML" in res.detail


def test_empty_json_results_do_not_crash(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_text("", encoding="utf-8")
    outcome = OutcomeAdapter(root=tmp_path, results="r.json").resolve("k")
    gate = EvalGateAdapter(root=tmp_path, results="r.json").resolve("acc>=0.9")
    field = FieldAdapter(root=tmp_path, schema="r.json").resolve("f")
    for res in (outcome, gate, field):
        assert res.state is ProofState.PENDING
        assert "r.json is empty" in res.detail


# --- #122: junit results are keyed by module + name; parametrised cases are AND-ed --------------


def test_same_named_tests_in_two_files_do_not_share_a_result(tmp_path: Path) -> None:
    adapter = _two_files(tmp_path)
    _junit(
        tmp_path,
        _case("tests.test_orders", "test_rejects_invalid_input", "failed"),
        _case("tests.test_invoices", "test_rejects_invalid_input", "passed"),
    )
    orders = adapter.resolve("tests/test_orders.py::test_rejects_invalid_input")
    invoices = adapter.resolve("tests/test_invoices.py::test_rejects_invalid_input")
    assert orders.state is ProofState.PENDING and orders.detail == "junit: failing"
    assert invoices.state is ProofState.DELIVERED and not invoices.declared


def test_parametrised_cases_must_all_pass(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    adapter = PytestAdapter(root=tmp_path, results="junit.xml")
    _junit(tmp_path, _case("test_x", "test_y[a]"), _case("test_x", "test_y[b]", "failed"))
    assert adapter.resolve("test_x.py::test_y").state is ProofState.PENDING
    assert adapter.resolve("test_x.py::test_y[a]").state is ProofState.DELIVERED
    assert adapter.resolve("test_x.py::test_y[b]").state is ProofState.PENDING


def test_parametrised_cases_that_all_pass_deliver(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    _junit(tmp_path, _case("test_x", "test_y[a]"), _case("test_x", "test_y[b]"))
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("test_x.py::test_y")
    assert res.state is ProofState.DELIVERED and res.detail == "junit: passed"


def test_class_based_test_matches_its_class(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "class TestA:\n    def test_y(self):\n        pass\n", encoding="utf-8"
    )
    _junit(tmp_path, _case("test_x.TestA", "test_y"))
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("test_x.py::TestA::test_y")
    assert res.state is ProofState.DELIVERED and not res.declared


def test_classname_relative_to_another_rootdir_still_matches(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "pkg" / "tests" / "test_x.py").write_text(
        "def test_y():\n    pass\n", encoding="utf-8"
    )
    _junit(tmp_path, _case("tests.test_x", "test_y"))  # pytest ran from pkg/
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("pkg/tests/test_x.py::test_y")
    assert res.state is ProofState.DELIVERED


# --- #123: a test absent from a present report did not run ------------------------------------


def test_test_absent_from_a_present_report_is_pending(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "def test_y():\n    pass\n\ndef test_z():\n    pass\n", encoding="utf-8"
    )
    _junit(tmp_path, _case("test_x", "test_z"))
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("test_x.py::test_y")
    assert res.state is ProofState.PENDING and not res.declared
    assert res.detail == "junit: configured but test not in report"


def test_no_report_written_still_falls_back_to_existence(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    res = PytestAdapter(root=tmp_path, results="junit.xml").resolve("test_x.py::test_y")
    assert res.state is ProofState.DELIVERED and res.declared
    assert res.detail == "test exists"


# --- #124: every path-reading adapter honours ``root`` -----------------------------------------


@pytest.mark.parametrize(
    ("kind", "extra", "locator"),
    [
        ("evalgate", 'results = "r.json"', "acc>=0.9"),
        ("external", 'results = "r.json"', "acc"),
        ("field", 'schema = "r.json"', "acc"),
    ],
)
def test_root_is_honoured_by_json_adapters(
    tmp_path: Path, kind: str, extra: str, locator: str
) -> None:
    (tmp_path / "sib").mkdir()
    (tmp_path / "sib" / "r.json").write_text(
        '{"acc": 0.95, "surfaced": ["acc"]}' if kind == "field" else '{"acc": 0.95}',
        encoding="utf-8",
    )
    if kind == "external":
        (tmp_path / "sib" / "r.json").write_text('{"acc": true}', encoding="utf-8")
    (tmp_path / "board").mkdir()
    toml = tmp_path / "board" / "prodc.toml"
    toml.write_text(
        f'[prodc]\nfiles = ["n/*.yaml"]\n[proofs.p]\nkind = "{kind}"\nroot = "../sib"\n{extra}\n',
        encoding="utf-8",
    )
    res = Config.load(toml).adapters["p"].resolve(locator)
    assert res.state is ProofState.DELIVERED, res.detail


def test_root_is_honoured_by_coverage(tmp_path: Path) -> None:
    (tmp_path / "sib").mkdir()
    (tmp_path / "sib" / "cats.txt").write_text("a/b\n", encoding="utf-8")
    (tmp_path / "board").mkdir()
    toml = tmp_path / "board" / "prodc.toml"
    toml.write_text(
        '[prodc]\nfiles = ["n/*.yaml"]\n'
        '[proofs.c]\nkind = "coverage"\nroot = "../sib"\ncatalog = "cats.txt"\n',
        encoding="utf-8",
    )
    assert Config.load(toml).adapters["c"].resolve("a/b").state is ProofState.DELIVERED


# --- #125: a board can carry its own name ------------------------------------------------------


def test_board_name_defaults_to_directory_and_can_be_set(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    toml = tmp_path / "repo" / "prodc.toml"
    toml.write_text('[prodc]\nfiles = ["n/*.yaml"]\n', encoding="utf-8")
    assert Config.load(toml).board_name == "repo"
    toml.write_text('[prodc]\nfiles = ["n/*.yaml"]\nname = "Orders API"\n', encoding="utf-8")
    cfg = Config.load(toml)
    assert cfg.board_name == "Orders API" and not cfg.notices


def test_status_and_portfolio_show_the_set_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    (tmp_path / "repo" / "n").mkdir(parents=True)
    toml = tmp_path / "repo" / "prodc.toml"
    toml.write_text('[prodc]\nfiles = ["n/*.yaml"]\nname = "orders-board"\n', encoding="utf-8")
    (tmp_path / "repo" / "n" / "a.yaml").write_text(
        "who: x\nneeds:\n  - id: N-1\n    text: When x, they can y.\n", encoding="utf-8"
    )
    main(["status", "--config", str(toml)])
    main(["portfolio", str(toml)])
    out = capsys.readouterr().out
    assert "prodc status: orders-board" in out
    assert "orders-board" in out.split("repo", 1)[1]
