"""Proof discovery (#54): rank candidate proofs for HOLE needs from adapter inventories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]
"""

_FEATURE = """
Feature: orders
  Scenario: Export orders to CSV
    Given orders
    Then a CSV downloads

  Scenario: Schedule the weekly roast
    Given a roastery
    Then it is scheduled
"""

_NEEDS = """
needs:
  - id: H-1
    text: user can export their orders to CSV
  - id: D-1
    text: a delivered need
    proofs: ["web:orders.feature#Export orders to CSV"]
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_suggest_ranks_matching_scenario_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    code = main(["suggest", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    # only the HOLE need H-1 gets suggestions; D-1 already has a proof
    assert {s["need"] for s in payload} == {"H-1"}
    top = payload[0]
    assert top["locator"] == "web:orders.feature#Export orders to CSV"
    assert top["locator"].endswith("Export orders to CSV") and top["score"] > 0.3


def test_suggest_respects_min_score(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["suggest", "--config", str(_project(tmp_path)), "--min-score", "0.99", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == []  # nothing is a 0.99 match


def test_suggest_single_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    code = main(["suggest", "H-1", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0 and "H-1:" in out and "web:orders.feature#Export orders to CSV" in out


def test_suggest_unknown_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    code = main(["suggest", "NOPE", "--config", str(_project(tmp_path))])
    assert code == 2 and "no need 'NOPE'" in capsys.readouterr().err


def test_coverage_adapter_inventory(tmp_path: Path) -> None:
    from prodc.adapters import CoverageAdapter, Inventoried

    (tmp_path / "cats.txt").write_text("alpha\nbeta\n# a comment\n", encoding="utf-8")
    ad = CoverageAdapter(root=tmp_path, catalog="cats.txt")
    assert isinstance(ad, Inventoried)
    assert ad.inventory() == ["alpha", "beta"]
