"""A need declares the proof kind it awaits; a HOLE says so, suggest looks there, lint checks (#78)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.loader import LoaderError
from prodc.model import ProofKind

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
[proofs.evals]
kind = "evalgate"
results = "evals.json"
"""

_FEATURE = """
Feature: orders
  Scenario: Export orders to CSV
    Given orders
    Then a CSV downloads
"""

_NEEDS = """
needs:
  - id: E-1
    text: the export is fast on a large board
    expects: eval
  - id: T-1
    text: user can export their orders to CSV
    expects: test
  - id: P-1
    text: nothing planned yet
  - id: M-1
    text: wired to a test but expects an eval
    expects: eval
    proofs: ["web:orders.feature#Export orders to CSV"]
"""


def _project(tmp_path: Path) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "features").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    (tmp_path / "evals.json").write_text(json.dumps({"export_ms": 41}), encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def test_awaiting_text_has_the_right_article() -> None:
    assert ProofKind.EVAL.awaiting == "awaiting an eval"
    assert ProofKind.TEST.awaiting == "awaiting a test"
    assert ProofKind.OBSERVED.awaiting == "awaiting an observed"


def test_a_hole_says_what_it_awaits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    assert main(["status", "--config", cfg, "--json"]) == 0
    needs = {n["id"]: n for n in json.loads(capsys.readouterr().out)["needs"]}
    assert needs["E-1"]["expects"] == "eval" and needs["E-1"]["detail"] == ["awaiting an eval"]
    assert needs["P-1"]["expects"] is None and needs["P-1"]["detail"] == []
    assert main(["show", "E-1", "--config", cfg]) == 0
    assert "(none, HOLE, awaiting an eval)" in capsys.readouterr().out


def test_suggest_looks_only_in_the_expected_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["suggest", "--config", cfg, "--json"]) == 0
    by_need: dict[str, set[str]] = {}
    for s in json.loads(capsys.readouterr().out):
        by_need.setdefault(s["need"], set()).add(s["locator"].partition(":")[0])
    assert by_need["E-1"] == {"evals"}  # offered although the text shares no words
    assert by_need["T-1"] == {"web"}  # the eval inventory is not searched for a test


def test_lint_warns_when_proofs_do_not_match_the_expectation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    main(["lint", "--config", cfg])
    out = capsys.readouterr().out
    assert "M-1: expects an eval proof, but its proofs resolve through: web (#78)" in out
    assert "E-1: expects" not in out  # a HOLE with no proofs is not a mismatch


def test_an_unknown_kind_is_a_loader_error(tmp_path: Path) -> None:
    from prodc.config import Config
    from prodc.loader import load

    cfg = _project(tmp_path)
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: X-1\n    text: x\n    expects: magic\n", encoding="utf-8"
    )
    with pytest.raises(LoaderError, match="unknown proof kind 'magic'"):
        load(Config.load(Path(cfg)))
