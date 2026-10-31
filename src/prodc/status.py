"""Resolve needs into states: the engine behind ``prodc status``.

A leaf's state comes from its proofs; a flow (need with children) aggregates its
sub-needs. ``HOLE`` (no proof) is deliberately not a failure. It is an honest gap.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise

from .adapters import Adapter, Enumerable, Inventoried, ProofResult, SourceAdapter, ViewsAdapter
from .dedup import similarity
from .model import (
    SOLUTION_VERBS,
    Answer,
    AttestationKind,
    Confidence,
    Decision,
    Goal,
    Need,
    NeedPath,
    NeedResult,
    NeedState,
    Principle,
    PrincipleState,
    ProofState,
    Release,
    Role,
    SourceKind,
    Verdict,
    ears_warnings,
)
from .views import View, ViewInventory, ViewLink
from .views import clicks as view_clicks
from .views import dangling as dangling_links
from .views import has_links as client_has_links
from .views import orphans as orphan_views
from .views import unreachable as unreachable_count

#: Reserved proof-adapter name for a need→need edge (#research-board step 2): a proof whose
#: payload is another need id. Resolved by the :class:`Resolver` itself, not a config adapter,
#: so it never appears in ``[proofs.*]``; a ``[proofs.need]`` block would be shadowed by this.
_NEEDREF = "need"


def _text_warnings(need: Need) -> list[str]:
    out: list[str] = []
    # The outcome-shape lint (EARS + solution-verb) fires only until the author states the
    # warrant. A need with `claim` set has already articulated the proposition the lint was
    # prodding toward ("what delivering this establishes"), so it is silenced. This is what
    # unifies a product board and a research board without a mode: "When a roaster opens the
    # queue, she can see today's orders" and "π is irrational" are the same claim-under-uncertainty
    # at different altitudes; EARS is just one falsifiable-claim grammar, a stated `claim` another.
    if need.claim is None:
        first = need.text.strip().split(" ", 1)[0].lower().rstrip(":")
        if first in SOLUTION_VERBS:
            out.append(f"text may be a solution in disguise (starts with '{first}')")
        else:
            out.extend(ears_warnings(need.text))  # EARS shape check (redundant on solution verbs)
    # Source hygiene is universal (it is about evidence, not phrasing): always run it.
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
    """Whether a need's importance should be revisited, for ``plan --revisit`` (#59).

    Due when the need has an importance set but it is either never dated (no ``importance_set_at``)
    or last set more than ``max_age_days`` ago. A need with no importance is never due. There is
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

    This is a dangling (BROKEN) *source*, distinct from OPINION (no source at all). A
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
    leaf with no :class:`~prodc.model.Attestation` is trusted blindly. Surface that so a
    reviewer can confirm the link, without the tool pretending to prove semantic fit.
    """
    if need.children or not need.proofs or result.state is not NeedState.DELIVERED:
        return []
    att = need.attestation
    if att is None:
        return ["DELIVERED on an unattested proof link (warrant not reviewed) (#13)"]
    out: list[str] = []
    if att.kind is AttestationKind.AI:
        # an AI review is a middle rung: better than nothing, weaker than a human sign-off
        out.append(f"DELIVERED, warrant reviewed by {att.who} (AI), not a human (#13)")
    if att.verdict is not Verdict.PASS:
        # a recorded fail/concerns (or no verdict) must NOT read as a green warrant. The board
        # cannot lie. Only `pass` clears the review (0.4 false-green fix).
        said = att.verdict.value if att.verdict else "no verdict"
        out.append(f"DELIVERED but the warrant review did not pass ({said}); re-review (#13)")
    return out


def _answer_warnings(need: Need, result: NeedResult) -> list[str]:
    """Flag an ``answer`` authored on a question that is not settled (research board).

    DELIVERED means settled; ``answer`` records which way it settled. An answer declared while
    the state is anything but DELIVERED is a claim the proofs do not yet support. Surface it.
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


def _outcome_warnings(need: Need, result: NeedResult) -> list[str]:
    """Flag a green need whose outcome did not land, and an outcome with no goal to land on."""
    out: list[str] = []
    if need.outcome is None:
        return out
    if not need.outcome.landed and result.state is NeedState.DELIVERED:
        out.append("DELIVERED but the outcome did not land; not counted toward its goal (#97)")
    if need.goal is None:
        out.append("outcome recorded, but the need serves no goal: what did it not move? (#97)")
    return out


def _path_warnings(need: Need, result: NeedResult) -> list[str]:
    """Flag a click budget with no test to enforce it, or a path proof that does not pass (#99)."""
    path = need.path
    if path is None or path.max_clicks is None:
        return []
    if path.proof is None:
        return [f"path budget of {path.max_clicks} click(s) has no proof (#99)"]
    if result.path_state is not ProofState.DELIVERED and result.path_state is not None:
        return [f"path proof '{path.proof}' is {result.path_state.value.upper()} (#99)"]
    return []


