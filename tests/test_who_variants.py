"""who-variant lint (#61): flag `who` strings that likely name the same person per client."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.dedup import who_variants
from prodc.model import Need


def _n(nid: str, who: str, client: str | None = None) -> Need:
    return Need(id=nid, text="a need", who=who, client=client)


def test_case_variants_cluster() -> None:
    needs = [_n("N-1", "John", "acme"), _n("N-2", "john", "acme"), _n("N-3", "JOHN", "acme")]
    vs = who_variants(needs, threshold=0.9)
    assert len(vs) == 1
    assert set(vs[0].whos) == {"John", "john", "JOHN"}
    assert set(vs[0].need_ids) == {"N-1", "N-2", "N-3"}


def test_distinct_people_not_flagged() -> None:
    needs = [_n("N-1", "John", "acme"), _n("N-2", "Mary", "acme")]
    assert who_variants(needs, threshold=0.9) == []


def test_scoped_per_client() -> None:
    # same name at two different clients is not a variant — they are different people
    needs = [_n("N-1", "John", "acme"), _n("N-2", "john", "globex")]
    assert who_variants(needs, threshold=0.9) == []


def test_whitespace_normalisation() -> None:
    needs = [_n("N-1", "john smith", "acme"), _n("N-2", "John  Smith", "acme")]
    vs = who_variants(needs, threshold=0.95)
    assert len(vs) == 1 and set(vs[0].whos) == {"john smith", "John  Smith"}


def test_none_who_ignored() -> None:
    needs = [_n("N-1", "john", "acme"), Need(id="N-2", text="x", client="acme")]
    assert who_variants(needs, threshold=0.9) == []


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[lint]
duplicate_threshold = 0.9
"""

_NEEDS = """
needs:
  - id: N-1
    text: a need
    who: John
    client: acme
  - id: N-2
    text: another need
    who: john
    client: acme
"""


def test_lint_surfaces_who_variant(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    code = main(["lint", "--config", str(tmp_path / "prodc.toml")])
    out = capsys.readouterr().out
    assert code == 0  # soft warning, not a hard error
    assert "who may name the same person" in out and "#61" in out
