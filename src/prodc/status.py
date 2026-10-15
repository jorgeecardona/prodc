"""Resolve needs into states: the engine behind ``prodc status``.

A leaf's state comes from its proofs; a flow (need with children) aggregates its
sub-needs. ``HOLE`` (no proof) is deliberately not a failure — it is an honest gap.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from .adapters import Adapter, Enumerable, Inventoried, ProofResult, SourceAdapter
from .dedup import similarity
from .model import (
    SOLUTION_VERBS,
    Answer,
    ArgKind,
    ArgNode,
    AttestationKind,
    Goal,
    Need,
    NeedResult,
    NeedState,
    ProofState,
    Release,
    Role,
    SourceKind,
    ears_warnings,
)

#: Reserved proof-adapter name for a need→need edge (#research-board step 2): a proof whose
#: payload is another need id. Resolved by the :class:`Resolver` itself, not a config adapter,
#: so it never appears in ``[proofs.*]``; a ``[proofs.need]`` block would be shadowed by this.
_NEEDREF = "need"


def _text_warnings(need: Need) -> list[str]:
    out: list[str] = []
    # The outcome-shape lint (EARS + solution-verb) fires only until the author states the
    # warrant. A need with `claim` set has already articulated the proposition the lint was
    # prodding toward — "what delivering this establishes" — so it is silenced. This is what
    # unifies a product board and a research board without a mode: "When a roaster opens the
    # queue, she can see today's orders" and "π is irrational" are the same claim-under-uncertainty
    # at different altitudes; EARS is just one falsifiable-claim grammar, a stated `claim` another.
    if need.claim is None:
        first = need.text.strip().split(" ", 1)[0].lower().rstrip(":")
        if first in SOLUTION_VERBS:
            out.append(f"text may be a solution in disguise (starts with '{first}')")
        else:
            out.extend(ears_warnings(need.text))  # EARS shape check (redundant on solution verbs)
    # Source hygiene is universal (it is about evidence, not phrasing) — always run it.
    for src in need.sources:
        out.extend(src.warnings())
    return out


def _observed_dates(need: Need) -> list[date]:
    """The parseable ISO ``observed_at`` dates across a need's sources (#58)."""
    out: list[date] = []
    for s in need.sources:
        if s.observed_at:
            with contextlib.suppress(ValueError):  # a malformed date is not counted, never a crash
                out.append(date.fromisoformat(s.observed_at))
    return out


def last_observed(need: Need) -> str | None:
    """The most recent ``observed_at`` across a need's sources, or None when unknown (#58)."""
    dates = _observed_dates(need)
    return max(dates).isoformat() if dates else None


def evidence_age_days(need: Need, today: date) -> int | None:
    """Days since the newest ``observed_at``; None when no source carries one (#58)."""
    dates = _observed_dates(need)
    return (today - max(dates)).days if dates else None


def importance_revisit_due(need: Need, today: date, max_age_days: int) -> bool:
    """Whether a need's importance should be revisited — for ``plan --revisit`` (#59).

    Due when the need has an importance set but it is either never dated (no ``importance_set_at``)
    or last set more than ``max_age_days`` ago. A need with no importance is never due — there is
    nothing to revisit. A malformed date is treated as not-due (the lint warning owns that defect).
    """
    if need.importance is None:
        return False
    when = need.importance_set_at
    if when is None:
        return True
    try:
        return (today - date.fromisoformat(when)).days > max_age_days
    except ValueError:
        return False


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
    if need.children or not need.proofs or result.state is not NeedState.DELIVERED:
        return []
    att = need.attestation
    if att is None:
        return ["DELIVERED on an unattested proof link — warrant not reviewed (#13)"]
    if att.kind is AttestationKind.AI:
        # an AI review is a middle rung: better than nothing, weaker than a human sign-off
        return [f"DELIVERED, warrant reviewed by {att.who} (AI) — not a human (#13)"]
    return []


