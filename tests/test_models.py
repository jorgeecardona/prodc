"""Model-check prodc's need lifecycle and flow roll-up with musil (#63).

These are not ordinary unit tests: they exhaustively explore every reachable evidence
state of a need and assert prodc's own invariants hold in all of them. Crucially, no state
rule is re-implemented here — each invariant derives the NeedState by calling prodc's real
``Resolver.resolve``. A drift between this model and the resolver is a failed check, not a
silent lie. ``docs/lifecycle.md`` maps the transitions below to their Torres grounding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check

from prodc.adapters import Adapter, ProofResult
from prodc.model import Need, NeedState, ProofState
from prodc.status import Resolver


class _Stub:
    """Resolve 'stub:<state>' to that ProofState — lets a model state name proof verdicts."""

    def resolve(self, payload: str) -> ProofResult:
        return ProofResult(ProofState(payload), declared=False, detail="stub")


_ADAPTERS: dict[str, Adapter] = {"stub": _Stub()}


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
    flow = Need(id="flow", text="f", children=tuple(c.id for c in children), seam=seam)
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


# --- the gate ------------------------------------------------------------------------
def test_leaf_lifecycle_safety() -> None:
    r = check(LEAF_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_flow_rollup_safety() -> None:
    r = check(FLOW_MODEL)
    assert r.ok, f"{r.invariant}: {r.trace}"


def test_checker_bites() -> None:
    """Guard against a vacuous suite: a knowingly false invariant must be caught."""
    bad = Model(
        init=Leaf(),
        actions=_leaf_actions(),
        invariants={"never-delivered": lambda s: leaf_state(s) is not NeedState.DELIVERED},
    )
    assert not check(bad).ok
