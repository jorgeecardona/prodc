"""Source kinds: the primary > secondary > assumption ladder, opinion as derived, and aliases."""

from __future__ import annotations

from pathlib import Path

from prodc.config import Config
from prodc.loader import load
from prodc.model import Need, Source, SourceKind


def _n(nid: str, *kinds: SourceKind) -> Need:
    srcs = tuple(Source(kind=k, who="x", date="2026-01-01", quote="q", locator="l") for k in kinds)
    return Need(id=nid, text="t", sources=srcs)


def test_opinion_is_no_external_evidence() -> None:
    # no source at all -> opinion
    assert _n("A").is_opinion
    # only an assumption -> still an opinion (an assumption is not external evidence)
    assert _n("B", SourceKind.ASSUMPTION).is_opinion
    assert _n("B", SourceKind.ASSUMPTION).only_assumption
    # a primary or secondary source -> not an opinion
    assert not _n("C", SourceKind.PRIMARY).is_opinion
    assert not _n("D", SourceKind.SECONDARY).is_opinion
    assert not _n("E", SourceKind.ASSUMPTION, SourceKind.PRIMARY).is_opinion


def test_strongest_kind_orders_primary_secondary_assumption() -> None:
    n = _n("A", SourceKind.ASSUMPTION, SourceKind.SECONDARY, SourceKind.PRIMARY)
    assert n.strongest_kind is SourceKind.PRIMARY
    assert (
        _n("B", SourceKind.ASSUMPTION, SourceKind.SECONDARY).strongest_kind is SourceKind.SECONDARY
    )


def _project(tmp_path: Path, needs: str) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def test_loader_aliases_old_kind_names(tmp_path: Path) -> None:
    # old vocabulary still loads, mapped onto the new ladder
    needs = """
needs:
  - id: N-1
    text: from a client call
    sources: [{kind: interview, who: Jordan, date: 2026-01-01, quote: "I need this"}]
  - id: N-2
    text: from a ticket
    sources: [{kind: artifact, locator: issues.md#5, date: 2026-01-01}]
  - id: N-3
    text: our guess
    sources: [{kind: proxy, date: 2026-01-01}]
  - id: N-4
    text: a teammate said so
    sources: [{kind: internal, date: 2026-01-01}]
"""
    by_id = {n.id: n for n in load(_project(tmp_path, needs)).needs}
    assert by_id["N-1"].sources[0].kind is SourceKind.PRIMARY
    assert by_id["N-2"].sources[0].kind is SourceKind.SECONDARY
    assert by_id["N-3"].sources[0].kind is SourceKind.ASSUMPTION
    assert by_id["N-4"].sources[0].kind is SourceKind.ASSUMPTION


def test_capture_normalises_alias_to_canonical(tmp_path: Path) -> None:
    from prodc.writer import capture_source

    cfg = _project(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    # author types the old name; it is stored as the canonical ladder value
    capture_source(
        cfg,
        "N-1",
        kind="interview",
        who="Jordan",
        date="2026-01-01",
        quote="I need it",
        locator=None,
        dry_run=False,
        expect_sha=None,
    )
    n = next(n for n in load(cfg).needs if n.id == "N-1")
    assert n.sources[0].kind is SourceKind.PRIMARY and not n.is_opinion
