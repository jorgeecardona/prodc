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
    good = Need(
        id="N-1", text="t", sources=(Source(kind=SourceKind.ARTIFACT, locator="issues:reg.md#A-1"),)
    )
    bad = Need(
        id="N-2",
        text="t",
        sources=(Source(kind=SourceKind.ARTIFACT, locator="issues:reg.md#NOPE"),),
    )
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


def test_rank_orders_by_must_state_then_evidence_then_importance() -> None:
    from prodc.status import rank

    interview = Source(kind=SourceKind.INTERVIEW, who="Ana", quote="q", date="2026-01-01")
    internal = Source(kind=SourceKind.INTERNAL, date="2026-01-01")
    needs = [
        Need(id="D-1", text="delivered", proofs=("x:1",)),  # lowest priority
        Need(id="MH-1", text="must hole", must=True),  # must-HOLE: top
        Need(id="H-interview", text="hole w interview", sources=(interview,)),
        Need(id="H-internal", text="hole w internal", sources=(internal,)),
        Need(id="H-imp", text="hole w internal high imp", sources=(internal,), importance=3),
    ]
    ranked = rank(resolve(needs, {"x": _delivered()}))
    order = [r.need.id for r in ranked]
    assert order[0] == "MH-1"  # must-HOLE first
    assert order.index("H-interview") < order.index("H-internal")  # interview outranks internal
    # within internal-backed HOLEs, higher importance comes first
    assert order.index("H-imp") < order.index("H-internal")
    assert order[-1] == "D-1"  # delivered last


def test_delivered_without_attestation_warns_warrant_unreviewed() -> None:
    from prodc.model import Attestation

    unattested = Need(id="U-1", text="delivered, link unreviewed", proofs=("x:1",))
    attested = Need(
        id="A-1",
        text="delivered, link reviewed",
        proofs=("x:1",),
        attestation=Attestation(who="Jorge", date="2026-02-01"),
    )
    results = {r.need.id: r for r in resolve([unattested, attested], {"x": _delivered()})}
    assert any("warrant not reviewed" in w for w in results["U-1"].warnings)
    assert not any("warrant not reviewed" in w for w in results["A-1"].warnings)


def test_hole_does_not_warn_about_attestation() -> None:
    # a HOLE has no green proof to over-trust, so there is nothing to attest
    (r,) = resolve([Need(id="H-1", text="no proof")], {})
    assert not any("warrant not reviewed" in w for w in r.warnings)


def test_ears_shape_classification() -> None:
    from prodc.model import EarsShape, ears_shape

    assert ears_shape("When an invoice is paid, the owner can see it settled") is EarsShape.EVENT
    assert ears_shape("While offline, a user can still draft") is EarsShape.STATE
    assert ears_shape("Where multi-currency is on, finance can pick a rate") is EarsShape.OPTIONAL
    assert ears_shape("If a payment fails, then the user can retry") is EarsShape.UNWANTED
    assert ears_shape("The owner can export a statement") is EarsShape.UBIQUITOUS
    assert ears_shape("multi-location per customer") is EarsShape.UNCLASSIFIED


def test_ears_warns_on_trigger_without_outcome() -> None:
    bad = Need(id="E-1", text="When an invoice is paid")  # trigger, no outcome
    (r,) = resolve([bad], {})
    assert any("without an observable outcome" in w for w in r.warnings)


def test_ears_does_not_double_flag_solution_verb() -> None:
    # a solution-in-disguise gets that warning, not also the generic EARS 'no outcome' one
    (r,) = resolve([Need(id="S-1", text="implement a dashboard")], {})
    assert any("solution in disguise" in w for w in r.warnings)
    assert not any("no observable outcome" in w for w in r.warnings)


