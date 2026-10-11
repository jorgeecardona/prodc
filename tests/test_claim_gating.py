"""The claim-gated text lint — what replaced the product/research profile fork. The EARS /
solution-verb lint fires only on a need that has NOT stated its `claim` (the warrant). A need that
articulates its claim has already done the thinking the lint prods toward, so it is silenced — one
board serves a product PM and a research lab head with no mode. Source hygiene always runs."""

from __future__ import annotations

from pathlib import Path

from prodc.config import Config
from prodc.loader import load
from prodc.status import resolve


def _warnings(tmp_path: Path, needs: str) -> list[str]:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    results = resolve(list(load(cfg).needs), cfg.adapters, cfg.source_adapters)
    return [w for r in results for w in r.warnings]


def test_claimless_need_is_linted(tmp_path: Path) -> None:
    # a claim with no outcome phrasing and no `claim` field — EARS flags it
    warnings = _warnings(tmp_path, "needs:\n  - id: Q\n    text: Prove that pi is irrational\n")
    assert any("EARS" in w for w in warnings)


def test_stating_the_claim_silences_the_lint(tmp_path: Path) -> None:
    # the same text, now with the warrant articulated — the lint is silenced, no mode needed
    needs = (
        "needs:\n"
        "  - id: Q\n"
        "    text: Prove that pi is irrational\n"
        "    claim: pi has no rational representation p/q\n"
    )
    warnings = _warnings(tmp_path, needs)
    assert not any("EARS" in w for w in warnings)


def test_claim_silences_solution_verb_too(tmp_path: Path) -> None:
    verb = "needs:\n  - id: Q\n    text: implement the sieve\n"
    assert any("solution in disguise" in w for w in _warnings(tmp_path, verb))
    with_claim = verb + "    claim: primes below N are enumerated correctly\n"
    assert not any("solution in disguise" in w for w in _warnings(tmp_path, with_claim))


def test_product_need_without_claim_still_linted(tmp_path: Path) -> None:
    # the common product case is unchanged: no claim set → the EARS nudge still fires
    needs = "needs:\n  - id: N\n    text: a vague capability with no outcome word\n"
    assert any("EARS" in w for w in _warnings(tmp_path, needs))


def test_source_hygiene_runs_regardless_of_claim(tmp_path: Path) -> None:
    # a primary source with no named person is flagged whether or not a claim is stated
    needs = """
needs:
  - id: Q
    text: a settled claim
    claim: the thing holds
    sources:
      - kind: primary
        date: 2026-10-11
"""
    assert any("primary source without a named person" in w for w in _warnings(tmp_path, needs))