def _path_view_warnings(need: Need, adapters: dict[str, Adapter]) -> list[str]:
    """Flag a path start or outcome that is not a view, when a ``views`` adapter exists (#101).

    A value is ``client:id`` or a bare id; a bare id means the only client when there is one.
    An outcome that is a proof locator of a configured adapter (a test id) is not a view and
    is not checked. Silent when no ``views`` adapter is configured.
    """
    path = need.path
    views = [a for a in adapters.values() if isinstance(a, ViewsAdapter)]
    if path is None or not views:
        return []
    clients = _view_clients(views)
    out: list[str] = []
    found: dict[str, set[str]] = {}
    for label, value in (("start", path.start), ("outcome", path.outcome)):
        prefix, sep, _ = value.partition(":")
        if label == "outcome" and sep and prefix in adapters:
            continue
        payload = _view_payload(value, clients)
        if payload is None:
            out.append(f"path {label} '{value}' names no client: write it as client:id (#101)")
            continue
        keys = {k for a in views for k in a.covers(payload)}
        if not keys:
            out.append(f"path {label} '{payload}' is not a view (#101)")
        else:
            found[label] = keys
    if len(found) == 2:
        out += _path_link_warnings(path, found, _inventory(views))
    return out


def _inventory(views: list[ViewsAdapter]) -> ViewInventory:
    """The views and links of every ``views`` adapter, merged."""
    invs = [a.load() for a in views]
    return ViewInventory(
        tuple(v for i in invs for v in i.views), tuple(lk for i in invs for lk in i.links)
    )


def _path_link_warnings(
    path: NeedPath, found: dict[str, set[str]], inv: ViewInventory
) -> list[str]:
    """Check a path over the view links: a route must exist and fit ``max_clicks`` (#105, #108).

    Skipped when the two ends are on different clients, or the client has no links at all.
    """
    start_clients = {k.partition(":")[0] for k in found["start"]}
    out_clients = {k.partition(":")[0] for k in found["outcome"]}
    if len(start_clients) != 1 or start_clients != out_clients:
        return []
    client = next(iter(start_clients))
    if not client_has_links(inv, client):
        return []
    starts = {k.partition(":")[2] for k in found["start"]}
    goals = {k.partition(":")[2] for k in found["outcome"]}
    n = view_clicks(inv, client, starts, goals)
    if n is None:
        return [
            f"path outcome '{path.outcome}' cannot be reached from start '{path.start}' "
            "over the view links (#105)"
        ]
    if path.max_clicks is not None and n > path.max_clicks:
        return [
            f"path takes {n} click(s) over the view links, over the budget of "
            f"{path.max_clicks} (#108)"
        ]
    return []


def view_link_errors(adapters: dict[str, Adapter]) -> list[str]:
    """A link to or from a view that is not in the inventory is a wrong inventory (#105)."""
    views = [a for a in adapters.values() if isinstance(a, ViewsAdapter)]
    return [
        f"{lk.file}: link {lk.source} -> {lk.target} names a view that is not in the "
        f"{lk.client} inventory (#105)"
        for lk in dangling_links(_inventory(views))
    ]


def _view_clients(views: list[ViewsAdapter]) -> list[str]:
    return list(dict.fromkeys(c for a in views for c in a.load().clients()))


def _view_payload(value: str, clients: list[str]) -> str | None:
    """``value`` as ``client:id``: as written, or with the only client added; None if ambiguous."""
    prefix, sep, _ = value.partition(":")
    if sep and prefix in clients:
        return value
    if len(clients) == 1:
        return f"{clients[0]}:{value}"
    return None


_CONFIDENCE_ORDER = list(Confidence)


