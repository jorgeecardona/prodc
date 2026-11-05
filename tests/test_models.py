"""Model-check prodc's need lifecycle and flow roll-up with musil (#63).

These are not ordinary unit tests: they exhaustively explore every reachable evidence
state of a need and assert prodc's own invariants hold in all of them. Crucially, no state
rule is re-implemented here — each invariant derives the NeedState by calling prodc's real
``Resolver.resolve``. A drift between this model and the resolver is a failed check, not a
silent lie. ``docs/lifecycle.md`` maps the transitions below to their Torres grounding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check, explore, reaches

from prodc.adapters import Adapter, ProofResult
from prodc.model import (
    Attestation,
    AttestationKind,
    Child,
    Confidence,
    Decision,
    Goal,
    Need,
    NeedState,
    Outcome,
    ProofState,
    Source,
    SourceKind,
    Stage,
    Verdict,
    Withdrawal,
    board_needs,
)
from prodc.status import Resolver, active_decisions, goal_report, summarize


class _Stub:
    """Resolve 'stub:<state>' to that ProofState — lets a model state name proof verdicts."""

    def resolve(self, payload: str) -> ProofResult:
        return ProofResult(ProofState(payload), declared=False, detail="stub")


class _DeclaredStub:
    """Resolve 'decl:<state>' like ``_Stub``, but as a declared proof (tag/existence, #97)."""

    def resolve(self, payload: str) -> ProofResult:
        return ProofResult(ProofState(payload), declared=True, detail="declared stub")


_ADAPTERS: dict[str, Adapter] = {"stub": _Stub(), "decl": _DeclaredStub()}


# --- leaf-need lifecycle -------------------------------------------------------------
MAX_PROOFS = 2  # cap the state space; 2 proofs already exercise every combination rule


@dataclass(frozen=True)
class Leaf:
    sourced: bool = False  # opinion -> sourced: at least one Source recorded
    proofs: tuple[str, ...] = ()  # each proof's current ProofState value
    attested: bool = False  # human sign-off recorded on the need


def leaf_state(s: Leaf) -> NeedState:
    """The NeedState prodc's real resolver gives this evidence — no reimplementation."""
    n = Need(id="n", text="x", proofs=tuple(f"stub:{p}" for p in s.proofs))
    return Resolver([n], _ADAPTERS).resolve("n").state


def _flip(s: Leaf, i: int, to: str) -> Leaf:
    return replace(s, proofs=(*s.proofs[:i], to, *s.proofs[i + 1 :]))


def _leaf_actions() -> list[Action[Leaf]]:
    out: list[Action[Leaf]] = [
        Action("source", lambda s: not s.sourced, lambda s: replace(s, sourced=True)),
        Action(
            "declare-proof",
            lambda s: len(s.proofs) < MAX_PROOFS,
            lambda s: replace(s, proofs=(*s.proofs, "pending")),
        ),
        Action(
            "attest",
            lambda s: not s.attested and leaf_state(s) is NeedState.DELIVERED,
            lambda s: replace(s, attested=True),
        ),
    ]
    for i in range(MAX_PROOFS):
        out += [
            Action(
                f"proof-passes@{i}",
                lambda s, i=i: i < len(s.proofs) and s.proofs[i] == "pending",
                lambda s, i=i: _flip(s, i, "delivered"),
            ),
            Action(
                f"proof-breaks@{i}",
                lambda s, i=i: i < len(s.proofs) and s.proofs[i] != "broken",
                lambda s, i=i: _flip(s, i, "broken"),
            ),
            Action(
                f"proof-unresolved@{i}",
                lambda s, i=i: i < len(s.proofs) and s.proofs[i] == "pending",
                lambda s, i=i: _flip(s, i, "unresolved"),
            ),
            Action(
                f"proof-relink@{i}",
                lambda s, i=i: i < len(s.proofs) and s.proofs[i] == "broken",
                lambda s, i=i: _flip(s, i, "pending"),
            ),
        ]
    return out


def _leaf_no_green_without_proof(s: Leaf) -> bool:
    """DELIVERED only when it has proofs and every proof is DELIVERED."""
    if leaf_state(s) is not NeedState.DELIVERED:
        return True
    return len(s.proofs) >= 1 and all(p == "delivered" for p in s.proofs)


def _leaf_hole_iff_no_proof(s: Leaf) -> bool:
    """HOLE is exactly 'no proof at all' — an honest gap, never caused by a failing proof."""
    return (leaf_state(s) is NeedState.HOLE) == (len(s.proofs) == 0)


def _leaf_broken_surfaces(s: Leaf) -> bool:
    """A broken locator dominates: it is never hidden under pending/delivered."""
    if any(p == "broken" for p in s.proofs):
        return leaf_state(s) is NeedState.BROKEN
    return True


LEAF_MODEL = Model(
    init=Leaf(),
    actions=_leaf_actions(),
    invariants={
        "no-green-without-proof": _leaf_no_green_without_proof,
        "hole-iff-no-proof": _leaf_hole_iff_no_proof,
        "broken-surfaces": _leaf_broken_surfaces,
    },
)


# --- flow roll-up --------------------------------------------------------------------
N_CHILDREN = 2
N_SEAM = 1
CHILD_STATES = ("hole", "pending", "delivered", "broken", "unresolved")
SEAM_STATES = ("none", "pending", "delivered", "broken", "unresolved")


@dataclass(frozen=True)
class Flow:
    children: tuple[str, ...]  # each child's NeedState value
    seam: tuple[str, ...]  # each seam proof's ProofState value, or "none" = absent


def _child_need(cid: str, state: str) -> Need:
    proofs = () if state == "hole" else (f"stub:{state}",)
    return Need(id=cid, text="c", proofs=proofs)


def flow_state(f: Flow) -> NeedState:
    """The NeedState prodc's real aggregate gives this set of children + seam."""
    children = [_child_need(f"c{i}", s) for i, s in enumerate(f.children)]
    seam = tuple(f"stub:{s}" for s in f.seam if s != "none")
    flow = Need(id="flow", text="f", children=tuple(Child(c.id) for c in children), seam=seam)
    return Resolver([flow, *children], _ADAPTERS).resolve("flow").state


def _set(seq: tuple[str, ...], i: int, to: str) -> tuple[str, ...]:
    return (*seq[:i], to, *seq[i + 1 :])


def _flow_actions() -> list[Action[Flow]]:
    out: list[Action[Flow]] = []
    for i in range(N_CHILDREN):
        for st in CHILD_STATES:
            out.append(
                Action(
                    f"child{i}={st}",
                    lambda s, i=i, st=st: s.children[i] != st,
                    lambda s, i=i, st=st: replace(s, children=_set(s.children, i, st)),
                )
            )
    for i in range(N_SEAM):
        for st in SEAM_STATES:
            out.append(
                Action(
                    f"seam{i}={st}",
                    lambda s, i=i, st=st: s.seam[i] != st,
                    lambda s, i=i, st=st: replace(s, seam=_set(s.seam, i, st)),
                )
            )
    return out


def _flow_broken_propagates(s: Flow) -> bool:
    """Any BROKEN child or seam -> the flow is BROKEN. A break is never hidden upward."""
    if any(c == "broken" for c in s.children) or any(x == "broken" for x in s.seam):
        return flow_state(s) is NeedState.BROKEN
    return True


def _flow_delivered_iff_all_green(s: Flow) -> bool:
    """A flow is DELIVERED exactly when it has children, all DELIVERED, and the seam is green."""
    all_green = (
        len(s.children) > 0
        and all(c == "delivered" for c in s.children)
        and all(
            x == "delivered" for x in s.seam if x != "none"
        )  # "none" = no seam, vacuously green
    )
    return (flow_state(s) is NeedState.DELIVERED) == all_green


def _flow_unresolved_below_broken(s: Flow) -> bool:
    """With nothing BROKEN, any UNRESOLVED child/seam -> the flow is UNRESOLVED (can't judge)."""
    if any(c == "broken" for c in s.children) or any(x == "broken" for x in s.seam):
        return True
    if any(c == "unresolved" for c in s.children) or any(x == "unresolved" for x in s.seam):
        return flow_state(s) is NeedState.UNRESOLVED
    return True


FLOW_MODEL = Model(
    init=Flow(children=("hole",) * N_CHILDREN, seam=("none",) * N_SEAM),
    actions=_flow_actions(),
    invariants={
        "broken-propagates": _flow_broken_propagates,
        "delivered-iff-all-green": _flow_delivered_iff_all_green,
        "unresolved-below-broken": _flow_unresolved_below_broken,
    },
)


# --- draft / withdrawn lifecycle (shared by Need and Decision) -----------------------
# The board-membership state machine the writer verbs move an item through: a thing is staged
# (draft), promoted (draft cleared), withdrawn (a decision against — off the board, record kept),
# or reinstated. Every invariant derives from prodc's REAL rules (counts_toward_coverage /
# board_needs / active_decisions), so a drift between this model and those rules is a failed check.
# Note the asymmetry it pins down: coverage/board exclude a *withdrawn* item unconditionally, but a
# *draft* only until promoted — and active_decisions excludes both.


@dataclass(frozen=True)
class Life:
    draft: bool = True  # starts staged (proposed); promote clears it
    withdrawn: bool = False


def _life_actions() -> list[Action[Life]]:
    return [
        Action("promote", lambda s: s.draft and not s.withdrawn, lambda s: replace(s, draft=False)),
        Action("withdraw", lambda s: not s.withdrawn, lambda s: replace(s, withdrawn=True)),
        Action("reinstate", lambda s: s.withdrawn, lambda s: replace(s, withdrawn=False)),
    ]


def _w(s: Life) -> Withdrawal | None:
    return Withdrawal(reason="r", date="2026-01-01") if s.withdrawn else None


def _life_need(s: Life) -> Need:
    stage = Stage.CAPTURED if s.draft else Stage.COMMITTED
    return Need(id="n", text="x", stage=stage, withdrawn=_w(s))


def _life_decision(s: Life) -> Decision:
    return Decision(id="D", text="x", needs=("n",), draft=s.draft, withdrawn=_w(s))


def _on_board(s: Life) -> bool:
    return not s.draft and not s.withdrawn


def _life_coverage_counts_iff_not_withdrawn(s: Life) -> bool:
    """A leaf product need counts toward coverage exactly when not withdrawn — draft is orthogonal."""
    return _life_need(s).counts_toward_coverage == (not s.withdrawn)


def _life_board_default_excludes_draft_and_withdrawn(s: Life) -> bool:
    """The counted board (no --include-drafts) holds the item iff it is neither draft nor withdrawn."""
    on = _life_need(s).id in {n.id for n in board_needs([_life_need(s)], include_drafts=False)}
    return on == _on_board(s)


def _life_board_with_drafts_excludes_only_withdrawn(s: Life) -> bool:
    """--include-drafts holds the item iff it is not withdrawn (a draft is kept, withdrawn never)."""
    on = _life_need(s).id in {n.id for n in board_needs([_life_need(s)], include_drafts=True)}
    return on == (not s.withdrawn)


def _life_decision_active_iff_on_board(s: Life) -> bool:
    """A decision is in force iff neither a draft nor withdrawn — stricter than need coverage."""
    return (active_decisions([_life_decision(s)]) == [_life_decision(s)]) == _on_board(s)


LIFE_MODEL = Model(
    init=Life(),
    actions=_life_actions(),
    invariants={
        "coverage-counts-iff-not-withdrawn": _life_coverage_counts_iff_not_withdrawn,
        "board-default-excludes-draft-and-withdrawn": _life_board_default_excludes_draft_and_withdrawn,
        "board-with-drafts-excludes-only-withdrawn": _life_board_with_drafts_excludes_only_withdrawn,
        "decision-active-iff-on-board": _life_decision_active_iff_on_board,
    },
)


# --- delivery confidence (#97) -------------------------------------------------------
# Every recorded fact that can feed confidence, as an axis an author can move. Each invariant
# asks prodc's real resolver for the confidence and checks a property of it, never the rule
# table itself.
SOURCE_AXIS = ("none", "assumption", "secondary", "primary")
PROOF_AXIS = ("none", "stub:pending", "stub:delivered", "decl:delivered", "stub:broken")
ATTEST_AXIS = ("none", "human:pass", "human:concerns", "human:fail", "ai:pass", "ai:fail")
OUTCOME_AXIS = ("none", "landed", "not-landed")


@dataclass(frozen=True)
class Conf:
    source: str = "none"
    proof: str = "none"
    attest: str = "none"
    outcome: str = "none"


def _conf_need(s: Conf, nid: str = "n") -> Need:
    sources = () if s.source == "none" else (Source(SourceKind(s.source), who="a", quote="q"),)
    proofs = () if s.proof == "none" else (s.proof,)
    att = None
    if s.attest != "none":
        kind, verdict = s.attest.split(":")
        att = Attestation("a", "2026-10-24", AttestationKind(kind), Verdict(verdict))
    outcome = (
        None
        if s.outcome == "none"
        else Outcome(landed=s.outcome == "landed", date="2026-10-24", who="a")
    )
    return Need(
        id=nid,
        text="x",
        goal="G",
        sources=sources,
        proofs=proofs,
        attestation=att,
        outcome=outcome,
    )


def conf_result(s: Conf) -> tuple[NeedState, Confidence | None]:
    """State and confidence from prodc's real resolver: no reimplementation."""
    r = Resolver([_conf_need(s)], _ADAPTERS).resolve("n")
    return r.state, r.confidence


def _conf_actions() -> list[Action[Conf]]:
    out: list[Action[Conf]] = []
    for field_name, axis in (
        ("source", SOURCE_AXIS),
        ("proof", PROOF_AXIS),
        ("attest", ATTEST_AXIS),
        ("outcome", OUTCOME_AXIS),
    ):
        for v in axis:
            out.append(
                Action(
                    f"{field_name}={v}",
                    lambda s, f=field_name, v=v: getattr(s, f) != v,
                    lambda s, f=field_name, v=v: replace(s, **{f: v}),
                )
            )
    return out


def _conf_iff_delivered(s: Conf) -> bool:
    """A need has a confidence exactly when it is DELIVERED. A gap is never 'weak'."""
    state, conf = conf_result(s)
    return (conf is not None) == (state is NeedState.DELIVERED)


def _conf_strong_needs_all_three(s: Conf) -> bool:
    """Strong only with a human pass, a primary source, and a results-backed proof."""
    if conf_result(s)[1] is not Confidence.STRONG:
        return True
    return s.attest == "human:pass" and s.source == "primary" and s.proof == "stub:delivered"


def _conf_fact_against_is_weak(s: Conf) -> bool:
    """A fail verdict, a declared proof, or an opinion caps a DELIVERED need at weak."""
    state, conf = conf_result(s)
    if state is not NeedState.DELIVERED:
        return True
    against = (
        s.outcome == "not-landed"
        or s.attest.endswith(":fail")
        or s.proof.startswith("decl:")
        or s.source
        in (
            "none",
            "assumption",
        )
    )
    return (conf is Confidence.WEAK) == against


def _conf_unattested_is_not_weak(s: Conf) -> bool:
    """A missing review is not a fact against the delivery: #13 warns on it, confidence does not."""
    if s.attest != "none" or s.outcome == "not-landed":
        return True
    state, conf = conf_result(s)
    if state is not NeedState.DELIVERED or s.proof.startswith("decl:"):
        return True
    if s.source in ("none", "assumption"):
        return True
    return conf is Confidence.MEDIUM


def _conf_outcome_never_hides_proofs(s: Conf) -> bool:
    """Recording an outcome never changes the proof state: the board cannot lie either way."""
    return conf_result(s)[0] is conf_result(replace(s, outcome="none"))[0]


def _conf_goal_never_above_coverage(s: Conf) -> bool:
    """The goal counts a need as delivered iff coverage does and its outcome did not miss."""
    r = Resolver([_conf_need(s)], _ADAPTERS).resolve("n")
    board = summarize([r])
    [(_, goal)] = goal_report([r], [Goal(id="G", text="g")])[0]
    expected = 0 if s.outcome == "not-landed" else board.delivered
    return goal.delivered == expected and goal.total == board.total


CONF_MODEL = Model(
    init=Conf(),
    actions=_conf_actions(),
    invariants={
        "confidence-iff-delivered": _conf_iff_delivered,
        "strong-needs-all-three": _conf_strong_needs_all_three,
        "fact-against-is-weak": _conf_fact_against_is_weak,
        "unattested-is-not-weak": _conf_unattested_is_not_weak,
        "outcome-never-hides-proofs": _conf_outcome_never_hides_proofs,
        "goal-never-above-coverage": _conf_goal_never_above_coverage,
    },
)


# A flow of two steps. Each step is one of a few leaf presets, one per confidence and one gap, so
# the product stays small; the leaf model above already covers every leaf configuration.
STEP_PRESETS = (
    Conf(),  # HOLE: no confidence
    Conf("assumption", "stub:delivered"),  # weak
    Conf("secondary", "stub:delivered"),  # medium
    Conf("primary", "stub:delivered", "human:pass"),  # strong
)


@dataclass(frozen=True)
class ConfFlow:
    steps: tuple[Conf, Conf] = (STEP_PRESETS[0], STEP_PRESETS[0])


def _set_step(i: int, c: Conf) -> Action[ConfFlow]:
    def enabled(s: ConfFlow) -> bool:
        return s.steps[i] != c

    def apply(s: ConfFlow) -> ConfFlow:
        return replace(s, steps=(c, s.steps[1]) if i == 0 else (s.steps[0], c))

    return Action(f"step{i}={c}", enabled, apply)


def _conf_flow_actions() -> list[Action[ConfFlow]]:
    return [_set_step(i, c) for i in range(2) for c in STEP_PRESETS]


def _conf_flow_is_lowest_step(s: ConfFlow) -> bool:
    """A DELIVERED flow is never more confident than its weakest step."""
    kids = [_conf_need(c, f"c{i}") for i, c in enumerate(s.steps)]
    flow = Need(id="f", text="f", children=tuple(Child(k.id) for k in kids))
    res = Resolver([flow, *kids], _ADAPTERS)
    fr = res.resolve("f")
    if fr.state is not NeedState.DELIVERED:
        return fr.confidence is None
    order = list(Confidence)
    kid_confs = [res.resolve(k.id).confidence for k in kids]
    return fr.confidence is not None and all(
        k is not None and order.index(fr.confidence) <= order.index(k) for k in kid_confs
    )


CONF_FLOW_MODEL = Model(
    init=ConfFlow(),
    actions=_conf_flow_actions(),
    invariants={"flow-is-lowest-step": _conf_flow_is_lowest_step},
)


# --- the gate ------------------------------------------------------------------------
def test_leaf_lifecycle_safety() -> None:
    r = check(LEAF_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_flow_rollup_safety() -> None:
    r = check(FLOW_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_lifecycle_safety() -> None:
    r = check(LIFE_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_lifecycle_board_always_recoverable() -> None:
    """No reachable state is permanently stuck off the board: reinstate + promote always lead back.

    The liveness counterpart to the safety invariants — it proves a withdrawn or staged item can
    never get trapped off the active board (an item is never a one-way trip).
    """
    g = explore(LIFE_MODEL)
    assert reaches(g, _on_board) == set(g.states)


def test_checker_bites() -> None:
    """Guard against a vacuous suite: a knowingly false invariant must be caught."""
    bad = Model(
        init=Leaf(),
        actions=_leaf_actions(),
        invariants={"never-delivered": lambda s: leaf_state(s) is not NeedState.DELIVERED},
    )
    assert not check(bad).ok


def test_confidence_safety() -> None:
    r = check(CONF_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_confidence_flow_safety() -> None:
    r = check(CONF_FLOW_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_confidence_strong_is_reachable() -> None:
    """Strong is not dead code: some sequence of recorded facts reaches it."""
    g = explore(CONF_MODEL)
    assert any(conf_result(st)[1] is Confidence.STRONG for st in g.states)