def test_goal_report_rolls_up_and_flags_ungoaled() -> None:
    from prodc.model import Goal
    from prodc.status import goal_report

    goals = [Goal(id="G-1", text="reduce churn")]
    needs = [
        Need(id="N-1", text="delivered toward G-1", proofs=("x:1",), goal="G-1"),
        Need(id="N-2", text="hole toward G-1", goal="G-1"),
        Need(id="N-3", text="serves no goal"),
    ]
    results = resolve(needs, {"x": _delivered()})
    coverage, ungoaled = goal_report(results, goals)
    (goal, gsum) = coverage[0]
    assert goal.id == "G-1" and gsum.total == 2 and gsum.delivered == 1
    assert [r.need.id for r in ungoaled] == ["N-3"]


def test_release_report_in_ship_order() -> None:
    from prodc.model import Release
    from prodc.status import release_report

    releases = [Release(id="R-1", text="skeleton"), Release(id="R-2", text="delight")]
    needs = [
        Need(id="N-1", text="done in R-1", proofs=("x:1",), release="R-1"),
        Need(id="N-2", text="hole in R-2", release="R-2"),
    ]
    results = resolve(needs, {"x": _delivered()})
    rep = release_report(results, releases)
    assert [rel.id for rel, _ in rep] == ["R-1", "R-2"]  # preserves declared order
    assert rep[0][1].delivered == 1 and rep[1][1].delivered == 0


def test_argument_defects_flags_unsupported_and_dangling() -> None:
    from prodc.model import ArgKind, ArgNode
    from prodc.status import argument_defects

    nodes = [
        ArgNode(id="C-1", kind=ArgKind.CLAIM, text="unsupported claim"),  # no support, no about
        ArgNode(id="C-2", kind=ArgKind.CLAIM, text="ok", about="web:x#y"),  # discharged by evidence
        ArgNode(id="A-1", kind=ArgKind.ASSUMPTION, text="never attached"),  # dangling
    ]
    defects = argument_defects(nodes)
    assert any("unsupported claim 'C-1'" in d for d in defects)
    assert any("dangling assumption 'A-1'" in d for d in defects)
    assert not any("'C-2'" in d for d in defects)  # C-2 cites evidence, not a defect


def test_coverage_counts_leaves_not_flow_parents() -> None:
    # a flow (parent with children) must not be double-counted in coverage (#43)
    from prodc.status import summarize

    needs = [
        Need(id="F-1", text="roast day flow", children=("L-1", "L-2")),
        Need(id="L-1", text="step one", proofs=("x:1",)),
        Need(id="L-2", text="step two", proofs=("x:1",)),
    ]
    results = resolve(needs, {"x": _delivered()})
    s = summarize(results)
    assert s.total == 2 and s.delivered == 2  # the 2 leaves only, not 3 (flow excluded)
    assert s.coverage == 1.0


def test_rank_recurrence_lifts_shared_baseline() -> None:
    from prodc.status import rank

    # two baselines, same state (HOLE) and no evidence; B-1 is shared by 2 clients
    needs = [
        Need(id="B-1", text="shared need"),
        Need(id="B-2", text="single-client need"),
        Need(id="B-1@x", text="shared", client="x", variant_of="B-1"),
        Need(id="B-1@y", text="shared", client="y", variant_of="B-1"),
    ]
    results = resolve(needs, {})
    counts = {"B-1": 2}  # B-1 shared by 2 clients
    order = [r.need.id for r in rank(results, counts)]
    assert order.index("B-1") < order.index("B-2")  # recurrence lifts the shared baseline
    # without the counts, they order by id (tie) — B-1 before B-2 anyway, so check the boost
    # is real by flipping: give B-2 the recurrence instead
    order2 = [r.need.id for r in rank(results, {"B-2": 5})]
    assert order2.index("B-2") < order2.index("B-1")