def leaf_confidence(need: Need, result: NeedResult) -> tuple[Confidence | None, list[str]]:
    """The confidence of a DELIVERED leaf and the rule that set it; None when not DELIVERED (#97).

    First match wins. Weak rules name a recorded fact that undercuts the delivery. A missing
    attestation is not one: it is medium, and #13 warns on it separately. Evidence age is left
    out on purpose, so the value changes only when a recorded fact changes.
    """
    if result.state is not NeedState.DELIVERED:
        return None, []
    if need.outcome is not None and not need.outcome.landed:
        return Confidence.WEAK, ["outcome did not land"]
    att = need.attestation
    if att is not None and att.verdict is Verdict.FAIL:
        return Confidence.WEAK, ["attestation verdict is fail"]
    if result.declared:
        return Confidence.WEAK, ["proof is declared (tag or existence), not a results file"]
    if need.is_opinion:
        return Confidence.WEAK, ["opinion: no primary or secondary source"]
    if (
        att is not None
        and att.kind is AttestationKind.HUMAN
        and att.verdict is Verdict.PASS
        and need.strongest_kind is SourceKind.PRIMARY
    ):
        return Confidence.STRONG, ["human pass on a primary source with a results-backed proof"]
    return Confidence.MEDIUM, ["green proof, nothing recorded against it"]


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
        if need_id in self._visiting:  # cycle: stop and report
            return NeedResult(need, NeedState.BROKEN, detail=["cycle in children"])
        self._visiting.add(need_id)
        result = self._compute(need)
        self._visiting.discard(need_id)
        if need.children:
            if result.state is NeedState.DELIVERED:
                kids = [self.resolve(c.id).confidence for c in need.children]
                known = [k for k in kids if k is not None]
                if known:
                    result.confidence = min(known, key=_CONFIDENCE_ORDER.index)
                    result.confidence_detail = ["lowest confidence of the flow's steps"]
        else:
            result.confidence, result.confidence_detail = leaf_confidence(need, result)
        if need.path is not None and need.path.proof is not None:
            result.path_state = self._resolve_one(need.path.proof).state
        result.warnings = (
            _text_warnings(need)
            + _source_warnings(need, self._source_adapters)
            + _warrant_warnings(need, result)
            + _answer_warnings(need, result)
            + _path_warnings(need, result)
            + _path_view_warnings(need, self._adapters)
            + _outcome_warnings(need, result)
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
        the resolver can do. Dispatched here, not via :func:`_resolve_proof`.
        """
        name, sep, payload = locator.partition(":")
        if sep and name == _NEEDREF:
            return self.resolve_ref(payload)
        return _resolve_proof(locator, self._adapters)

    def resolve_ref(self, payload: str) -> ProofResult:
        """Resolve ``need:<id>`` (or ``need:<id>@<answer>``) against another need (#research step 2).

        A research question can depend on a peer: "B cannot be posed until A is settled." That
        edge is itself a proof: B delivers iff A is settled, so it rides the ``proofs`` tuple
        with no new field, and the resolver's own cycle detection and memoization cover A→B→A for
        free (a back-edge hits the ``_visiting`` guard and returns BROKEN). ``need:A`` resolves on
        A's *settledness* (DELIVERED); the optional ``need:A@yes`` form additionally requires A's
        authored :attr:`~prodc.model.Need.answer` to match. B never inherits A's answer. The
        dependency only requires A settled, optionally in a given direction. Public because a
        decision's ``awaits`` (#93) reads the same edge (see :func:`decision_readiness`).
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
            state = NeedState.UNRESOLVED  # a source couldn't be read: can't judge yet
        elif delivered == len(results):
            state = NeedState.DELIVERED
        else:
            state = NeedState.PENDING
        declared_only = state is NeedState.DELIVERED and all(r.declared for r in results)
        return NeedResult(
            need, state, delivered, len(results), declared, detail, declared_only=declared_only
        )

    def _aggregate_children(self, need: Need) -> NeedResult:
        warnings: list[str] = []
        child_states: list[NeedState] = []
        child_results: list[NeedResult] = []
        declared = False
        for c in need.children:
            if c.id not in self._by_id:
                warnings.append(f"unknown child id '{c.id}'")
                continue
            cr = self.resolve(c.id)
            child_states.append(cr.state)
            child_results.append(cr)
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
        # A flow rests on declared proofs only when every step and every seam proof does (#103).
        declared_only = (
            state is NeedState.DELIVERED
            and all(cr.declared_only for cr in child_results)
            and all(r.declared for r in seam_results)
        )
        return NeedResult(
            need, state, delivered, total, declared, detail, warnings, declared_only=declared_only
        )


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
    must_hole: int  # a HOLE on a must-have: the top of the board
    broken: int  # a dangling proof locator
    unresolved: int  # a proof whose source could not be read (e.g. sibling repo absent)
    opinion: int  # a need with no source of any kind

    @property
    def coverage(self) -> float:
        """Fraction DELIVERED, of needs that could be read.

        UNRESOLVED needs (a source that couldn't be read) are excluded from the
        denominator. They neither help nor hurt coverage, so a `--min-coverage` gate
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


def group_state(s: Summary) -> NeedState:
    """The derived state of an FK group (goal, release, role): the roll-up of its members (#80).

    One function behind every group's state, so a goal/initiative, a release slice and a role all
    read the same way and none carries a hand-set status that can drift from its needs: BROKEN if
    any member proof is broken, UNRESOLVED if any source couldn't be read, DELIVERED only when every
    member is, HOLE when nothing is covered yet, else PENDING (in progress). An empty group is a
    HOLE (nothing delivered, nothing pending).
    """
    if s.broken:
        return NeedState.BROKEN
    if s.unresolved:
        return NeedState.UNRESOLVED
    if s.total and s.delivered == s.total:
        return NeedState.DELIVERED
    if s.delivered == 0 and s.pending == 0:
        return NeedState.HOLE
    return NeedState.PENDING


@dataclass(frozen=True)
class Recurrence:
    """A baseline need and the clients that carry a variant of it (#32)."""

    baseline: Need
    clients: tuple[str, ...]  # distinct named clients with a variant, sorted
    variants: int  # how many variants reference this baseline

    @property
    def count(self) -> int:
        """How many clients share this baseline: the recurrence signal."""
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
    proof units and return the closest matches as ready-to-paste locators. Read-only: it never
    writes; ``--apply`` and BROKEN-relink are left to the caller/follow-up. A ``views``
    adapter is left out unless named by ``kind``: a view exists, it does not prove a need (#100).
    """
    inventories: list[tuple[str, list[str]]] = [
        (name, ad.inventory())
        for name, ad in adapters.items()
        if isinstance(ad, Inventoried)
        and (name == kind if kind is not None else not isinstance(ad, ViewsAdapter))
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
    """A candidate replacement for a BROKEN proof locator: a renamed test, relinkable (#54)."""

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

    A relink is for a locator whose adapter still exists but whose id no longer resolves. A test
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
                continue  # adapter gone, or can't enumerate: nothing to relink against
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
    """Pure ordering over recorded inputs only. Never a conjured score (#34).

    1. must + state: a must-HOLE sits at the top, then BROKEN, PENDING, …, DELIVERED.
    2. evidence kind: a real `interview` outranks `proxy`/`internal`/opinion at the same
       state, because a user actually asked. This is what reorders the author's guesses.
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

    Per-goal coverage is just :func:`summarize` over the needs that cite that goal. The
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
    coverage = [(g, _goal_summary(by_goal[g.id])) for g in goals]
    return coverage, ungoaled


def _goal_summary(results: list[NeedResult]) -> Summary:
    """:func:`summarize`, but a need whose outcome did not land is not delivered for its goal (#97).

    Board coverage still counts it: coverage asks "is it built", the goal asks "did it move".
    """
    s = summarize(results)
    missed = sum(
        1
        for r in results
        if r.need.counts_toward_coverage
        and r.state is NeedState.DELIVERED
        and r.need.outcome is not None
        and not r.need.outcome.landed
    )
    return replace(s, delivered=s.delivered - missed, pending=s.pending + missed)


def release_report(
    results: list[NeedResult], releases: list[Release]
) -> list[tuple[Release, Summary]]:
    """Coverage per release slice, in declared (ship) order: the story-map release view (#30).

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
    summary is an orphan role: on the roster though no need references it yet (a new packer),
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
            # a person is named but plays no declared role: the flag symmetric to an
            # ungoaled need. A need with neither who nor role (e.g. a bare flow) is not a
            # person with a missing role, so it is not listed here.
            unroled.append(r)
    coverage = [(p, summarize(by_role[p.id])) for p in roles]
    return coverage, unroled


def principle_state(principle: Principle, adapters: dict[str, Adapter]) -> PrincipleState:
    """Resolve a principle's guards into its enforced/stated/violated/broken state (#89).

    A principle proof is a guard against regression, so its ``ProofState`` reads differently from a
    need's (:class:`~prodc.model.PrincipleState` says why). Using :attr:`ProofResult.declared` to tell
    a declared-but-inactive guard from one that actually ran and failed:

    - ``implemented_in`` set but not resolving, or any proof BROKEN → **BROKEN** (lint fails).
    - any proof UNRESOLVED → **UNRESOLVED** (a source could not be read).
    - a proof PENDING with ``declared=False`` (a results artifact shows it failing) → **VIOLATED**.
    - no proofs, or only DELIVERED-or-declared-pending guards and not all green → **STATED** (honest).
    - every proof DELIVERED → **ENFORCED**.

    ``implemented_in`` is a pointer, not evidence: it can only make a principle BROKEN (a dangling
    locator), never ENFORCED.
    """
    impl_broken = (
        principle.implemented_in is not None
        and _resolve_proof(principle.implemented_in, adapters).state is ProofState.BROKEN
    )
    results = [_resolve_proof(loc, adapters) for loc in principle.proofs]
    if not principle.proofs:
        return PrincipleState.BROKEN if impl_broken else PrincipleState.STATED
    if impl_broken or any(r.state is ProofState.BROKEN for r in results):
        return PrincipleState.BROKEN
    if any(r.state is ProofState.UNRESOLVED for r in results):
        return PrincipleState.UNRESOLVED
    if any(r.state is ProofState.PENDING and not r.declared for r in results):
        return PrincipleState.VIOLATED  # a guard ran and failed: the code contradicts the stance
    if all(r.state is ProofState.DELIVERED for r in results):
        return PrincipleState.ENFORCED
    # some declared-pending guards, none failing: honestly not yet active
    return PrincipleState.STATED


@dataclass(frozen=True)
class PrincipleReport:
    """One principle, its enforcement state, and the decisions that rest on it: the ripple made visible."""

    principle: Principle
    declined: tuple[Need, ...]  # needs withdrawn citing this principle
    stale: tuple[Need, ...]  # of those, decided before the principle's latest revision: re-review
    state: PrincipleState = PrincipleState.STATED  # enforced/stated/violated/broken (#89)


def _decided_before(decided: str, revised: str | None) -> bool:
    """True when a decision dated ``decided`` predates a principle revised on ``revised``.

    Both are ISO dates. An undated principle, or a malformed date on either side, is never stale.
    there is no revision to compare against, and the loader does not own date format here.
    """
    if revised is None:
        return False
    try:
        return date.fromisoformat(decided) < date.fromisoformat(revised)
    except ValueError:
        return False


def principle_report(
    needs: list[Need],
    principles: list[Principle],
    adapters: dict[str, Adapter] | None = None,
) -> list[PrincipleReport]:
    """Each declared principle with its enforcement state, the needs withdrawn under it, and the stale ones.

    Reads the *whole* need list, withdrawn needs included. A declined need is off the board, so
    the board-filtered list would hide exactly what this reports. A decision is stale when the
    withdrawal is dated before the principle's ``revised_at``: the frame it was judged against has
    changed since, so it comes back up for re-review. Records-only: prodc flags, the PM re-decides.
    When ``adapters`` are given, each principle also carries its :func:`principle_state` (#89); without
    them the state defaults to STATED (a caller that has no proof adapters, e.g. a plain ripple view).
    """
    by_principle: dict[str, list[Need]] = {a.id: [] for a in principles}
    for n in needs:
        if n.withdrawn is not None and n.withdrawn.principle in by_principle:
            by_principle[n.withdrawn.principle].append(n)
    out: list[PrincipleReport] = []
    for a in principles:
        declined = sorted(by_principle[a.id], key=lambda n: n.id)
        stale = [
            n
            for n in declined
            if n.withdrawn is not None and _decided_before(n.withdrawn.date, a.revised_at)
        ]
        state = principle_state(a, adapters) if adapters is not None else PrincipleState.STATED
        out.append(PrincipleReport(a, tuple(declined), tuple(stale), state))
    return out


def active_decisions(decisions: list[Decision]) -> list[Decision]:
    """The decisions still in force: neither superseded (``withdrawn``) nor a staged ``draft``."""
    return [d for d in decisions if d.withdrawn is None and not d.draft]


def decisions_for(need_id: str, decisions: list[Decision]) -> list[Decision]:
    """The in-force decisions whose chosen solution serves ``need_id``: the 'how' behind a need."""
    return [d for d in active_decisions(decisions) if need_id in d.needs]


@dataclass(frozen=True)
class DecisionWait:
    """One entry of a decision's ``awaits``, resolved: the research it names, and how far it got."""

    ref: str  # as authored: ``<need-id>`` or ``<need-id>@<answer>``
    state: ProofState  # DELIVERED = settled (in the wanted direction, when one is named)
    detail: str


@dataclass(frozen=True)
class DecisionReadiness:
    """Whether a decision's research has settled (#93): derived from the awaited needs' proofs.

    BLOCKED is a property of the decision, not a :class:`NeedState`: the awaited needs keep their
    ordinary states, and nothing about coverage or delivery changes.
    """

    decision: Decision
    waits: tuple[DecisionWait, ...]

    @property
    def blocked(self) -> bool:
        return any(w.state is not ProofState.DELIVERED for w in self.waits)

    @property
    def open_refs(self) -> list[str]:
        return [w.ref for w in self.waits if w.state is not ProofState.DELIVERED]


def decision_readiness(
    decisions: list[Decision], needs: list[Need], adapters: dict[str, Adapter]
) -> dict[str, DecisionReadiness]:
    """Readiness for each decision that ``awaits`` research, keyed by decision id (#93).

    Each awaited ref resolves exactly like a ``need:`` proof (:meth:`Resolver.resolve_ref`), over
    every need in the model. A research need is often ``product: false`` and off the board, but it
    is still what the decision waits on. Decisions with no ``awaits`` are absent.
    """
    resolver = Resolver(needs, adapters)
    out: dict[str, DecisionReadiness] = {}
    for d in decisions:
        if not d.awaits:
            continue
        waits: list[DecisionWait] = []
        for ref in d.awaits:
            r = resolver.resolve_ref(ref)
            waits.append(DecisionWait(ref, r.state, r.detail))
        out[d.id] = DecisionReadiness(d, tuple(waits))
    return out


def awaits_warnings(
    decisions: list[Decision], needs: list[Need], readiness: dict[str, DecisionReadiness]
) -> list[tuple[str, str]]:
    """Lint for a decision's ``awaits`` (#93), keyed by decision id: warnings, never errors.

    - committed (not ``draft``) while its research is still open;
    - an awaited direction the research answered the other way: decided against its own result;
    - waiting on a withdrawn need: abandoned research;
    - waiting on a product need: research belongs on a ``product: false`` need, or it leaks into
      coverage and blurs the line between research and a delivery proof.
    """
    by_id = {n.id: n for n in needs}
    out: list[tuple[str, str]] = []
    for d in decisions:
        if d.withdrawn is not None:
            continue  # a superseded decision's research no longer matters
        r = readiness.get(d.id)
        if r is None:
            continue
        if not d.draft and r.blocked:
            out.append((d.id, f"committed before its research settled: {', '.join(r.open_refs)}"))
        for ref in d.awaits:
            nid, sep, direction = ref.partition("@")
            n = by_id[nid]
            if sep and n.answer is not None and n.answer.value != direction:
                out.append(
                    (
                        d.id,
                        f"awaits {ref} but {nid} answered {n.answer.value}: decided against its research",
                    )
                )
            if n.withdrawn is not None:
                out.append(
                    (d.id, f"awaits {nid}, which is withdrawn; drop it or withdraw the decision")
                )
            if n.product:
                out.append(
                    (
                        d.id,
                        f"awaits {nid}, a product need; research belongs on a product: false need",
                    )
                )
    return out


def stale_decisions(
    decisions: list[Decision], principles: list[Principle]
) -> list[tuple[Decision, str]]:
    """Each in-force decision paired with a principle it cites that was revised after it was decided.

    The same ripple a withdrawal gets (:func:`principle_report`), the other way round: a solution
    chosen under an older statement of a principle comes back up when the principle moves. Reuses
    :func:`_decided_before`; an undated decision or principle never counts (nothing to compare).
    """
    revised = {p.id: p.revised_at for p in principles}
    out: list[tuple[Decision, str]] = []
    for d in active_decisions(decisions):
        for pid in d.principles:
            if pid in revised and _decided_before(d.decided_at or "", revised[pid]):
                out.append((d, pid))
    return out


def orphaned_decisions(decisions: list[Decision], needs: list[Need]) -> list[Decision]:
    """In-force decisions whose every served need is withdrawn or non-product: the real orphan.

    A decision must name a need at load, but that need can later be withdrawn (``out_of_scope``) or
    marked non-product. A decision left serving only such needs is engineering with no live product
    reason. Re-tie it to a live need, or withdraw it. (A need not in ``needs`` at all is a load
    error, never reached here.)
    """
    by_id = {n.id: n for n in needs}
    out: list[Decision] = []
    for d in active_decisions(decisions):
        live = [
            nid
            for nid in d.needs
            if (n := by_id.get(nid)) is not None and not n.is_withdrawn and n.product
        ]
        if not live:
            out.append(d)
    return out


@dataclass(frozen=True)
class Contradiction:
    """Two needs in tension: clients wanting opposite things. ``unresolved`` = both still live.

    The ``contradicts`` relation is symmetric and the model carries it on both needs, so a pair is
    unordered (``a.id < b.id``). It is *unresolved* while neither need has left the board: the
    tension the product vision has not yet decided. Withdrawing one side (typically ``out_of_scope``
    citing the principle that decides) resolves it. This is the structural home for "clients want
    opposite things; the vision decides" (#B).
    """

    a: Need
    b: Need
    unresolved: bool  # both live (not withdrawn, not a staged draft): the vision hasn't decided


def _contradiction_live(need: Need) -> bool:
    """On the board for contradiction purposes: not decided-against, not a staged draft."""
    return not need.is_withdrawn and not need.draft


def contradictions(needs: list[Need]) -> list[Contradiction]:
    """The symmetric ``contradicts`` pairs across ``needs``, each flagged ``unresolved`` when live.

    Reads the relation off the (already symmetric) model, so a pair surfaces from either need's
    ``contradicts``; pairs are deduped and unordered. A target not present in ``needs`` is skipped,
    so a scoped subset never raises. Pass the whole ``model.needs`` to judge resolution honestly
    (a withdrawn side is what resolves a pair, and a board-filtered list would have dropped it).
    """
    by_id = {n.id: n for n in needs}
    seen: set[frozenset[str]] = set()
    out: list[Contradiction] = []
    for n in needs:
        for t in n.contradicts:
            if t == n.id or t not in by_id:
                continue
            key = frozenset({n.id, t})
            if key in seen:
                continue
            seen.add(key)
            a, b = (n, by_id[t]) if n.id < t else (by_id[t], n)
            out.append(Contradiction(a, b, _contradiction_live(a) and _contradiction_live(b)))
    out.sort(key=lambda c: (c.a.id, c.b.id))
    return out


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

    A handoff is a consecutive pair of a flow's children whose ``role`` differs: the point in
    the journey where one person's work passes to the next (Patton's backbone, read as an
    ordered story map). It keys on ``role``, not ``who``, so it does not fire on the file-level
    ``who`` (a person) that every need in a file shares (the noise #52's follow-up flagged). A
    file-level ``role:`` is fine: it is still an archetype chosen once, on purpose (#96). No new
    edge type: the order already in ``children`` is the sequence.
    """
    by_id = {n.id: n for n in needs}
    out: list[Handoff] = []
    for flow in needs:
        if not flow.children:
            continue
        steps = [by_id[c.id] for c in flow.children if c.id in by_id]
        for a, b in pairwise(steps):
            if a.role and b.role and a.role != b.role:
                out.append(Handoff(flow, a, b, a.role, b.role))
    return out


def applicable_needs(needs: list[Need], client: str) -> list[Need]:
    """The needs in force for one client: its own variants, plus every shared baseline
    it has not specialised.

    A baseline (``variant_of is None`` and ``client is None``) applies to all clients
    unless this client carries a variant of it. In that case the variant overrides the
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


def flow_orphan_warnings(needs: list[Need]) -> set[str]:
    """Leaf needs that belong to no flow: the seam-coverage analogue of orphan proofs (#44).

    A product feels half-baked at the seams (the walk *between* stories), which only a flow
    (a need with children) scores. Once any flow exists, a leaf referenced by no flow is a
    gap in that seam coverage. With no flows at all this is silent: there's no seam to miss.
    """
    flows = [n for n in needs if n.children]
    if not flows:
        return set()
    in_a_flow: set[str] = set()
    for flow in flows:
        in_a_flow.update(c.id for c in flow.children)
    return {n.id for n in needs if not n.children and n.id not in in_a_flow}


def flow_step_warnings(needs: list[Need], steps: tuple[str, ...]) -> list[tuple[str, str]]:
    """Judgment-level hygiene on a flow's steps, once a ``[flows].steps`` vocabulary exists (#90).

    Opt-in: silent when no vocabulary is declared. A board with no steps has no journey to
    grade. Membership (a step word that isn't in the vocab) is the loader's hard error; this
    catches the *shape* of the journey, keyed by flow id, as warnings:

    - **never terminal**: a flow with stepped edges but none carrying the terminal step. The
      journey never ends (Patton: the story must end). The message names the configured word.
    - **out of order**: stepped edges whose rank decreases along ``children``. The map runs
      backwards. Warned once per flow.
    - **mixed bare/stepped**: a flow where some edges carry a step and some don't. A use case
      with a hole, which would otherwise pass clean.

    A flow with zero stepped edges is exempt: it's a plain flow, not a use case (#90), and
    warning it would punish every existing board the moment a vocabulary is declared.
    """
    if not steps:
        return []
    terminal = steps[-1]
    rank = {s: i for i, s in enumerate(steps)}
    out: list[tuple[str, str]] = []
    for flow in needs:
        if not flow.children:
            continue
        stepped = [c for c in flow.children if c.step is not None]
        if not stepped:
            continue  # a plain flow, not a use case: exempt
        if len(stepped) != len(flow.children):
            bare = next(c.id for c in flow.children if c.step is None)
            out.append(
                (flow.id, f"edge {bare!r} has no step while siblings do (a use case with a hole)")
            )
        if not any(c.step == terminal for c in stepped):
            out.append(
                (
                    flow.id,
                    f"no edge carries the terminal step {terminal!r}: the journey never ends; "
                    "add it or drop the steps",
                )
            )
        ranks = [rank[c.step] for c in stepped if c.step in rank]
        if any(b < a for a, b in pairwise(ranks)):
            out.append((flow.id, "steps run out of order; reorder children or re-step the edges"))
    return out


def shared_proof_warnings(results: list[NeedResult]) -> dict[str, str]:
    """Flag a need whose *every* proof is also claimed by another need (#45).

    `orphans` catches a proof claimed by no need; this catches the opposite inflation: one
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
            out[r.need.id] = "every proof shared with another need (weak independent coverage)"
    return out


def orphans(needs: list[Need], adapters: dict[str, Adapter]) -> dict[str, list[str]]:
    """Proof units claimed by no need, per enumerable adapter: the reverse of the board.

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


@dataclass(frozen=True)
class ViewRow:
    """One view in the ``prodc views`` report: the needs that point at it and their state (#102)."""

    view: View
    depth: int  # containment depth: 0 for a top-level view
    needs: tuple[str, ...]  # ids of needs whose proofs or path name this view
    state: NeedState | None  # group state of those needs; None when no need points here
    justified: bool  # a need points here or at a child, or ``needless_ok`` is set
    orphan: bool = False  # top-level, no inbound link, not a path start (#106)
    inbound: tuple[ViewLink, ...] = ()  # links that end at this view (#107)
    outbound: tuple[ViewLink, ...] = ()  # links that start at this view (#107)

    @property
    def untyped(self) -> bool:
        return self.view.kind is None


def view_report(
    results: list[NeedResult], adapters: dict[str, Adapter], client: str | None = None
) -> list[ViewRow]:
    """Every view, in tree order per client, with the needs that point at it (#102).

    A need points at a view through a ``views:`` proof or its ``path`` start or outcome. A
    parent with no need of its own is justified when one of its children is.
    """
    views_by_name = {n: a for n, a in adapters.items() if isinstance(a, ViewsAdapter)}
    inv = _inventory(list(views_by_name.values()))
    all_views = list(inv.views)
    clients = _view_clients(list(views_by_name.values()))
    entries = view_entries(results, adapters)
    orphaned = orphan_views(inv, entries)
    pointing: dict[str, list[str]] = {}
    for r in results:
        payloads = [
            payload
            for name, _, payload in (p.partition(":") for p in r.need.proofs)
            if name in views_by_name
        ]
        if r.need.path is not None:
            for value in (r.need.path.start, r.need.path.outcome):
                payload = _view_payload(value, clients)
                if payload is not None:
                    payloads.append(payload)
        keys = {k for p in payloads for a in views_by_name.values() for k in a.covers(p)}
        for k in sorted(keys):
            pointing.setdefault(k, []).append(r.need.id)
    by_id = {r.need.id: r for r in results}
    children: dict[str, list[View]] = {}
    roots: list[View] = []
    known = {v.key for v in all_views}
    for v in sorted(all_views, key=lambda x: x.id):
        parent_key = f"{v.client}:{v.parent}" if v.parent is not None else None
        if parent_key is not None and parent_key in known:
            children.setdefault(parent_key, []).append(v)
        else:
            roots.append(v)

    def justified(v: View) -> bool:
        return (
            v.needless_ok or v.key in pointing or any(justified(c) for c in children.get(v.key, []))
        )

    out: list[ViewRow] = []

    def walk(v: View, depth: int) -> None:
        ids = tuple(pointing.get(v.key, []))
        state = group_state(summarize([by_id[i] for i in ids])) if ids else None
        out.append(
            ViewRow(
                v,
                depth,
                ids,
                state,
                justified(v),
                orphan=v.key in orphaned,
                inbound=tuple(
                    lk for lk in inv.links if lk.client == v.client and lk.target == v.id
                ),
                outbound=tuple(
                    lk for lk in inv.links if lk.client == v.client and lk.source == v.id
                ),
            )
        )
        for c in children.get(v.key, []):
            walk(c, depth + 1)

    for c in clients:
        if client is not None and c != client:
            continue
        for v in roots:
            if v.client == c:
                walk(v, 0)
    return out


def view_entries(results: list[NeedResult], adapters: dict[str, Adapter]) -> set[str]:
    """The views users start from: every view a need's ``path.start`` names, as ``client:id``.

    An entry is derived from a need, never flagged on the view, so there is no switch that
    excuses a view nobody links to.
    """
    views = [a for a in adapters.values() if isinstance(a, ViewsAdapter)]
    clients = _view_clients(views)
    out: set[str] = set()
    for r in results:
        if r.need.path is None:
            continue
        payload = _view_payload(r.need.path.start, clients)
        if payload is not None:
            out.update(k for a in views for k in a.covers(payload))
    return out


def view_entry_warnings(results: list[NeedResult], adapters: dict[str, Adapter]) -> list[str]:
    """A client that has links but no entry view, so orphans and reachability cannot be judged (#110).

    One message per client. Fix it with a need whose ``path.start`` names a view of that client.
    """
    inv = _inventory([a for a in adapters.values() if isinstance(a, ViewsAdapter)])
    entries = view_entries(results, adapters)
    return [
        f"{c}: the view inventory has links but no entry view: add a need whose path starts at "
        f"a {c} view (#110)"
        for c in inv.clients()
        if client_has_links(inv, c) and not any(k.partition(":")[0] == c for k in entries)
    ]


def view_unreachable(results: list[NeedResult], adapters: dict[str, Adapter]) -> dict[str, int]:
    """Per client, how many views cannot be reached from an entry view (#105).

    A client with no links or no entry view is left out.
    """
    inv = _inventory([a for a in adapters.values() if isinstance(a, ViewsAdapter)])
    entries = view_entries(results, adapters)
    counts = {c: unreachable_count(inv, c, entries) for c in inv.clients()}
    return {c: n for c, n in counts.items() if n is not None}
