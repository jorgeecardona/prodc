"""Delivery confidence: a derived label beside DELIVERED (#97). Rules are model-checked in
``tests/test_models.py``; these tests pin what the CLI and report print."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli.render import render_show
from prodc.cli.serialize import show_json
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Confidence, NeedResult, NeedState
from prodc.report import render_markdown
from prodc.status import goal_report, resolve, summarize
from prodc.writer import record_outcome

_TOML = '[prodc]\nfiles = ["needs/*.yaml"]\n\n[proofs.accept]\nkind = "accept"\n'

_NEEDS = """\
who: roaster
needs:
  - id: R-1
    text: arm a live roast from the preparation page
    sources:
      - kind: primary
        who: Ana
        quote: "I want to start the roast in one click"
    proofs: ["accept:jorge@2026-10-24"]
"""


def _cfg(tmp_path: Path) -> Config:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def _r1(cfg: Config) -> NeedResult:
    model = load(cfg)
    return resolve(list(model.needs), cfg.adapters, cfg.source_adapters)[0]


def test_declared_proof_is_weak_and_says_why(tmp_path: Path) -> None:
    r = _r1(_cfg(tmp_path))  # an `accept` proof is declared: there is no results file
    assert r.confidence is Confidence.WEAK
    assert (
        "  confidence: weak (proof is declared (tag or existence), not a results file)"
        in render_show(r)
    )


def test_json_and_report_carry_confidence(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = json.loads(show_json(_r1(cfg)))
    assert payload["confidence"] == "weak"
    assert payload["confidence_detail"] == [
        "proof is declared (tag or existence), not a results file"
    ]
    assert "| R-1 | DELIVERED (weak) |" in render_markdown(cfg, load(cfg))


_GOALED = """\
goals:
  - id: G-1
    text: more roasts started
    metric: roasts started per week
who: roaster
needs:
  - id: R-1
    text: arm a live roast from the preparation page
    goal: G-1
    sources:
      - kind: primary
        who: Ana
        quote: "I want to start the roast in one click"
    proofs: ["accept:jorge@2026-10-24"]
    # keep this comment
"""


def _goaled(tmp_path: Path) -> Config:
    cfg = _cfg(tmp_path)
    (tmp_path / "needs" / "a.yaml").write_text(_GOALED, encoding="utf-8")
    return cfg


def test_outcome_not_landed_stays_delivered_but_leaves_its_goal(tmp_path: Path) -> None:
    cfg = _goaled(tmp_path)
    record_outcome(
        cfg,
        "R-1",
        landed=False,
        who="jorge",
        date="2026-10-24",
        evidence="starts stayed flat for 4 weeks",
        expect_sha=None,
        dry_run=False,
    )
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "    # keep this comment\n" in text
    model = load(cfg)
    results = resolve(list(model.needs), cfg.adapters, cfg.source_adapters)
    r = results[0]
    assert r.state is NeedState.DELIVERED  # the proofs are still green
    assert r.confidence is Confidence.WEAK
    assert r.confidence_detail == ["outcome did not land"]
    assert any("outcome did not land" in w for w in r.warnings)
    assert summarize(results).delivered == 1  # board coverage unchanged
    [(_, goal)] = goal_report(results, list(model.goals))[0]
    assert goal.delivered == 0  # the goal does not count it
    assert "  outcome: did not land (jorge, 2026-10-24): starts stayed flat for 4 weeks" in (
        render_show(r)
    )


def test_outcome_landed_changes_nothing(tmp_path: Path) -> None:
    cfg = _goaled(tmp_path)
    record_outcome(
        cfg,
        "R-1",
        landed=True,
        who="j",
        date="2026-10-24",
        evidence=None,
        expect_sha=None,
        dry_run=False,
    )
    model = load(cfg)
    results = resolve(list(model.needs), cfg.adapters, cfg.source_adapters)
    assert results[0].confidence_detail != ["outcome did not land"]
    assert goal_report(results, list(model.goals))[0][0][1].delivered == 1


def test_outcome_without_goal_warns(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    record_outcome(
        cfg,
        "R-1",
        landed=True,
        who="j",
        date="2026-10-24",
        evidence=None,
        expect_sha=None,
        dry_run=False,
    )
    r = _r1(cfg)
    assert any("serves no goal" in w for w in r.warnings)


def test_outcome_refused_on_research_question(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: Q-1\n    text: t\n    answer: no\n"
        "    outcome: {landed: false, who: j, date: 2026-10-24}\n",
        encoding="utf-8",
    )
    with pytest.raises(LoaderError, match="research question"):
        load(cfg)