def _answer_warnings(need: Need, result: NeedResult) -> list[str]:
    """Flag an ``answer`` authored on a question that is not settled (research board).

    DELIVERED means settled; ``answer`` records which way it settled. An answer declared while
    the state is anything but DELIVERED is a claim the proofs do not yet support — surface it.
    Conservative by design: the check never cross-examines the proof detail against the
    direction (a ``command:lean/¬P`` counterexample legitimately pairs DELIVERED with ``no``),
    so only settledness is checked here, not which way.
    """
    if need.answer is not None and result.state is not NeedState.DELIVERED:
        return [
            f"answer '{need.answer.value}' declared on an unsettled question "
            f"(state {result.state.value})"
        ]
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
            + _answer_warnings(need, result)
            + result.warnings
        )
        self._cache[need_id] = result
        return result

    def _compute(self, need: Need) -> NeedResult:
        if need.children:
            return self._aggregate_children(need)
        return self._resolve_leaf(need)

    def _resolve_one(self, locator: str) -> ProofResult:
        """Resolve one leaf proof locator, routing ``need:`` to the needref edge.

        Every other adapter reads a repo; a needref reads another need's resolution, which only
        the resolver can do — so it is dispatched here, not via :func:`_resolve_proof`.
        """
        name, sep, payload = locator.partition(":")
        if sep and name == _NEEDREF:
            return self._resolve_needref(payload)
        return _resolve_proof(locator, self._adapters)

    def _resolve_needref(self, payload: str) -> ProofResult:
        """Resolve ``need:<id>`` (or ``need:<id>@<answer>``) against another need (#research step 2).

        A research question can depend on a peer: "B cannot be posed until A is settled." That
        edge is itself a proof — B delivers iff A is settled — so it rides the ``proofs`` tuple
        with no new field, and the resolver's own cycle detection and memoization cover A→B→A for
        free (a back-edge hits the ``_visiting`` guard and returns BROKEN). ``need:A`` resolves on
        A's *settledness* (DELIVERED); the optional ``need:A@yes`` form additionally requires A's
        authored :attr:`~prodc.model.Need.answer` to match. B never inherits A's answer — the
        dependency only requires A settled, optionally in a given direction.
        """
        ref_id, sep, direction = payload.partition("@")
        ref_id = ref_id.strip()
        if ref_id not in self._by_id:
            return ProofResult(ProofState.BROKEN, False, f"need '{ref_id}' is not a known need id")
        want: Answer | None = None
        if sep:
            try:
                want = Answer(direction.strip())
            except ValueError:
                answers = "|".join(a.value for a in Answer)
                return ProofResult(
                    ProofState.BROKEN, False, f"unknown answer '{direction}' ({answers})"
                )
        cr = self.resolve(ref_id)  # cycle-safe via the _visiting guard in resolve()
        if cr.state is NeedState.BROKEN:
            return ProofResult(ProofState.BROKEN, False, f"need '{ref_id}' unresolved (broken)")
        if cr.state is NeedState.UNRESOLVED:
            return ProofResult(ProofState.UNRESOLVED, False, f"need '{ref_id}' could not be read")
        if cr.state is not NeedState.DELIVERED:
            return ProofResult(
                ProofState.PENDING, False, f"need '{ref_id}' not settled ({cr.state.value})"
            )
        if want is None:
            return ProofResult(ProofState.DELIVERED, cr.declared, f"need '{ref_id}' settled")
        answer = self._by_id[ref_id].answer
        if answer is None:
            return ProofResult(
                ProofState.PENDING,
                False,
                f"need '{ref_id}' settled, no answer recorded, awaiting '{want.value}'",
            )
        if answer is want:
            return ProofResult(
                ProofState.DELIVERED, cr.declared, f"need '{ref_id}' settled: {answer.value}"
            )
        return ProofResult(
            ProofState.PENDING,
            False,
            f"need '{ref_id}' settled {answer.value}, awaiting '{want.value}'",
        )

    def _resolve_leaf(self, need: Need) -> NeedResult:
        if not need.proofs:
            return NeedResult(need, NeedState.HOLE)
        results = [self._resolve_one(p) for p in need.proofs]
        detail = [
            f"{p} → {r.state.value}{'*' if r.declared else ''} ({r.detail})"
            for p, r in zip(need.proofs, results, strict=True)
        ]
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
        # The flow's own between-steps (seam) behaviour, if it declares one (#44).
        seam_results = [_resolve_proof(p, self._adapters) for p in need.seam]
        seam_states = [r.state for r in seam_results]
        seam_green = all(s is ProofState.DELIVERED for s in seam_states)  # vacuously true if none
        declared = declared or any(
            r.declared for r in seam_results if r.state is ProofState.DELIVERED
        )
        detail = [f"{delivered} of {total} sub-needs delivered"]
        detail += [
            f"seam {p} → {r.state.value}{'*' if r.declared else ''} ({r.detail})"
            for p, r in zip(need.seam, seam_results, strict=True)
        ]
        if any(s is NeedState.BROKEN for s in child_states) or ProofState.BROKEN in seam_states:
            state = NeedState.BROKEN
        elif any(s is NeedState.UNRESOLVED for s in child_states) or (
            ProofState.UNRESOLVED in seam_states
        ):
            state = NeedState.UNRESOLVED
        elif total and delivered == total and seam_green:
            # a flow is DELIVERED only when every step is AND its seam proof is green
            state = NeedState.DELIVERED
        elif not child_states or (all(s is NeedState.HOLE for s in child_states) and not need.seam):
            state = NeedState.HOLE
        else:
            state = NeedState.PENDING
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
    """Roll a resolved board up into its gap counts, over LEAF needs only.

    A flow (a need with ``children``) is a roll-up view of its leaves, so counting it in the
    denominator too would double-count every flow (#43). Coverage is the leaves; a flow's own
    state is reported separately, never added on top of the children it aggregates.
    """
    leaves = [r for r in results if r.need.counts_toward_coverage]
    by_state = {s: sum(1 for r in leaves if r.state is s) for s in NeedState}
    return Summary(
        total=len(leaves),
        delivered=by_state[NeedState.DELIVERED],
        pending=by_state[NeedState.PENDING],
        hole=by_state[NeedState.HOLE],
        must_hole=sum(1 for r in leaves if r.need.must and r.state is NeedState.HOLE),
        broken=by_state[NeedState.BROKEN],
        unresolved=by_state[NeedState.UNRESOLVED],
        opinion=sum(1 for r in leaves if r.need.is_opinion),
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


@dataclass(frozen=True)
class ProofSuggestion:
    """A candidate proof locator for a HOLE need, ranked by text similarity (#54)."""

    need: Need
    adapter: str  # the adapter name the locator resolves through
    locator: str  # a ready-to-paste proof locator, "<adapter>:<inventory id>"
    score: float


def _matchable(inventory_id: str) -> str:
    """The human-meaningful part of an inventory id (a scenario title, a field name)."""
    return inventory_id.rsplit("#", 1)[-1]


def proof_suggestions(
    results: list[NeedResult],
    adapters: dict[str, Adapter],
    *,
    min_score: float,
    top: int,
    kind: str | None = None,
) -> list[ProofSuggestion]:
    """Rank candidate proofs for every HOLE need against the adapters' inventories (#54).

    For each leaf need with no proof, compare its text with every enumerable adapter's known
    proof units and return the closest matches as ready-to-paste locators. Read-only — it never
    writes; ``--apply`` and BROKEN-relink are left to the caller/follow-up.
    """
    inventories: list[tuple[str, list[str]]] = [
        (name, ad.inventory())
        for name, ad in adapters.items()
        if isinstance(ad, Inventoried) and (kind is None or name == kind)
    ]
    out: list[ProofSuggestion] = []
    for r in results:
        if r.state is not NeedState.HOLE or r.need.children:
            continue
        scored: list[ProofSuggestion] = []
        for name, ids in inventories:
            for inv in ids:
                score = similarity(r.need.text, _matchable(inv))
                if score >= min_score:
                    scored.append(ProofSuggestion(r.need, name, f"{name}:{inv}", score))
        scored.sort(key=lambda s: (-s.score, s.locator))
        out.extend(scored[:top])
    return out


@dataclass(frozen=True)
class RelinkSuggestion:
    """A candidate replacement for a BROKEN proof locator — a renamed test, relinkable (#54)."""

    need: Need
    adapter: str  # the adapter the broken locator (and the replacement) resolve through
    broken: str  # the locator currently on the need that no longer resolves
    locator: str  # the proposed replacement, "<adapter>:<inventory id>"
    score: float


def relink_suggestions(
    results: list[NeedResult],
    adapters: dict[str, Adapter],
    *,
    min_score: float,
    top: int,
    kind: str | None = None,
) -> list[RelinkSuggestion]:
    """Propose the nearest live inventory entry for each BROKEN proof locator (#54 relink).

    A relink is for a locator whose adapter still exists but whose id no longer resolves — a test
    that was renamed. So it only proposes within the *same* adapter (the kind is stable, the id
    drifted), scoring each inventory entry by the similarity of its matchable part to the broken
    id's matchable part, falling back to the need text. A locator whose adapter is absent entirely
    cannot be relinked (there is no inventory to match against) and is skipped. Read-only.
    """
    out: list[RelinkSuggestion] = []
    for r in results:
        if r.state is not NeedState.BROKEN or r.need.children:
            continue
        for proof in r.need.proofs:
            if _resolve_proof(proof, adapters).state is not ProofState.BROKEN:
                continue
            name, _, payload = proof.partition(":")
            if kind is not None and name != kind:
                continue
            ad = adapters.get(name)
            if not isinstance(ad, Inventoried):
                continue  # adapter gone, or can't enumerate — nothing to relink against
            scored: list[RelinkSuggestion] = []
            for inv in ad.inventory():
                candidate = f"{name}:{inv}"
                if candidate in r.need.proofs:
                    continue  # already on the need
                score = max(
                    similarity(_matchable(payload), _matchable(inv)),
                    similarity(r.need.text, _matchable(inv)),
                )
                if score >= min_score:
                    scored.append(RelinkSuggestion(r.need, name, proof, candidate, score))
            scored.sort(key=lambda s: (-s.score, s.locator))
            out.extend(scored[:top])
    return out


_STATE_RANK = {
    NeedState.BROKEN: 1,
    NeedState.PENDING: 2,
    NeedState.UNRESOLVED: 3,
    NeedState.HOLE: 4,
    NeedState.DELIVERED: 5,
}


def state_priority(r: NeedResult) -> int:
    """Attention order for a need: must-HOLE first, then BROKEN … DELIVERED last.

    The single source of truth for both the board sort and the backlog rank.
    """
    if r.need.must and r.state is NeedState.HOLE:
        return 0
    return _STATE_RANK[r.state]


def _rank_key(r: NeedResult, recurrence_counts: dict[str, int]) -> tuple[int, int, int, int, str]:
    """Pure ordering over recorded inputs only — never a conjured score (#34).

    1. must + state: a must-HOLE sits at the top, then BROKEN, PENDING, …, DELIVERED.
    2. evidence kind: a real `interview` outranks `proxy`/`internal`/opinion at the same
       state, because a user actually asked — this is what reorders the author's guesses.
    3. recurrence: how many clients share this baseline (#51). Breadth of demand is a
       first-order, objective signal, so it outranks the author's importance guess.
    4. `importance`: the author's optional ordinal, higher first; absent falls to the back
       of its tier, so it only refines 1-3 and never invents priority where none was set.
    """
    state_rank = state_priority(r)
    kind = r.need.strongest_kind
    kind_rank = list(SourceKind).index(kind) if kind is not None else len(SourceKind)
    recurrence_rank = -recurrence_counts.get(r.need.id, 0)
    importance_rank = -(r.need.importance or 0)
    return (state_rank, kind_rank, recurrence_rank, importance_rank, r.need.id)


def rank(
    results: list[NeedResult], recurrence_counts: dict[str, int] | None = None
) -> list[NeedResult]:
    """Order a resolved board into a backlog by :func:`_rank_key`.

    ``recurrence_counts`` maps a baseline need id to how many clients share it (from
    :func:`recurrence`); a shared baseline then outranks a single-client need with the same
    state and evidence. Omitted, recurrence contributes nothing.
    """
    counts = recurrence_counts or {}
    return sorted(results, key=lambda r: _rank_key(r, counts))


def goal_report(
    results: list[NeedResult], goals: list[Goal]
) -> tuple[list[tuple[Goal, Summary]], list[NeedResult]]:
    """Roll results up per goal, and list the needs that serve no goal.

    Per-goal coverage is just :func:`summarize` over the needs that cite that goal — the
    same summary the whole board uses. The ungoaled list is the flag symmetric to opinion:
    a need with no objective above it.
    """
    by_goal: dict[str, list[NeedResult]] = {g.id: [] for g in goals}
    ungoaled: list[NeedResult] = []
    for r in results:
        if r.need.goal is None:
            ungoaled.append(r)
        elif r.need.goal in by_goal:
            by_goal[r.need.goal].append(r)
    coverage = [(g, summarize(by_goal[g.id])) for g in goals]
    return coverage, ungoaled


def release_report(
    results: list[NeedResult], releases: list[Release]
) -> list[tuple[Release, Summary]]:
    """Coverage per release slice, in declared (ship) order — the story-map release view (#30).

    Like :func:`goal_report`, each slice's coverage is just :func:`summarize` over the needs
    that name it, so "what does this release look like" reads the same as the whole board.
    """
    by_release: dict[str, list[NeedResult]] = {r.id: [] for r in releases}
    for res in results:
        if res.need.release in by_release:
            by_release[res.need.release].append(res)
    return [(rel, summarize(by_release[rel.id])) for rel in releases]


def role_report(
    results: list[NeedResult], roles: list[Role]
) -> tuple[list[tuple[Role, Summary]], list[NeedResult]]:
    """Coverage per declared role, plus the needs whose ``who`` plays no declared role (#52).

    The roster view: like :func:`goal_report`, each role's coverage is :func:`summarize` over the
    needs that name it, so a role reads the same as the whole board. A declared role with a 0/0
    summary is an orphan role — on the roster though no need references it yet (a new packer),
    the symmetric flag to a need that serves no role. Scope to one client by resolving a
    client-filtered need set first (``status --client``), exactly as goals/releases do.
    """
    by_role: dict[str, list[NeedResult]] = {p.id: [] for p in roles}
    unroled: list[NeedResult] = []
    for r in results:
        if r.need.role is not None:
            if r.need.role in by_role:
                by_role[r.need.role].append(r)
        elif r.need.who is not None:
            # a person is named but plays no declared role — the flag symmetric to an
            # ungoaled need. A need with neither who nor role (e.g. a bare flow) is not a
            # person with a missing role, so it is not listed here.
            unroled.append(r)
    coverage = [(p, summarize(by_role[p.id])) for p in roles]
    return coverage, unroled


@dataclass(frozen=True)
class Handoff:
    """A derived step in a cross-role journey: one flow child hands off to the next (#52)."""

    flow: Need
    from_need: Need
    to_need: Need
    from_role: str
    to_role: str


def handoffs(needs: list[Need]) -> list[Handoff]:
    """Derive the cross-role handoffs in every flow from its ordered ``children`` (#52).

    A handoff is a consecutive pair of a flow's children whose ``role`` differs — the point in
    the journey where one person's work passes to the next (Patton's backbone, read as an
    ordered story map). It keys on ``role``, not ``who``: ``role`` is set deliberately on the
    need and is never inherited from a file-level default, so deriving on it does not fire on
    the file-level ``who`` that every need in a file silently shares (the noise #52's follow-up
    flagged). No new edge type — the order already in ``children`` is the sequence.
    """
    by_id = {n.id: n for n in needs}
    out: list[Handoff] = []
    for flow in needs:
        if not flow.children:
            continue
        steps = [by_id[c] for c in flow.children if c in by_id]
        for a, b in pairwise(steps):
            if a.role and b.role and a.role != b.role:
                out.append(Handoff(flow, a, b, a.role, b.role))
    return out


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


_CONTEXT_KINDS = (ArgKind.CONTEXT, ArgKind.ASSUMPTION, ArgKind.JUSTIFICATION)


def argument_defects(argument: list[ArgNode]) -> list[str]:
    """Report an unsupported claim or a dangling context node — like HOLE, not a load failure (#28).

    A CLAIM or STRATEGY discharges nothing if nothing supports it (and, for a claim, it cites
    no evidence via ``about``). A CONTEXT/ASSUMPTION/JUSTIFICATION that no node attaches via
    ``in_context_of`` is stated but never used. These are the checkable defects GSN exists to
    surface; the graph still loads.
    """
    attached: set[str] = set()
    for node in argument:
        attached.update(node.in_context_of)
    out: list[str] = []
    for node in argument:
        if node.kind is ArgKind.CLAIM and not node.supported_by and not node.about:
            out.append(f"unsupported claim {node.id!r}: no supporting node and no evidence")
        elif node.kind is ArgKind.STRATEGY and not node.supported_by:
            out.append(f"unsupported strategy {node.id!r}: no supporting node")
        if node.kind in _CONTEXT_KINDS and node.id not in attached:
            out.append(f"dangling {node.kind.value} {node.id!r}: attached to no claim")
    return out


def flow_orphan_warnings(needs: list[Need]) -> set[str]:
    """Leaf needs that belong to no flow — the seam-coverage analogue of orphan proofs (#44).

    A product feels half-baked at the seams (the walk *between* stories), which only a flow
    (a need with children) scores. Once any flow exists, a leaf referenced by no flow is a
    gap in that seam coverage. With no flows at all this is silent — there's no seam to miss.
    """
    flows = [n for n in needs if n.children]
    if not flows:
        return set()
    in_a_flow: set[str] = set()
    for flow in flows:
        in_a_flow.update(flow.children)
    return {n.id for n in needs if not n.children and n.id not in in_a_flow}


def shared_proof_warnings(results: list[NeedResult]) -> dict[str, str]:
    """Flag a need whose *every* proof is also claimed by another need (#45).

    `orphans` catches a proof claimed by no need; this catches the opposite inflation — one
    scenario standing in for many needs, so several green rows rest on a single assertion.
    Sharing is sometimes legitimate (one behaviour serves two needs), so it is a warning, not
    a failure. A need with no proof, or at least one proof it alone claims, is not flagged.
    """
    by_proof: dict[str, set[str]] = {}
    for r in results:
        for p in r.need.proofs:
            by_proof.setdefault(p, set()).add(r.need.id)
    out: dict[str, str] = {}
    for r in results:
        proofs = r.need.proofs
        if proofs and all(len(by_proof[p]) > 1 for p in proofs):
            out[r.need.id] = "every proof shared with another need — weak independent coverage"
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
