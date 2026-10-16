"""Gather the resolved board once, for every renderer to consume.

`prodc status`, `prodc report` (markdown), and `prodc report --format html` each need the
same thing: resolve every need, roll it up, and compute the per-goal / per-release / per-role
coverage, the handoffs, the recurrence, and the orphan proofs. They used to do that gather
three separate times, which is how the three outputs could silently drift. :func:`gather` does
it once and returns a :class:`ResolvedBoard`; the renderers format that struct. :func:`warrant`
and :func:`need_payload` are the one user-signal string and the one Need-to-dict serialiser the
board and the HTML viewer share, so a need looks the same wherever it is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .config import Config
from .model import (
    Goal,
    Model,
    Need,
    NeedResult,
    Release,
    Role,
    SourceKind,
    ears_shape,
)
from .status import (
    Handoff,
    PrincipleReport,
    Recurrence,
    Summary,
    evidence_age_days,
    flow_orphan_warnings,
    goal_report,
    handoffs,
    last_observed,
    orphans,
    principle_report,
    recurrence,
    release_report,
    resolve,
    role_report,
    shared_proof_warnings,
    summarize,
)


def warrant(need: Need) -> str:
    """The warrant column: the strongest source kind, or 'opinion' when there is no source at all.

    A `primary` source names its person (`primary:who`, and `primary:who (role)` when that person's
    role is recorded, #52); `secondary`/`assumption` show the kind. A need with any source is shown
    by that kind even if it is an opinion (only an assumption) — the opinion roll-up lives in the
    gap counts, this column shows the literal evidence tier.
    """
    strongest = need.strongest_kind  # the one source-strength ranking lives on the model
    if strongest is None:
        return "opinion"
    if strongest is SourceKind.PRIMARY:
        src = next((s for s in need.sources if s.kind is SourceKind.PRIMARY and s.who), None)
        if src is None:
            return "primary"
        return f"primary:{src.who}" + (f" ({src.role})" if src.role else "")
    return strongest.value


def annotate_board_warnings(results: list[NeedResult], needs: list[Need]) -> None:
    """Append the cross-need hygiene warnings (shared proofs #45, seam coverage #44)."""
    shared = shared_proof_warnings(results)
    flow_orphans = flow_orphan_warnings(needs)
    for r in results:
        if r.need.id in shared:
            r.warnings.append(shared[r.need.id])
        if r.need.id in flow_orphans:
            r.warnings.append("belongs to no flow — seam not covered (#44)")


def need_payload(r: NeedResult, *, flavor: Literal["board", "html"] = "board") -> dict[str, object]:
    """One need serialised to a plain dict — the single Need-to-JSON used by the board and viewer.

    ``flavor="board"`` is the status/`show` payload (the full record); ``flavor="html"`` is the
    report viewer's flatter row. They carry different fields in a different order, so the two
    shapes live here together, byte-for-byte as they were, rather than as copies in two modules.
    """
    need = r.need
    if flavor == "html":
        strongest = need.strongest_kind
        return {
            "id": need.id,
            "text": need.text,
            "description": need.description,
            "state": r.state.value,
            "must": need.must,
            "who": need.who or "(unassigned)",
            "label": need.label,
            "client": need.client,
            "opinion": need.is_opinion,
            "warrant": strongest.value if strongest is not None else "opinion",
            "importance": need.importance,
            "goal": need.goal,
            "release": need.release,
            "claim": need.claim,
            "answer": need.answer.value if need.answer else None,
            "withdrawn": (
                {
                    "reason": need.withdrawn.reason,
                    "date": need.withdrawn.date,
                    "kind": need.withdrawn.kind.value,
                    "principle": need.withdrawn.principle,
                    "of": need.withdrawn.of,
                }
                if need.withdrawn
                else None
            ),
            "proofs": list(need.proofs),
            "contradicts": list(need.contradicts),
            "detail": list(r.detail),
            "warnings": list(r.warnings),
            "attestation": (
                {
                    "who": need.attestation.who,
                    "date": need.attestation.date,
                    "kind": need.attestation.kind.value,
                    "verdict": need.attestation.verdict,
                }
                if need.attestation
                else None
            ),
            "sources": [
                {
                    "kind": s.kind.value,
                    "who": s.who,
                    "role": s.role,
                    "date": s.date,
                    "quote": s.quote,
                    "locator": s.locator,
                }
                for s in need.sources
            ],
        }
    return {
        "id": need.id,
        "who": need.who,
        "role": need.role,
        "text": need.text,
        "description": need.description,
        "must": need.must,
        "state": r.state.value,
        "grounds": r.state.value,
        "warrant": warrant(need),
        "shape": ears_shape(need.text).value,
        "client": need.client,
        "variant_of": need.variant_of,
        "goal": need.goal,
        "release": need.release,
        "product": need.product,
        "draft": need.draft,
        "contradicts": list(need.contradicts),
        "answer": need.answer.value if need.answer else None,
        "withdrawn": (
            {
                "reason": need.withdrawn.reason,
                "date": need.withdrawn.date,
                "kind": need.withdrawn.kind.value,
                "principle": need.withdrawn.principle,
                "of": need.withdrawn.of,
            }
            if need.withdrawn
            else None
        ),
        "importance": need.importance,
        "importance_set_at": need.importance_set_at,
        "claim": need.claim,
        "attestation": (
            {
                "who": need.attestation.who,
                "date": need.attestation.date,
                "kind": need.attestation.kind.value,
                "verdict": need.attestation.verdict,
                "comment": need.attestation.comment,
            }
            if need.attestation
            else None
        ),
        "delivered": r.delivered,
        "total": r.total,
        "declared": r.declared,
        "opinion": need.is_opinion,
        "only_assumption": need.only_assumption,
        "evidence_age": evidence_age_days(need, date.today()),
        "last_observed_at": last_observed(need),
        "detail": r.detail,
        "warnings": r.warnings,
    }


@dataclass(frozen=True)
class ResolvedBoard:
    """The board resolved once: the results and every roll-up the renderers read off it."""

    results: list[NeedResult]
    summary: Summary
    goal_cov: list[tuple[Goal, Summary]]
    ungoaled: list[NeedResult]
    rel_cov: list[tuple[Release, Summary]]
    role_cov: list[tuple[Role, Summary]]
    unroled: list[NeedResult]
    handoffs: list[Handoff]
    recurrence: list[Recurrence]
    orphans: dict[str, list[str]]
    principles: list[PrincipleReport]  # over the whole model — declined needs are off the board


def gather(
    cfg: Config,
    model: Model,
    *,
    needs: list[Need] | None = None,
    annotate_warnings: bool = False,
) -> ResolvedBoard:
    """Resolve the board once and compute every roll-up a renderer needs.

    ``needs`` overrides which needs are resolved (the caller filters drafts/client/goal/stale
    before calling and passes the result); it defaults to the whole model. ``annotate_warnings``
    appends the cross-need board warnings (#44/#45) to the results, as ``prodc status`` does —
    the markdown/HTML reports leave it off, exactly as they did before this was factored out.
    The declared goals/releases/roles come from ``model``; the recurrence/handoffs/orphans views
    are computed over the resolved ``needs``. The principle report reads the whole ``model.needs``:
    the needs declined under a principle are withdrawn, so the filtered ``needs`` never holds them.
    """
    use_needs = list(model.needs) if needs is None else needs
    results = resolve(use_needs, cfg.adapters, cfg.source_adapters)
    if annotate_warnings:
        annotate_board_warnings(results, use_needs)
    summary = summarize(results)
    goal_cov, ungoaled = goal_report(results, list(model.goals))
    rel_cov = release_report(results, list(model.releases))
    role_cov, unroled = role_report(results, list(model.roles))
    return ResolvedBoard(
        results=results,
        summary=summary,
        goal_cov=goal_cov,
        ungoaled=ungoaled,
        rel_cov=rel_cov,
        role_cov=role_cov,
        unroled=unroled,
        handoffs=handoffs(use_needs),
        recurrence=recurrence(use_needs),
        orphans=orphans(use_needs, cfg.adapters),
        principles=principle_report(list(model.needs), list(model.principles)),
    )
