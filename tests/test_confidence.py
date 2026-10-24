"""Delivery confidence: a derived label beside DELIVERED (#97). Rules are model-checked in
``tests/test_models.py``; these tests pin what the CLI and report print."""

from __future__ import annotations

import json
from pathlib import Path

from prodc.cli.render import render_show
from prodc.cli.serialize import show_json
from prodc.config import Config
from prodc.loader import load
from prodc.model import Confidence, NeedResult
from prodc.report import render_markdown
from prodc.status import resolve

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
