"""`suggest` reads outcome and evalgate inventories, and does not cut them by text score (#75, #76)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.adapters import EvalGateAdapter, OutcomeAdapter
from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.web]
kind = "external"
results = "outcomes.json"
[proofs.evals]
kind = "evalgate"
results = "evals.json"
"""

_NEEDS = """
needs:
  - id: H-1
    text: a user exports their orders to CSV
"""


def _project(tmp_path: Path) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "outcomes.json").write_text(
        json.dumps({"GET /csv returns 200": True, "p95 under load": {"passed": False}}),
        encoding="utf-8",
    )
    (tmp_path / "evals.json").write_text(
        json.dumps({"accuracy": {"score": 0.82}, "rollup_ms": 41}), encoding="utf-8"
    )
    return str(tmp_path / "prodc.toml")


def test_outcome_inventory_lists_the_recorded_keys(tmp_path: Path) -> None:
    _project(tmp_path)
    assert OutcomeAdapter(tmp_path, "outcomes.json").inventory() == [
        "GET /csv returns 200",
        "p95 under load",
    ]
    assert OutcomeAdapter(tmp_path, "missing.json").inventory() == []


def test_evalgate_inventory_is_one_resolvable_gate_per_metric(tmp_path: Path) -> None:
    _project(tmp_path)
    ad = EvalGateAdapter(tmp_path, "evals.json")
    assert ad.inventory() == ["accuracy>=0.82", "rollup_ms>=41"]
    assert all(ad.resolve(p).state.value == "delivered" for p in ad.inventory())


def test_suggest_by_kind_offers_every_eval_key_even_with_no_word_overlap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["suggest", "--config", cfg, "--kind", "evals", "--json"]) == 0
    got = {s["locator"] for s in json.loads(capsys.readouterr().out)}
    assert got == {"evals:accuracy>=0.82", "evals:rollup_ms>=41"}


def test_suggest_without_kind_still_cuts_by_text_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["suggest", "--config", cfg, "--json"]) == 0
    got = {s["locator"] for s in json.loads(capsys.readouterr().out)}
    assert "evals:accuracy>=0.82" not in got
