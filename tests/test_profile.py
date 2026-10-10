"""The `[prodc].profile` switch (research-board step 3): a product board lints need text for
EARS shape and solution-verbs; a research board's needs are posed questions/claims, not outcomes,
so that grammar is skipped. Source-hygiene warnings are about evidence, not phrasing — they run
in both profiles. The switch changes no state or coverage, only which warnings apply."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.config import Config, ConfigError
from prodc.loader import load
from prodc.model import Profile
from prodc.status import resolve


def _warnings(tmp_path: Path, profile: str | None, needs: str) -> list[str]:
    toml = '[prodc]\nneeds = ["needs/*.yaml"]\n'
    if profile is not None:
        toml += f'profile = "{profile}"\n'
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    results = resolve(list(load(cfg).needs), cfg.adapters, cfg.source_adapters, cfg.profile)
    return [w for r in results for w in r.warnings]


# a claim with no user-facing outcome — EARS flags it as UNCLASSIFIED under the product profile
_CLAIM = """
needs:
  - id: Q
    text: Prove that pi is irrational
"""


def test_default_profile_is_product(tmp_path: Path) -> None:
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    assert Config.load(tmp_path / "prodc.toml").profile is Profile.PRODUCT


def test_product_profile_lints_claim_text(tmp_path: Path) -> None:
    warnings = _warnings(tmp_path, "product", _CLAIM)
    assert any("EARS" in w for w in warnings)  # the outcome grammar fires on a claim


def test_research_profile_silences_outcome_grammar(tmp_path: Path) -> None:
    warnings = _warnings(tmp_path, "research", _CLAIM)
    assert not any("EARS" in w for w in warnings)
    assert not any("solution in disguise" in w for w in warnings)


def test_research_profile_silences_solution_verb(tmp_path: Path) -> None:
    needs = "needs:\n  - id: Q\n    text: implement the sieve of Eratosthenes\n"
    assert any("solution in disguise" in w for w in _warnings(tmp_path, "product", needs))
    assert not any("solution in disguise" in w for w in _warnings(tmp_path, "research", needs))


def test_source_hygiene_runs_in_both_profiles(tmp_path: Path) -> None:
    # a primary source with no named person is flagged regardless of profile (it is about evidence)
    needs = """
needs:
  - id: Q
    text: a claim settled by a paper
    sources:
      - kind: primary
        date: 2026-10-10
"""
    for profile in ("product", "research"):
        warnings = _warnings(tmp_path, profile, needs)
        assert any("primary source without a named person" in w for w in warnings)


def test_unknown_profile_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\nprofile = "chaos"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown profile 'chaos'"):
        Config.load(tmp_path / "prodc.toml")