def test_shared_proof_warning() -> None:
    from prodc.status import shared_proof_warnings

    # one scenario stands in for two needs; a third has its own proof
    needs = [
        Need(id="N-1", text="a", proofs=("web:f#S",)),
        Need(id="N-2", text="b", proofs=("web:f#S",)),  # every proof shared with N-1
        Need(id="N-3", text="c", proofs=("web:f#S", "web:f#T")),  # f#T is its own
    ]
    results = resolve(needs, {"web": _delivered()})
    flagged = shared_proof_warnings(results)
    assert "N-1" in flagged and "N-2" in flagged
    assert "N-3" not in flagged  # has an independently-claimed proof


def test_non_product_need_excluded_from_coverage() -> None:
    from prodc.status import summarize

    needs = [
        Need(id="P-1", text="a user can log in", proofs=("x:1",)),  # product, delivered
        Need(id="I-1", text="resize the database", product=False),  # infra, no proof
    ]
    results = resolve(needs, {"x": _delivered()})
    s = summarize(results)
    assert s.total == 1 and s.delivered == 1 and s.coverage == 1.0  # I-1 not counted
    assert s.hole == 0  # the non-product need is not a HOLE in the denominator


def test_flow_orphan_warning() -> None:
    from prodc.status import flow_orphan_warnings

    needs = [
        Need(id="F-1", text="a flow", children=("L-1",)),
        Need(id="L-1", text="in the flow"),
        Need(id="L-2", text="in no flow"),
    ]
    assert flow_orphan_warnings(needs) == {"L-2"}  # L-1 is in F-1; L-2 belongs to no flow


def test_flow_orphan_silent_without_flows() -> None:
    from prodc.status import flow_orphan_warnings

    needs = [Need(id="A", text="a"), Need(id="B", text="b")]
    assert flow_orphan_warnings(needs) == set()  # no flows → no seam to miss


def test_ai_attestation_is_middle_rung_warning() -> None:
    from prodc.model import Attestation, AttestationKind

    ai = Need(
        id="N-1",
        text="t",
        proofs=("x:1",),
        attestation=Attestation(who="opus", date="2026-10-05", kind=AttestationKind.AI),
    )
    human = Need(
        id="N-2", text="t", proofs=("x:1",), attestation=Attestation(who="Jorge", date="2026-10-05")
    )
    by_id = {r.need.id: r for r in resolve([ai, human], {"x": _delivered()})}
    assert any("(AI) — not a human" in w for w in by_id["N-1"].warnings)
    assert not any("#13" in w for w in by_id["N-2"].warnings)  # human review: no warning


def test_flow_seam_proof_gates_delivered() -> None:
    # all children delivered but the seam proof pending → flow is PENDING, not DELIVERED (#44)
    from prodc.adapters import Adapter

    flow = Need(id="F-1", text="roast day", children=("L-1", "L-2"), seam=("web:seam#E2E",))
    children = [
        Need(id="L-1", text="a", proofs=("x:1",)),
        Need(id="L-2", text="b", proofs=("x:1",)),
    ]
    adapters: dict[str, Adapter] = {
        "x": _delivered(),
        "web": StubAdapter(ProofResult(ProofState.PENDING, False, "not green")),
    }
    by_id = {r.need.id: r for r in resolve([flow, *children], adapters)}
    assert by_id["F-1"].state is NeedState.PENDING  # seam not green holds the flow back


def test_flow_seam_green_delivers() -> None:
    flow = Need(id="F-1", text="roast day", children=("L-1",), seam=("web:seam#E2E",))
    child = Need(id="L-1", text="a", proofs=("x:1",))
    by_id = {r.need.id: r for r in resolve([flow, child], {"x": _delivered(), "web": _delivered()})}
    assert by_id["F-1"].state is NeedState.DELIVERED


def test_flow_seam_broken_breaks_flow() -> None:
    flow = Need(id="F-1", text="roast day", children=("L-1",), seam=("nope:x",))
    child = Need(id="L-1", text="a", proofs=("x:1",))
    by_id = {r.need.id: r for r in resolve([flow, child], {"x": _delivered()})}
    assert by_id["F-1"].state is NeedState.BROKEN  # no 'nope' adapter → seam BROKEN
