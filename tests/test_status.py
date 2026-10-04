"""Status resolver: proofs and children → NeedState, the engine behind the board."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from prodc.adapters import FrontmatterAdapter, ProofResult, SourceAdapter
from prodc.model import Need, NeedState, ProofState, Source, SourceKind
from prodc.status import resolve


@dataclass(frozen=True)
class StubAdapter:
    """Resolves any payload to a fixed ProofResult — a test double for an adapter."""

    result: ProofResult

    def resolve(self, payload: str) -> ProofResult:
        return self.result


def _delivered() -> StubAdapter:
    return StubAdapter(ProofResult(ProofState.DELIVERED, declared=True, detail="tagged delivered"))


def test_need_without_proofs_is_hole() -> None:
    need = Need(id="A-1", text="a need", proofs=())
    (r,) = resolve([need], {})
    assert r.state is NeedState.HOLE
    assert r.total == 0


def test_delivered_via_tag_is_declared() -> None:
    need = Need(id="A-1", text="a need", proofs=("web:x#y",))
    (r,) = resolve([need], {"web": _delivered()})
    assert r.state is NeedState.DELIVERED
    assert r.declared is True
    assert r.delivered == 1 and r.total == 1


def test_unresolvable_locator_is_broken() -> None:
    # No adapter named "web" is registered → the locator points at nothing.
    need = Need(id="A-1", text="a need", proofs=("web:x#y",))
    (r,) = resolve([need], {})
    assert r.state is NeedState.BROKEN


def test_flow_aggregates_two_of_three() -> None:
    children = (
        Need(id="C-1", text="one", proofs=("web:1",)),
        Need(id="C-2", text="two", proofs=("web:2",)),
        Need(id="C-3", text="three", proofs=()),  # a HOLE
    )
    flow = Need(id="F-1", text="a flow", children=("C-1", "C-2", "C-3"))
    results = {r.need.id: r for r in resolve([flow, *children], {"web": _delivered()})}
    flow_result = results["F-1"]
    assert flow_result.state is NeedState.PENDING  # not all delivered → pending
    assert flow_result.delivered == 2 and flow_result.total == 3


def test_solution_verb_warns() -> None:
    need = Need(id="A-1", text="implement a dashboard", proofs=())
    (r,) = resolve([need], {})
    assert any("solution in disguise" in w for w in r.warnings)


def test_unresolved_proof_is_excluded_from_coverage() -> None:
    from prodc.status import summarize

    delivered = StubAdapter(ProofResult(ProofState.DELIVERED, declared=True, detail="ok"))
    unresolved = StubAdapter(ProofResult(ProofState.UNRESOLVED, declared=False, detail="absent"))
    need_ok = Need(id="D", text="t", proofs=("web:x",))
    need_un = Need(id="U", text="t", proofs=("ext:x",))
    results = resolve([need_ok, need_un], {"web": delivered, "ext": unresolved})
    by_id = {r.need.id: r for r in results}
    assert by_id["U"].state is NeedState.UNRESOLVED
    s = summarize(results)
    assert s.unresolved == 1 and s.delivered == 1
    assert s.coverage == 1.0  # 1 delivered / (2 total - 1 unresolved); the absent one is excluded


def test_dangling_source_warns_distinct_from_opinion(tmp_path: Path) -> None:
    (tmp_path / "issues").mkdir()
    (tmp_path / "issues" / "reg.md").write_text("# A-1 ok\n", encoding="utf-8")
    sources: dict[str, SourceAdapter] = {
        "issues": FrontmatterAdapter(root=tmp_path, paths=["issues/*.md"])
    }
    good = Need(id="N-1", text="t",
                sources=(Source(kind=SourceKind.ARTIFACT, locator="issues:reg.md#A-1"),))
    bad = Need(id="N-2", text="t",
               sources=(Source(kind=SourceKind.ARTIFACT, locator="issues:reg.md#NOPE"),))
    results = {r.need.id: r for r in resolve([good, bad], {}, sources)}
    assert not any("BROKEN source" in w for w in results["N-1"].warnings)
    assert any("BROKEN source" in w for w in results["N-2"].warnings)
    # both are sourced, so neither is an opinion — BROKEN-source is a distinct signal
    assert not results["N-2"].need.is_opinion


def test_recurrence_counts_clients_sharing_a_baseline() -> None:
    from prodc.status import recurrence

    base = Need(id="N-1", text="multi-location per customer")
    v_acme = Need(id="N-1@acme", text="multi-location", client="acme", variant_of="N-1")
    v_globex = Need(id="N-1@globex", text="multi-location", client="globex", variant_of="N-1")
    lonely = Need(id="N-2", text="own voice")  # baseline with no variants — not recurring
    recs = recurrence([base, v_acme, v_globex, lonely])
    assert len(recs) == 1  # only N-1 is shared
    (rec,) = recs
    assert rec.baseline.id == "N-1"
    assert rec.count == 2 and rec.clients == ("acme", "globex")


def test_recurrence_sorted_most_shared_first() -> None:
    from prodc.status import recurrence

    needs = [
        Need(id="A", text="a"),
        Need(id="B", text="b"),
        Need(id="A@x", text="a", client="x", variant_of="A"),
        Need(id="B@x", text="b", client="x", variant_of="B"),
        Need(id="B@y", text="b", client="y", variant_of="B"),
    ]
    recs = recurrence(needs)
    assert [r.baseline.id for r in recs] == ["B", "A"]  # B shared by 2, A by 1
