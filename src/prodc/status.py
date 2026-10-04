"""Resolve needs into states: the engine behind ``prodc status``.

A leaf's state comes from its proofs; a flow (need with children) aggregates its
sub-needs. ``HOLE`` (no proof) is deliberately not a failure — it is an honest gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import Adapter, Enumerable, ProofResult, SourceAdapter
from .model import (
    SOLUTION_VERBS,
    Need,
    NeedResult,
    NeedState,
    ProofState,
    SourceKind,
    ears_warnings,
)


def _text_warnings(need: Need) -> list[str]:
    first = need.text.strip().split(" ", 1)[0].lower().rstrip(":")
    out: list[str] = []
    if first in SOLUTION_VERBS:
        out.append(f"text may be a solution in disguise (starts with '{first}')")
    else:
        out.extend(ears_warnings(need.text))  # EARS shape check (redundant on solution verbs)
    for src in need.sources:
        out.extend(src.warnings())
    return out


def _resolve_proof(locator: str, adapters: dict[str, Adapter]) -> ProofResult:
    name, sep, payload = locator.partition(":")
    adapter = adapters.get(name)
    if not sep or adapter is None:
        return ProofResult(ProofState.BROKEN, False, f"no adapter '{name}' for '{locator}'")
    return adapter.resolve(payload)


def _source_warnings(need: Need, source_adapters: dict[str, SourceAdapter]) -> list[str]:
    """Flag a Source.locator that names a configured source adapter but does not resolve.

    This is a dangling (BROKEN) *source* — distinct from OPINION (no source at all). A
    free-text locator with no matching adapter is left unchecked, not flagged.
    """
    out: list[str] = []
    for s in need.sources:
        if not s.locator:
            continue
        name, sep, payload = s.locator.partition(":")
        adapter = source_adapters.get(name)
        if not sep or adapter is None:
            continue
        res = adapter.resolve(payload)
        if not res.ok:
            out.append(f"BROKEN source '{s.locator}' ({res.detail})")
    return out


def _warrant_warnings(need: Need, result: NeedResult) -> list[str]:
    """Flag a leaf that is green on its proofs but whose link no human has attested (#13).

    prodc reads that the proof passes, not that it establishes *this* need. A DELIVERED
    leaf with no :class:`~prodc.model.Attestation` is trusted blindly — surface that so a
    reviewer can confirm the link, without the tool pretending to prove semantic fit.
    """
    if need.children or not need.proofs:
        return []
    if result.state is NeedState.DELIVERED and need.attestation is None:
        return ["DELIVERED on an unattested proof link — warrant not human-reviewed (#13)"]
    return []


class Resolver:
    def __init__(
        self,
        needs: list[Need],
        adapters: dict[str, Adapter],
        source_adapters: dict[str, SourceAdapter] | None = None,
    ) -> None:
        self._by_id = {n.id: n for n in needs}
        self._adapters = adapters
        self._source_adapters = source_adapters or {}
        self._cache: dict[str, NeedResult] = {}
        self._visiting: set[str] = set()

    def resolve_all(self) -> list[NeedResult]:
        return [self.resolve(n.id) for n in self._by_id.values()]

    def resolve(self, need_id: str) -> NeedResult:
        if need_id in self._cache:
            return self._cache[need_id]
        need = self._by_id[need_id]
        if need_id in self._visiting:  # cycle — stop and report
            return NeedResult(need, NeedState.BROKEN, detail=["cycle in children"])
        self._visiting.add(need_id)
        result = self._compute(need)
        self._visiting.discard(need_id)
        result.warnings = (
            _text_warnings(need)
            + _source_warnings(need, self._source_adapters)
            + _warrant_warnings(need, result)
            + result.warnings
        )
        self._cache[need_id] = result
        return result

    def _compute(self, need: Need) -> NeedResult:
        if need.children:
            return self._aggregate_children(need)
        return self._resolve_leaf(need)

    def _resolve_leaf(self, need: Need) -> NeedResult:
        if not need.proofs:
            return NeedResult(need, NeedState.HOLE)
        results = [_resolve_proof(p, self._adapters) for p in need.proofs]
        detail = [f"{p} → {r.state.value}{'*' if r.declared else ''} ({r.detail})"
                  for p, r in zip(need.proofs, results, strict=True)]
        delivered = sum(1 for r in results if r.state is ProofState.DELIVERED)
        declared = any(r.declared for r in results if r.state is ProofState.DELIVERED)
        if any(r.state is ProofState.BROKEN for r in results):
            state = NeedState.BROKEN
        elif any(r.state is ProofState.UNRESOLVED for r in results):
            state = NeedState.UNRESOLVED  # a source couldn't be read — can't judge yet
        elif delivered == len(results):
            state = NeedState.DELIVERED
        else:
            state = NeedState.PENDING
        return NeedResult(need, state, delivered, len(results), declared, detail)

    def _aggregate_children(self, need: Need) -> NeedResult:
        warnings: list[str] = []
        child_states: list[NeedState] = []
        declared = False
        for cid in need.children:
            if cid not in self._by_id:
                warnings.append(f"unknown child id '{cid}'")
                continue
            cr = self.resolve(cid)
            child_states.append(cr.state)
            declared = declared or cr.declared
        delivered = sum(1 for s in child_states if s is NeedState.DELIVERED)
        total = len(child_states)
        if any(s is NeedState.BROKEN for s in child_states):
            state = NeedState.BROKEN
        elif any(s is NeedState.UNRESOLVED for s in child_states):
            state = NeedState.UNRESOLVED
        elif total and delivered == total:
            state = NeedState.DELIVERED
        elif not child_states or all(s is NeedState.HOLE for s in child_states):
            state = NeedState.HOLE
        else:
            state = NeedState.PENDING
        detail = [f"{delivered} of {total} sub-needs delivered"]
        return NeedResult(need, state, delivered, total, declared, detail, warnings)


def resolve(
    needs: list[Need],
    adapters: dict[str, Adapter],
    source_adapters: dict[str, SourceAdapter] | None = None,
) -> list[NeedResult]:
    """Resolve every need to a :class:`NeedResult`."""
    return Resolver(needs, adapters, source_adapters).resolve_all()


@dataclass(frozen=True)
class Summary:
    """The gap at a glance: how many needs sit in each state, and how many are opinions."""

    total: int
    delivered: int
    pending: int
    hole: int
    must_hole: int  # a HOLE on a must-have — the top of the board
    broken: int  # a dangling proof locator
    unresolved: int  # a proof whose source could not be read (e.g. sibling repo absent)
    opinion: int  # a need with no source of any kind

    @property
    def coverage(self) -> float:
        """Fraction DELIVERED, of needs that could be read.

        UNRESOLVED needs (a source that couldn't be read) are excluded from the
        denominator — they neither help nor hurt coverage, so a `--min-coverage` gate
        isn't failed by an absent sibling the way a BROKEN locator fails it.
        """
        judged = self.total - self.unresolved
        return self.delivered / judged if judged else 0.0


def summarize(results: list[NeedResult]) -> Summary:
    """Roll a resolved board up into its gap counts."""
    by_state = {s: sum(1 for r in results if r.state is s) for s in NeedState}
    return Summary(
        total=len(results),
        delivered=by_state[NeedState.DELIVERED],
        pending=by_state[NeedState.PENDING],
        hole=by_state[NeedState.HOLE],
        must_hole=sum(1 for r in results if r.need.must and r.state is NeedState.HOLE),
        broken=by_state[NeedState.BROKEN],
        unresolved=by_state[NeedState.UNRESOLVED],
        opinion=sum(1 for r in results if r.need.is_opinion),
    )


@dataclass(frozen=True)
class Recurrence:
    """A baseline need and the clients that carry a variant of it (#32)."""

    baseline: Need
    clients: tuple[str, ...]  # distinct named clients with a variant, sorted
    variants: int  # how many variants reference this baseline

    @property
    def count(self) -> int:
        """How many clients share this baseline — the recurrence signal."""
        return self.variants


def recurrence(needs: list[Need]) -> list[Recurrence]:
    """Baselines shared by at least one variant, most-shared first.

    A variant points at its baseline via ``variant_of``; grouping on that id turns N
    scattered per-client needs back into one baseline with a recurrence count, so the
    board can weigh a request by how broadly it recurs instead of treating each ask as
    unique.
    """
    by_id = {n.id: n for n in needs}
    grouped: dict[str, list[Need]] = {}
    for n in needs:
        if n.variant_of is not None and n.variant_of in by_id:
            grouped.setdefault(n.variant_of, []).append(n)

    out: list[Recurrence] = []
    for base_id, variants in grouped.items():
        clients = tuple(sorted({v.client for v in variants if v.client}))
        out.append(Recurrence(by_id[base_id], clients, len(variants)))
    out.sort(key=lambda r: (-r.count, r.baseline.id))
    return out


_STATE_RANK = {
    NeedState.BROKEN: 1,
    NeedState.PENDING: 2,
    NeedState.UNRESOLVED: 3,
    NeedState.HOLE: 4,
    NeedState.DELIVERED: 5,
}


def _rank_key(r: NeedResult) -> tuple[int, int, int, str]:
    """Pure ordering over recorded inputs only — never a conjured score (#34).

    1. must + state: a must-HOLE sits at the top, then BROKEN, PENDING, …, DELIVERED.
    2. evidence kind: a real `interview` outranks `proxy`/`internal`/opinion at the same
       state, because a user actually asked — this is what reorders the author's guesses.
    3. `importance`: the author's optional ordinal, higher first; absent falls to the back
       of its tier, so it only refines (1)+(2) and never invents priority where none was set.
    """
    state_rank = 0 if (r.need.must and r.state is NeedState.HOLE) else _STATE_RANK[r.state]
    kind = r.need.strongest_kind
    kind_rank = list(SourceKind).index(kind) if kind is not None else len(SourceKind)
    importance_rank = -(r.need.importance or 0)
    return (state_rank, kind_rank, importance_rank, r.need.id)


def rank(results: list[NeedResult]) -> list[NeedResult]:
    """Order a resolved board into a backlog by :func:`_rank_key`."""
    return sorted(results, key=_rank_key)


def applicable_needs(needs: list[Need], client: str) -> list[Need]:
    """The needs in force for one client: its own variants, plus every shared baseline
    it has not specialised.

    A baseline (``variant_of is None`` and ``client is None``) applies to all clients
    unless this client carries a variant of it — in which case the variant overrides the
    baseline and the baseline is dropped. Standalone needs tied to a different client are
    excluded.
    """
    overridden = {n.variant_of for n in needs if n.client == client and n.variant_of}
    out: list[Need] = []
    for n in needs:
        if n.client == client:
            out.append(n)  # this client's own needs/variants
        elif n.client is None and n.variant_of is None and n.id not in overridden:
            out.append(n)  # a shared baseline this client hasn't specialised
    return out


def orphans(needs: list[Need], adapters: dict[str, Adapter]) -> dict[str, list[str]]:
    """Proof units claimed by no need, per enumerable adapter — the reverse of the board.

    The board walks need → proof; this walks proof → need, surfacing scenarios that
    exist in the suite but no need references ("does every feature tie to a need?").
    Only adapters that can enumerate their universe (:class:`~prodc.adapters.Enumerable`,
    e.g. gherkin) participate.
    """
    referenced: dict[str, set[str]] = {}
    for need in needs:
        for locator in need.proofs:
            name, sep, payload = locator.partition(":")
            if sep:
                referenced.setdefault(name, set()).add(payload)

    out: dict[str, list[str]] = {}
    for name, adapter in adapters.items():
        if not isinstance(adapter, Enumerable):
            continue
        claimed: set[str] = set()
        for payload in referenced.get(name, set()):
            claimed.update(adapter.covers(payload))
        unclaimed = sorted(set(adapter.inventory()) - claimed)
        if unclaimed:
            out[name] = unclaimed
    return out
