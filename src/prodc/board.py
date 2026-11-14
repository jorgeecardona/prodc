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

from .anchor import anchor_drift
from .config import Config
from .dedup import duplicate_pairs, variant_suggestions, who_variants
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
    goal_report,
    handoffs,
    is_ai_attested_warning,
    last_observed,
    orphans,
    principle_report,
    proof_kind,
    recurrence,
    release_report,
    resolve,
    role_report,
    shared_proof_warnings,
    summarize,
)


def _duplicate_warnings(results: list[NeedResult], needs: list[Need], threshold: float) -> None:
    """Append a `possible duplicate of <id>` warning to each need in a candidate pair (#55)."""
    by_id = {r.need.id: r for r in results}
    for pair in duplicate_pairs(needs, threshold):
        msg_a = f"possible duplicate of {pair.b.id} ({pair.score:.2f}) (#55)"
        msg_b = f"possible duplicate of {pair.a.id} ({pair.score:.2f}) (#55)"
        if pair.a.id in by_id:
            by_id[pair.a.id].warnings.append(msg_a)
        if pair.b.id in by_id:
            by_id[pair.b.id].warnings.append(msg_b)


def _importance_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Flag importance values off the rubric, or set long ago / never dated (#59)."""
    today = date.today()
    for r in results:
        imp = r.need.importance
        if imp is None:
            continue
        if cfg.importance_levels and imp not in cfg.importance_levels:
            allowed = ", ".join(str(n) for n in sorted(cfg.importance_levels))
            r.warnings.append(f"importance {imp} is off the declared scale ({allowed}) (#59)")
            continue
        when = r.need.importance_set_at
        if when is None:
            r.warnings.append(
                "importance set but no revisit date (`set importance` stamps one) (#59)"
            )
        elif cfg.importance_revisit_days is not None:
            try:
                days = (today - date.fromisoformat(when)).days
            except ValueError:
                days = None
            if days is not None and days > cfg.importance_revisit_days:
                r.warnings.append(
                    f"importance set {days}d ago (> {cfg.importance_revisit_days}d). Revisit (#59)"
                )


def _draft_age_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Flag staged drafts older than `[lint].draft_max_age_days`, so a batch can't be forgotten (#60).

    Mirrors the importance-revisit check: a draft with no `draft_added` stamp is flagged undated
    (it cannot be aged, so it is not silently exempt); a dated draft past the limit is flagged with
    its age. Only runs when the knob is set.
    """
    if cfg.draft_max_age_days is None:
        return
    today = date.today()
    for r in results:
        if not r.need.draft or r.need.is_withdrawn:
            continue
        when = r.need.draft_added
        if when is None:
            r.warnings.append("draft with no staged date (`add --draft` stamps one) (#60)")
            continue
        try:
            days = (today - date.fromisoformat(when)).days
        except ValueError:
            continue
        if days > cfg.draft_max_age_days:
            r.warnings.append(
                f"draft staged {days}d ago (> {cfg.draft_max_age_days}d). Promote or drop (#60)"
            )


def _variant_warnings(results: list[NeedResult], needs: list[Need], threshold: float) -> None:
    """Flag cross-client recurrences nobody linked with ``variant_of`` / ``not_variant_of`` (#56)."""
    by_id = {r.need.id: r for r in results}
    for g in variant_suggestions(needs, threshold):
        others = ", ".join(m.id for m in g.members)
        for m in g.members:
            if m.id in by_id:
                by_id[m.id].warnings.append(
                    f"unlinked cross-client recurrence with {others}: set variant_of or "
                    f"not_variant_of ({g.score:.2f}) (#56)"
                )


def _stale_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Flag evidence older than ``[lint].stale_after_days`` (#58)."""
    if cfg.stale_after_days is None:
        return
    today = date.today()
    for r in results:
        age = evidence_age_days(r.need, today)
        if age is not None and age > cfg.stale_after_days:
            r.warnings.append(f"evidence is {age}d old (> {cfg.stale_after_days}d) (#58)")


def _who_warnings(results: list[NeedResult], needs: list[Need], threshold: float) -> None:
    """Flag ``who`` spellings that may name one person (#61)."""
    by_id = {r.need.id: r for r in results}
    for v in who_variants(needs, threshold):
        whos = " / ".join(repr(w) for w in v.whos)
        for nid in v.need_ids:
            if nid in by_id:
                by_id[nid].warnings.append(
                    f"who may name the same person: {whos} (needs {', '.join(v.need_ids)}) (#61)"
                )


def _declared_only_warnings(results: list[NeedResult]) -> None:
    """Warn on a DELIVERED must-have whose every proof is declared, so ``--strict`` fails (#103).

    A declared proof (``files``, ``accept``, ``prototype``, ``citation``) says something exists,
    not that the need works. One results-backed proof clears the warning. A should-have is left
    alone: its confidence already reads ``weak`` (#97).
    """
    for r in results:
        if r.need.must and r.declared_only:
            r.warnings.append(
                "must-have DELIVERED on declared proofs only: add a results-backed proof (#103)"
            )


def _anchor_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Warn when a source quote is no longer at the lines its anchor names (#57)."""
    for r in results:
        for s in r.need.sources:
            why = anchor_drift(cfg.root, s)
            if why is not None:
                r.warnings.append(f"source anchor drifted: {why} (#57)")


def _ai_attestation_policy(results: list[NeedResult], cfg: Config) -> None:
    """With ``[lint].ai_attestation = "counts"``, an AI review no longer warns it is not human (#87)."""
    if cfg.ai_attestation != "counts":
        return
    for r in results:
        r.warnings[:] = [w for w in r.warnings if not is_ai_attested_warning(w)]


def _expects_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Warn when a need declares the proof kind it awaits but is wired to other kinds (#78)."""
    for r in results:
        want = r.need.expects
        if want is None or not r.need.proofs:
            continue
        names = [p.partition(":")[0] for p in r.need.proofs]
        kinds = {proof_kind(cfg.adapters[n]) for n in names if n in cfg.adapters}
        if want not in kinds:
            wired = ", ".join(sorted({n for n in names}))
            r.warnings.append(
                f"expects {want.with_article} proof, but its proofs resolve through: {wired} (#78)"
            )


def annotate_need_warnings(results: list[NeedResult], needs: list[Need], cfg: Config) -> None:
    """Append every per-need hygiene warning, in one fixed order (#81).

    ``status`` and ``lint`` both call this, so a warning on a need reads the same under either.
    Warnings about the model rather than one need (principles, decisions, tags, flow steps, a
    contradiction) are not per-need and stay in ``lint``.
    """
    annotate_board_warnings(results, needs)
    _duplicate_warnings(results, needs, cfg.duplicate_threshold)
    _variant_warnings(results, needs, cfg.duplicate_threshold)
    _stale_warnings(results, cfg)
    _who_warnings(results, needs, cfg.duplicate_threshold)
    _importance_warnings(results, cfg)
    _draft_age_warnings(results, cfg)
    _declared_only_warnings(results)
    _anchor_warnings(results, cfg)
    _expects_warnings(results, cfg)
    _ai_attestation_policy(results, cfg)


def warrant(need: Need) -> str:
    """The warrant column: the strongest source kind, or 'opinion' when there is no source at all.

    A `primary` source names its person (`primary:who`, and `primary:who (role)` when that person's
    role is recorded, #52); `secondary`/`assumption` show the kind. A need with any source is shown
    by that kind even if it is an opinion (only an assumption). The opinion roll-up lives in the
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


def path_summary(r: NeedResult) -> str | None:
    """The need's path as one line: ``start → outcome``, its click budget, and its proof state (#99)."""
    path = r.need.path
    if path is None:
        return None
    out = f"{path.start} → {path.outcome}"
    if path.max_clicks is not None:
        out += f", max {path.max_clicks} click{'' if path.max_clicks == 1 else 's'}"
    if path.proof is not None:
        state = r.path_state.value.upper() if r.path_state else "?"
        out += f", proof {path.proof} [{state}]"
    elif path.max_clicks is not None:
        out += ", no proof"
    return out


def path_payload(r: NeedResult) -> dict[str, object] | None:
    """The need's path as a plain dict for JSON output, or None when it has none (#99)."""
    path = r.need.path
    if path is None:
        return None
    return {
        "start": path.start,
        "outcome": path.outcome,
        "max_clicks": path.max_clicks,
        "proof": path.proof,
        "proof_state": r.path_state.value if r.path_state else None,
    }


def annotate_board_warnings(results: list[NeedResult], needs: list[Need]) -> None:
    """Append the cross-need hygiene warnings (shared proofs #45)."""
    shared = shared_proof_warnings(results)
    for r in results:
        if r.need.id in shared:
            r.warnings.append(shared[r.need.id])


def need_payload(r: NeedResult, *, flavor: Literal["board", "html"] = "board") -> dict[str, object]:
    """One need serialised to a plain dict: the single Need-to-JSON used by the board and viewer.

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
            "confidence": r.confidence.value if r.confidence else None,
            "must": need.must,
            "who": need.who or "(unassigned)",
            "client": need.client,
            "opinion": need.is_opinion,
            "warrant": strongest.value if strongest is not None else "opinion",
            "importance": need.importance,
            "goal": need.goal,
            "release": need.release,
            "claim": need.claim,
            "expects": need.expects.value if need.expects else None,
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
            "tags": list(need.tags),
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
                    "anchor": s.anchor,
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
        "stage": need.stage.value,
        "contradicts": list(need.contradicts),
        "tags": list(need.tags),
        "path": path_payload(r),
        "outcome": (
            {
                "landed": need.outcome.landed,
                "date": need.outcome.date,
                "who": need.outcome.who,
                "evidence": need.outcome.evidence,
            }
            if need.outcome
            else None
        ),
        "confidence": r.confidence.value if r.confidence else None,
        "confidence_detail": list(r.confidence_detail),
        "expects": need.expects.value if need.expects else None,
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
    principles: list[PrincipleReport]  # over the whole model: declined needs are off the board


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
    appends every per-need warning (:func:`annotate_need_warnings`, #81), as ``status`` and
    ``lint`` do. The markdown/HTML reports leave it off.
    The declared goals/releases/roles come from ``model``; the recurrence/handoffs/orphans views
    are computed over the resolved ``needs``. The principle report reads the whole ``model.needs``:
    the needs declined under a principle are withdrawn, so the filtered ``needs`` never holds them.
    """
    use_needs = list(model.needs) if needs is None else needs
    results = resolve(use_needs, cfg.adapters, cfg.source_adapters)
    if annotate_warnings:
        annotate_need_warnings(results, use_needs, cfg)
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
        principles=principle_report(list(model.needs), list(model.principles), cfg.adapters),
    )
