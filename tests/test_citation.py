"""The `citation` proof adapter (research-board step 5): a cited published result as a declared
DELIVERED. Distinct from `accept` on purpose — `accept` records who signed off, a citation records
what external result settles the question (the `ref` a reader follows to check it)."""

from __future__ import annotations

from pathlib import Path

from prodc.adapters import CitationAdapter
from prodc.config import Config
from prodc.model import ProofState


def test_citation_is_declared_delivered() -> None:
    r = CitationAdapter().resolve("Smith2019@Smith@2019")
    assert r.state is ProofState.DELIVERED
    assert r.declared is True  # the `*` marker — declared, not checked by prodc
    assert r.detail == "cites Smith2019 by Smith (2019)"


def test_citation_ref_only() -> None:
    r = CitationAdapter().resolve("arXiv:2401.00001")
    assert r.state is ProofState.DELIVERED
    assert r.detail == "cites arXiv:2401.00001"  # author/year optional


def test_citation_never_broken_even_when_empty() -> None:
    # it is an assertion, like a tag — it never fails to resolve
    assert CitationAdapter().resolve("").state is ProofState.DELIVERED


def test_config_builds_citation_adapter(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n\n[proofs.paper]\nkind = "citation"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    assert isinstance(cfg.adapters["paper"], CitationAdapter)
