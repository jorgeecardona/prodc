"""``prodc`` command line: one verb, ``status`` — the board.

Prints the gap between needs and what the test suite proves, sorted by what needs
attention first. Exit 1 on a BROKEN proof; ``--strict`` also on an opinion. A HOLE
never fails — it is the honest gap you want people to keep writing.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import cast

from . import __version__
from .config import Config, ConfigError
from .dedup import (
    DupPair,
    VariantGroup,
    duplicate_pairs,
    matches_for,
    variant_suggestions,
    who_variants,
)
from .loader import LoaderError, load
from .model import (
    Goal,
    Model,
    Need,
    NeedResult,
    NeedState,
    Release,
    Role,
    SourceKind,
    ears_shape,
)
from .report import render_markdown
from .status import (
    Handoff,
    ProofSuggestion,
    Recurrence,
    Summary,
    applicable_needs,
    argument_defects,
    evidence_age_days,
    flow_orphan_warnings,
    goal_report,
    handoffs,
    last_observed,
    orphans,
    proof_suggestions,
    rank,
    recurrence,
    release_report,
    resolve,
    role_report,
    shared_proof_warnings,
    state_priority,
    summarize,
)
from .writer import (
    Edit,
    WriteError,
    accept,
    add_need,
    add_proof,
    add_role,
    attest,
    capture_source,
    link_variant_group,
    set_field,
    set_importance,
)

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


def _warrant(need: Need) -> str:
    """The warrant column: the strongest source kind, or 'opinion' when there is no source at all.

    A `primary` source names its person (`primary:who`); `secondary`/`assumption` show the kind. A
    need with any source is shown by that kind even if it is an opinion (only an assumption) — the
    opinion roll-up lives in the gap counts, this column shows the literal evidence tier.
    """
    strongest = need.strongest_kind  # the one source-strength ranking lives on the model
    if strongest is None:
        return "opinion"
    if strongest is SourceKind.PRIMARY:
        who = next((s.who for s in need.sources if s.kind is SourceKind.PRIMARY and s.who), None)
        return f"primary:{who}" if who else "primary"
    return strongest.value


def _provenance_counts(results: list[NeedResult]) -> dict[str, int]:
    """How many needs carry each evidence tier (primary/secondary/assumption/opinion)."""
    counts = {"primary": 0, "secondary": 0, "assumption": 0, "opinion": 0}
    for r in results:
        counts[_warrant(r.need).split(":", 1)[0]] += 1
    return counts


def _provenance_line(results: list[NeedResult]) -> str:
    """Per-role evidence mix — makes assumption-only needs (weak, but not sourceless) visible.

    The headline a PM wants is how many needs trace to a real user (primary), not just 'has any
    source'; a need resting only on an assumption is an opinion, shown here as its assumption tier.
    """
    counts = _provenance_counts(results)
    return "provenance: " + "  ·  ".join(f"{counts[k]} {k}" for k in counts)


def _summary_line(s: Summary) -> str:
    """The leading gap-count line: what needs attention, and overall coverage."""
    parts: list[str] = []
    if s.must_hole:
        parts.append(f"{s.must_hole} must-HOLE")
    if s.broken:
        parts.append(f"{s.broken} BROKEN")
    if s.unresolved:
        parts.append(f"{s.unresolved} UNRESOLVED")
    if s.pending:
        parts.append(f"{s.pending} PENDING")
    if s.hole - s.must_hole:
        parts.append(f"{s.hole - s.must_hole} HOLE")
    if s.opinion:
        parts.append(f"{s.opinion} opinion")
    gaps = "  ·  ".join(parts) if parts else "no gaps"
    return f"gaps: {gaps}    coverage {s.delivered}/{s.total} ({round(s.coverage * 100)}%)"


def _clip(text: str, width: int) -> str:
    """Fit text to width, breaking at a word boundary with an ellipsis, not mid-word (#39)."""
    if len(text) <= width:
        return text
    budget = width - 1  # leave room for the ellipsis
    cut = text[:budget]
    if text[budget] != " " and " " in cut:  # boundary lands mid-word → back up to last space
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def _grounds_cell(r: NeedResult) -> str:
    """The GROUNDS column as one aligned token: state, a `*` if declared, and n/n if proofs."""
    star = "*" if (r.declared and r.state is NeedState.DELIVERED) else ""
    nm = f" {r.delivered}/{r.total}" if r.total else ""
    return f"{_LABEL[r.state]}{star}{nm}"


def _marker(need: Need) -> str:
    """The 2-char left gutter: must beats flow when a need is both."""
    if need.must:
        return "!!"
    if need.children:
        return "⊟ "
    return "  "


def _render(results: list[NeedResult], wide: bool = False) -> str:
    if not results:
        return "  (no needs)"
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)

    # Fit every column to its widest content across the WHOLE board, so columns line up
    # the same in every role block. The need column takes whatever width is left.
    id_w = max([len("id"), *(len(r.need.id) for r in results)])
    grounds_w = max([len("grounds"), *(len(_grounds_cell(r)) for r in results)])
    warrant_w = max([len("warrant"), *(len(_warrant(r.need)) for r in results)])
    if wide:
        need_w = max([len("need"), *(len(r.need.text) for r in results)])
    else:
        cols = shutil.get_terminal_size(fallback=(100, 24)).columns
        need_w = max(24, cols - (id_w + grounds_w + warrant_w + 12))

    def row(marker: str, c_id: str, c_grounds: str, c_need: str, c_warrant: str) -> str:
        return (
            f"  {marker}  {c_id.ljust(id_w)}  {c_grounds.ljust(grounds_w)}  "
            f"{c_need.ljust(need_w)}  {c_warrant}"
        )

    total_w = 2 + 2 + 2 + id_w + 2 + grounds_w + 2 + need_w + 2 + warrant_w
    out: list[str] = [
        row("  ", "id", "grounds", "need", "warrant"),
        "  " + "─" * (total_w - 2),
        "  legend: !! must · ⊟ flow · * declared (no results) · "
        "grounds = test proof · warrant = user signal",
    ]
    for who in sorted(groups):
        rs = sorted(groups[who], key=state_priority)
        label = next((x.need.label for x in rs if x.need.label), None)
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "   ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        title = f"{who}" + (f" ({label})" if label else "")
        out.append(f"\n{title}    {head}")
        out.append(f"    {_provenance_line(rs)}\n")
        for r in rs:
            out.append(
                row(
                    _marker(r.need),
                    r.need.id,
                    _grounds_cell(r),
                    _clip(r.need.text, need_w),
                    _warrant(r.need),
                )
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


_COLUMNS: dict[str, tuple[str, Callable[[NeedResult], str]]] = {
    "id": ("id", lambda r: r.need.id),
    "state": ("state", lambda r: _LABEL[r.state]),
    "grounds": ("grounds", lambda r: f"{r.delivered}/{r.total}" if r.total else ""),
    "text": ("need", lambda r: r.need.text),
    "who": ("who", lambda r: r.need.who or ""),
    "role": ("role", lambda r: r.need.role or ""),
    "warrant": ("warrant", lambda r: _warrant(r.need)),
    "declared": (
        "declared",
        lambda r: "yes" if (r.declared and r.state is NeedState.DELIVERED) else "",
    ),
    "must": ("must", lambda r: "!!" if r.need.must else ""),
    "opinion": ("opinion", lambda r: "opinion" if r.need.is_opinion else ""),
    "goal": ("goal", lambda r: r.need.goal or ""),
    "release": ("release", lambda r: r.need.release or ""),
    "client": ("client", lambda r: r.need.client or ""),
}


def _render_columns(results: list[NeedResult], columns: list[str]) -> str:
    """A flat table of exactly the chosen columns — the board cut to the question asked (#40)."""
    rows = sorted(results, key=state_priority)
    cells = [[_COLUMNS[c][1](r) for c in columns] for r in rows]
    headers = [_COLUMNS[c][0] for c in columns]
    widths = [max([len(headers[i]), *(len(row[i]) for row in cells)]) for i in range(len(columns))]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    for row in cells:
        out.append("  ".join(row[i].ljust(widths[i]) for i in range(len(columns))))
    return "\n".join(out)


def _render_orphans(orphan_map: dict[str, list[str]]) -> str:
    """The reverse report: proof units that no need references."""
    total = sum(len(v) for v in orphan_map.values())
    out = [f"\norphan proofs (claimed by no need): {total}"]
    for name in sorted(orphan_map):
        for sid in orphan_map[name]:
            out.append(f"     {name}:{sid}")
    return "\n".join(out)


def _render_out_of_scope(results: list[NeedResult]) -> str:
    """Non-product needs (infra/NFR/internal): listed, not counted, never a HOLE (#48)."""
    out = [f"\nout of scope (not product — excluded from coverage): {len(results)}"]
    for r in sorted(results, key=lambda x: x.need.id):
        out.append(f"  {r.need.id:<12} {_LABEL[r.state]:<10} {r.need.text[:54]}")
    return "\n".join(out)


def _render_goals(goal_cov: list[tuple[Goal, Summary]], ungoaled: list[NeedResult]) -> str:
    """Per-goal coverage, plus the needs that serve no objective (#27)."""
    out = ["\ngoals (objectives needs trace up to):"]
    for goal, gsum in goal_cov:
        metric = f"  [{goal.metric}]" if goal.metric else ""
        pct = round(gsum.coverage * 100)
        out.append(f"  {goal.id:<12} {gsum.delivered}/{gsum.total} ({pct}%){metric}  {goal.text}")
    if ungoaled:
        ids = ", ".join(r.need.id for r in ungoaled)
        out.append(f"  ⚠ {len(ungoaled)} need(s) serve no goal: {ids}")
    return "\n".join(out)


def _render_releases(rel_cov: list[tuple[Release, Summary]]) -> str:
    """Per-release coverage, in ship order (#30)."""
    out = ["\nreleases (ship order):"]
    for rel, rsum in rel_cov:
        pct = round(rsum.coverage * 100)
        title = f"  {rel.text}" if rel.text else ""
        out.append(f"  {rel.id:<12} {rsum.delivered}/{rsum.total} ({pct}%){title}")
    return "\n".join(out)


def _render_roles(role_cov: list[tuple[Role, Summary]], unroled: list[NeedResult]) -> str:
    """The roster: coverage per declared role, orphan roles (0 needs), and unroled needs (#52)."""
    out = ["\nroles (the roster — who plays which function):"]
    for role, rsum in role_cov:
        if rsum.total:
            pct = round(rsum.coverage * 100)
            out.append(f"  {role.id:<12} {rsum.delivered}/{rsum.total} ({pct}%)  {role.text}")
        else:
            out.append(f"  {role.id:<12} —  (orphan role: no need plays it yet)  {role.text}")
    if unroled:
        ids = ", ".join(r.need.id for r in unroled)
        out.append(f"  ⚠ need(s) whose who plays no declared role: {ids}")
    return "\n".join(out)


def _render_handoffs(hos: list[Handoff]) -> str:
    """Derived cross-role journey: where a flow's ordered steps pass between roles (#52)."""
    out = [f"\nhandoffs (derived from ordered cross-role flows): {len(hos)}"]
    for h in hos:
        out.append(
            f"  {h.flow.id:<12} {h.from_role} → {h.to_role}    {h.from_need.id} → {h.to_need.id}"
        )
    return "\n".join(out)


def _render_recurrence(recs: list[Recurrence]) -> str:
    """Baselines shared across clients, most-shared first — the #32 recurrence view."""
    out = [f"\nrecurrence (needs shared across clients): {len(recs)}"]
    for rec in recs:
        who = f" — {', '.join(rec.clients)}" if rec.clients else ""
        out.append(
            f"  {rec.baseline.id:<12} {rec.count} client{'s' if rec.count != 1 else ''}{who}"
            f"    {rec.baseline.text[:60]}"
        )
    return "\n".join(out)


def _summary_payload(summary: Summary, orphan_map: dict[str, list[str]]) -> dict[str, object]:
    return {
        "total": summary.total,
        "delivered": summary.delivered,
        "pending": summary.pending,
        "hole": summary.hole,
        "must_hole": summary.must_hole,
        "broken": summary.broken,
        "unresolved": summary.unresolved,
        "opinion": summary.opinion,
        "coverage": round(summary.coverage, 4),
        "orphans": sum(len(v) for v in orphan_map.values()),
    }


def _need_payload(r: NeedResult) -> dict[str, object]:
    """One need's common fields — shared by the board and `show` so the two never drift."""
    need = r.need
    return {
        "id": need.id,
        "who": need.who,
        "role": need.role,
        "text": need.text,
        "must": need.must,
        "state": r.state.value,
        "grounds": r.state.value,
        "warrant": _warrant(need),
        "shape": ears_shape(need.text).value,
        "client": need.client,
        "variant_of": need.variant_of,
        "goal": need.goal,
        "release": need.release,
        "product": need.product,
        "draft": need.draft,
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


def _to_json(
    results: list[NeedResult],
    summary: Summary,
    orphan_map: dict[str, list[str]],
    recs: list[Recurrence],
    goal_cov: list[tuple[Goal, Summary]],
    ungoaled: list[NeedResult],
    rel_cov: list[tuple[Release, Summary]],
    role_cov: list[tuple[Role, Summary]],
    unroled: list[NeedResult],
    hos: list[Handoff],
) -> str:
    payload = {
        "summary": _summary_payload(summary, orphan_map),
        "orphans": orphan_map,
        "roles": [
            {
                "id": role.id,
                "text": role.text,
                "coverage": round(rsum.coverage, 4),
                "delivered": rsum.delivered,
                "total": rsum.total,
                "orphan": rsum.total == 0,
            }
            for role, rsum in role_cov
        ],
        "unroled": [r.need.id for r in unroled],
        "handoffs": [
            {
                "flow": h.flow.id,
                "from_role": h.from_role,
                "to_role": h.to_role,
                "from_need": h.from_need.id,
                "to_need": h.to_need.id,
            }
            for h in hos
        ],
        "releases": [
            {
                "id": rel.id,
                "text": rel.text,
                "coverage": round(rsum.coverage, 4),
                "delivered": rsum.delivered,
                "total": rsum.total,
            }
            for rel, rsum in rel_cov
        ],
        "recurrence": [
            {
                "baseline": rec.baseline.id,
                "text": rec.baseline.text,
                "count": rec.count,
                "clients": list(rec.clients),
            }
            for rec in recs
        ],
        "goals": [
            {
                "id": goal.id,
                "text": goal.text,
                "metric": goal.metric,
                "coverage": round(gsum.coverage, 4),
                "delivered": gsum.delivered,
                "total": gsum.total,
            }
            for goal, gsum in goal_cov
        ],
        "ungoaled": [r.need.id for r in ungoaled],
        "needs": [_need_payload(r) for r in results],
    }
    return json.dumps(payload, indent=2)


def _load_or_report(args: argparse.Namespace) -> tuple[Config, Model] | None:
    """Load config + the whole model, or print the error to stderr and return None."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return None
    try:
        cfg = Config.load(cfg_path)
        return cfg, load(cfg)
    except (ConfigError, LoaderError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return None


def _annotate_board_warnings(results: list[NeedResult], needs: list[Need]) -> None:
    """Append the cross-need hygiene warnings (shared proofs #45, seam coverage #44)."""
    shared = shared_proof_warnings(results)
    flow_orphans = flow_orphan_warnings(needs)
    for r in results:
        if r.need.id in shared:
            r.warnings.append(shared[r.need.id])
        if r.need.id in flow_orphans:
            r.warnings.append("belongs to no flow — seam not covered (#44)")


def _annotate_duplicate_warnings(
    results: list[NeedResult], needs: list[Need], threshold: float
) -> None:
    """Append a `possible duplicate of <id>` warning to each need in a candidate pair (#55)."""
    by_id = {r.need.id: r for r in results}
    for pair in duplicate_pairs(needs, threshold):
        msg_a = f"possible duplicate of {pair.b.id} ({pair.score:.2f}) — #55"
        msg_b = f"possible duplicate of {pair.a.id} ({pair.score:.2f}) — #55"
        if pair.a.id in by_id:
            by_id[pair.a.id].warnings.append(msg_a)
        if pair.b.id in by_id:
            by_id[pair.b.id].warnings.append(msg_b)


def _annotate_importance_warnings(results: list[NeedResult], cfg: Config) -> None:
    """Flag importance values off the rubric, or set long ago / never dated (#59)."""
    today = date.today()
    for r in results:
        imp = r.need.importance
        if imp is None:
            continue
        if cfg.importance_levels and imp not in cfg.importance_levels:
            allowed = ", ".join(str(n) for n in sorted(cfg.importance_levels))
            r.warnings.append(f"importance {imp} is off the declared scale ({allowed}) — #59")
            continue
        when = r.need.importance_set_at
        if when is None:
            r.warnings.append(
                "importance set but no revisit date (`set importance` stamps one) — #59"
            )
        elif cfg.importance_revisit_days is not None:
            try:
                days = (today - date.fromisoformat(when)).days
            except ValueError:
                days = None
            if days is not None and days > cfg.importance_revisit_days:
                r.warnings.append(
                    f"importance set {days}d ago (> {cfg.importance_revisit_days}d) — revisit (#59)"
                )


def _lint_errors(results: list[NeedResult]) -> list[str]:
    """Hard problems a lint gate fails on: a dangling proof, or a must-have with no evidence."""
    errors: list[str] = []
    for r in sorted(results, key=lambda x: x.need.id):
        if r.state is NeedState.BROKEN:
            errors.append(f"{r.need.id}: BROKEN proof — {'; '.join(r.detail)}")
        if r.need.must and r.need.is_opinion:
            errors.append(f"{r.need.id}: must-have is an opinion (no evidence)")
    return errors


def _cmd_lint(args: argparse.Namespace) -> int:
    """Gate the board: fail on hard problems (BROKEN, must-opinion); list hygiene warnings.

    The red-gate counterpart to `status` — so drift is a CI failure, not something you notice
    by eye. `--strict` also fails on any hygiene warning.
    """
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    _annotate_board_warnings(results, needs)
    _annotate_duplicate_warnings(results, needs, cfg.duplicate_threshold)
    by_id = {r.need.id: r for r in results}
    for g in variant_suggestions(needs, cfg.duplicate_threshold):
        others = ", ".join(m.id for m in g.members)
        for m in g.members:
            if m.id in by_id:
                by_id[m.id].warnings.append(
                    f"unlinked cross-client recurrence with {others} — set variant_of or "
                    f"not_variant_of ({g.score:.2f}) — #56"
                )
    if cfg.stale_after_days is not None:
        today = date.today()
        for r in results:
            age = evidence_age_days(r.need, today)
            if age is not None and age > cfg.stale_after_days:
                r.warnings.append(f"evidence is {age}d old (> {cfg.stale_after_days}d) — #58")
    for v in who_variants(needs, cfg.duplicate_threshold):
        whos = " / ".join(repr(w) for w in v.whos)
        for nid in v.need_ids:
            if nid in by_id:
                by_id[nid].warnings.append(
                    f"who may name the same person: {whos} (needs {', '.join(v.need_ids)}) — #61"
                )
    _annotate_importance_warnings(results, cfg)
    errors = _lint_errors(results)
    warnings = [
        (r.need.id, w) for r in sorted(results, key=lambda x: x.need.id) for w in r.warnings
    ]
    if args.json:
        print(
            json.dumps(
                {"errors": errors, "warnings": [{"id": i, "warning": w} for i, w in warnings]},
                indent=2,
            )
        )
    else:
        for e in errors:
            print(f"  ERROR  {e}")
        for nid, w in warnings:
            print(f"  warn   {nid}: {w}")
        print(f"lint: {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    # Draft needs (#60) are staged: kept off the counted board (and coverage, recurrence,
    # orphans) until promoted with `set <id> draft=false`, unless --include-drafts is passed.
    draft_count = sum(1 for n in needs if n.draft)
    if not args.include_drafts:
        needs = [n for n in needs if not n.draft]
    # Scoped coverage (#49): restrict the board + coverage to a subset, so the number people
    # act on (this client, this goal) isn't diluted by the whole mixed board.
    if args.client:
        needs = applicable_needs(needs, args.client)
    if args.goal:
        needs = [n for n in needs if n.goal == args.goal]
    if args.stale is not None:
        today = date.today()
        needs = [
            n
            for n in needs
            if (age := evidence_age_days(n, today)) is not None and age > args.stale
        ]
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    _annotate_board_warnings(results, needs)
    summary = summarize(results)
    orphan_map = orphans(needs, cfg.adapters)
    recs = recurrence(needs)
    goal_cov, ungoaled = goal_report(results, list(model.goals))
    rel_cov = release_report(results, list(model.releases))
    role_cov, unroled = role_report(results, list(model.roles))
    hos = handoffs(needs)

    if args.columns:
        bad = [c for c in args.columns if c not in _COLUMNS]
        if bad:
            print(
                f"prodc: unknown column(s) {', '.join(bad)} (available: {', '.join(_COLUMNS)})",
                file=sys.stderr,
            )
            return 2

    if args.json:
        print(
            _to_json(
                results,
                summary,
                orphan_map,
                recs,
                goal_cov,
                ungoaled,
                rel_cov,
                role_cov,
                unroled,
                hos,
            )
        )
    else:
        commit = _git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(_summary_line(summary))
        if draft_count and not args.include_drafts:
            print(f"drafts: {draft_count} staged (hidden — --include-drafts to show) (#60)")
        visible = [r for r in results if r.need.product]
        if args.only_must:
            visible = [r for r in visible if r.need.must]
        if args.columns:
            print(_render_columns(visible, args.columns))
            return _exit_code(args, summary, sum(len(v) for v in orphan_map.values()))
        print(_render(visible, wide=args.wide))
        out_of_scope = [r for r in results if not r.need.product]
        if out_of_scope:
            print(_render_out_of_scope(out_of_scope))
        if model.goals:
            print(_render_goals(goal_cov, ungoaled))
        if model.releases:
            print(_render_releases(rel_cov))
        if model.roles:
            print(_render_roles(role_cov, unroled))
        if hos:
            print(_render_handoffs(hos))
        if recs:
            print(_render_recurrence(recs))
        if orphan_map:
            print(_render_orphans(orphan_map))

    return _exit_code(args, summary, sum(len(v) for v in orphan_map.values()))


def _exit_code(args: argparse.Namespace, summary: Summary, orphan_total: int) -> int:
    """Gate: 0 unless a threshold is crossed; HOLE never fails.

    Default fails on any BROKEN; ``--max-dangling N`` tolerates N; ``--min-coverage F``
    fails when delivered/total < F; ``--max-orphans N`` fails above N unclaimed proofs;
    ``--strict`` fails on any opinion.
    """
    if args.max_dangling is not None:
        if summary.broken > args.max_dangling:
            return 1
    elif summary.broken:
        return 1
    if args.min_coverage is not None and summary.coverage < args.min_coverage:
        return 1
    if args.max_orphans is not None and orphan_total > args.max_orphans:
        return 1
    if args.strict and summary.opinion:
        return 1
    return 0


def _render_show(r: NeedResult, importance_label: str | None = None) -> str:
    """One need as a citable answer — the artifact you drop into a thread."""
    need = r.need
    who = (need.who + (f" ({need.label})" if need.label else "")) if need.who else "(unassigned)"
    who += f" — {need.role}" if need.role else ""
    nm = f"  {r.delivered}/{r.total}" if r.total else ""
    lines = [
        f"{need.id}{'  !!' if need.must else ''}{'  (draft)' if need.draft else ''}  {need.text}",
        f"  who: {who}",
        f"  grounds: {_LABEL[r.state]}{nm}    warrant: {_warrant(need)}",
        f"  shape: {ears_shape(need.text).value}",
    ]
    if need.importance is not None:
        label = f" ({importance_label})" if importance_label else ""
        seen = f", set {need.importance_set_at}" if need.importance_set_at else ""
        lines.append(f"  importance: {need.importance}{label}{seen}")
    if need.goal:
        lines.append(f"  goal: {need.goal}")
    if need.release:
        lines.append(f"  release: {need.release}")
    if need.claim:
        lines.append(f"  claim: {need.claim}")
    if need.attestation:
        a = need.attestation
        tag = " (AI)" if a.kind.value == "ai" else ""
        verdict = f" — {a.verdict}" if a.verdict else ""
        lines.append(f"  attested: {a.who}{tag} ({a.date}){verdict}")
        if a.comment:
            lines.append(f"    ↳ {a.comment}")
    elif need.proofs and r.state is NeedState.DELIVERED:
        lines.append("  attested: (none — proof link not reviewed, #13)")
    if need.sources:
        lines.append("  sources:")
        for s in need.sources:
            bits = [s.kind.value]
            bits += [
                f"{k}={v}"
                for k, v in (("who", s.who), ("date", s.date), ("locator", s.locator))
                if v
            ]
            line = "    - " + "  ".join(bits)
            lines.append(line + (f'  "{s.quote}"' if s.quote else ""))
    else:
        lines.append("  sources: (none — opinion)")
    if need.children:
        lines.append(f"  children: {', '.join(need.children)}")
    if need.seam:
        lines.append(f"  seam: {', '.join(need.seam)}")
    if need.proofs:
        lines.append("  proofs:")
        lines += [f"    - {d}" for d in r.detail]
    elif not need.children:
        lines.append("  proofs: (none — HOLE)")
    lines += [f"  ⚠ {w}" for w in r.warnings]
    return "\n".join(lines)


def _show_json(r: NeedResult) -> str:
    need = r.need
    payload = _need_payload(r)  # the shared core — never drifts from the board
    payload.update(
        {
            "label": need.label,
            "sources": [
                {
                    "kind": s.kind.value,
                    "who": s.who,
                    "date": s.date,
                    "quote": s.quote,
                    "locator": s.locator,
                }
                for s in need.sources
            ],
            "proofs": list(need.proofs),
            "children": list(need.children),
            "seam": list(need.seam),
        }
    )
    return json.dumps(payload, indent=2)


def _cmd_show(args: argparse.Namespace) -> int:
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    by_id = {r.need.id: r for r in resolve(needs, cfg.adapters, cfg.source_adapters)}
    r = by_id.get(args.need_id)
    if r is None:
        print(f"prodc: no need '{args.need_id}'", file=sys.stderr)
        return 2
    print(_show_json(r) if args.json else _render_show(r, cfg.importance_label(r.need.importance)))
    return 0


def _brief_open(results: list[NeedResult]) -> list[NeedResult]:
    """The meeting agenda: needs that are opinions (no evidence) or HOLEs (no proof),
    must-haves first, then by id."""
    open_ = [r for r in results if r.need.is_opinion or r.state is NeedState.HOLE]
    open_.sort(key=lambda r: (not r.need.must, r.need.id))
    return open_


def _render_brief(client: str, results: list[NeedResult]) -> str:
    open_ = _brief_open(results)
    out = [f"brief — {client}: {len(open_)} open question{'s' if len(open_) != 1 else ''}"]
    if not open_:
        out.append("  (nothing open — every applicable need has evidence and a proof)")
    for r in open_:
        bang = "!!" if r.need.must else "  "
        gaps = " · ".join(
            g
            for g in (
                "opinion" if r.need.is_opinion else "",
                "HOLE" if r.state is NeedState.HOLE else "",
            )
            if g
        )
        out.append(f"  {bang} {r.need.id:<12} [{gaps}]  {r.need.text}")
    return "\n".join(out)


def _brief_json(client: str, results: list[NeedResult]) -> str:
    open_ = _brief_open(results)
    return json.dumps(
        {
            "client": client,
            "open": [
                {
                    "id": r.need.id,
                    "text": r.need.text,
                    "must": r.need.must,
                    "opinion": r.need.is_opinion,
                    "hole": r.state is NeedState.HOLE,
                    "warrant": _warrant(r.need),
                }
                for r in open_
            ],
        },
        indent=2,
    )


def _cmd_brief(args: argparse.Namespace) -> int:
    """Pre-meeting agenda for one client: its applicable needs that lack evidence or proof."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    if not any(n.client == args.client for n in needs):
        # shared baselines apply to everyone, so an unknown client would otherwise
        # silently return a baselines-only brief — guard the likely typo instead.
        print(f"prodc: no needs for client '{args.client}'", file=sys.stderr)
        return 2
    scoped = applicable_needs(needs, args.client)
    results = resolve(scoped, cfg.adapters, cfg.source_adapters)
    print(_brief_json(args.client, results) if args.json else _render_brief(args.client, results))
    return 0


def _importance_cell(need: Need) -> str:
    """The importance column; a value entered by a weak-warrant author is flagged a guess."""
    if need.importance is None:
        return ""
    # weak = no external evidence (only an assumption, or nothing) — the author is guessing
    weak = need.is_opinion
    return f"imp={need.importance}{' (guess)' if weak else ''}"


def _render_plan(results: list[NeedResult], recurrence_counts: dict[str, int]) -> str:
    ranked = rank(results, recurrence_counts)
    out = ["plan — ranked backlog (must + state + evidence + recurrence, importance refines)"]
    for i, r in enumerate(ranked, 1):
        bang = "!!" if r.need.must else "  "
        imp = _importance_cell(r.need)
        out.append(
            f"  {i:>3}. {bang} {r.need.id:<12} {_LABEL[r.state]:<10} "
            f"{_warrant(r.need):<16} {imp:<12} {r.need.text[:48]}"
        )
    return "\n".join(out)


def _plan_json(results: list[NeedResult], recurrence_counts: dict[str, int]) -> str:
    ranked = rank(results, recurrence_counts)
    return json.dumps(
        {
            "plan": [
                {
                    "rank": i,
                    "id": r.need.id,
                    "text": r.need.text,
                    "must": r.need.must,
                    "state": r.state.value,
                    "warrant": _warrant(r.need),
                    "recurrence": recurrence_counts.get(r.need.id, 0),
                    "importance": r.need.importance,
                    "importance_is_guess": (
                        r.need.importance is not None and r.need.is_opinion
                    ),
                }
                for i, r in enumerate(ranked, 1)
            ]
        },
        indent=2,
    )


def _cmd_plan(args: argparse.Namespace) -> int:
    """Emit a ranked backlog from recorded inputs — must+state+evidence, importance refines."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    if not args.include_drafts:
        needs = [n for n in needs if not n.draft]  # drafts aren't backlog until promoted (#60)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    recurrence_counts = {rec.baseline.id: rec.count for rec in recurrence(needs)}
    print(
        _plan_json(results, recurrence_counts)
        if args.json
        else _render_plan(results, recurrence_counts)
    )
    return 0


def _render_argument(model: Model, defects: list[str]) -> str:
    out = [f"argument — GSN graph: {len(model.argument)} node(s), {len(defects)} defect(s)"]
    for node in model.argument:
        links = ""
        if node.supported_by:
            links += f"  ←{','.join(node.supported_by)}"
        if node.in_context_of:
            links += f"  ⊙{','.join(node.in_context_of)}"
        about = f"  [{node.about}]" if node.about else ""
        out.append(f"  {node.id:<12} {node.kind.value:<13} {node.text[:44]}{about}{links}")
    for d in defects:
        out.append(f"  ⚠ {d}")
    return "\n".join(out)


def _argument_json(model: Model, defects: list[str]) -> str:
    return json.dumps(
        {
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind.value,
                    "text": n.text,
                    "supported_by": list(n.supported_by),
                    "in_context_of": list(n.in_context_of),
                    "about": n.about,
                }
                for n in model.argument
            ],
            "defects": defects,
        },
        indent=2,
    )


def _emit_edit(edit: Edit, dry_run: bool, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"file": edit.path.name, "dry_run": dry_run, "diff": edit.diff}, indent=2))
    else:
        print(f"{'would edit' if dry_run else 'edited'} {edit.path.name}")
        print(edit.diff, end="")
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    """Set or append one field on an existing need, validated against the loader."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        # `set importance=…` goes through its own path so the value is checked against the
        # rubric and `importance_set_at` is stamped in the same edit (#59).
        key, sep, raw = args.assignment.partition("=")
        if sep and "+" not in key and key.strip() == "importance":
            level = cfg.resolve_importance(raw)
            edit = set_importance(
                cfg,
                args.need_id,
                level,
                date.today().isoformat(),
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        else:
            edit = set_field(
                cfg,
                args.need_id,
                args.assignment,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_add(args: argparse.Namespace) -> int:
    """Create a new need (with an assumption/secondary provenance source) or declare a role (#52)."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    if args.noun == "role":
        try:
            cfg = Config.load(cfg_path)
            edit = add_role(
                cfg,
                args.need_id,
                args.text,
                file=args.file,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        except (ConfigError, LoaderError, WriteError) as exc:
            print(f"prodc: {exc}", file=sys.stderr)
            return 2
        return _emit_edit(edit, args.dry_run, args.json)
    if args.who is None:
        print("prodc: add need requires --who (the author recorded on the source)", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        if not args.no_dupe_check:
            hits = matches_for(
                args.text, list(load(cfg).needs), cfg.duplicate_threshold, exclude_id=args.need_id
            )
            for need, score in hits:
                print(
                    f"prodc: possible duplicate of {need.id} ({score:.2f}): {need.text}",
                    file=sys.stderr,
                )
            if hits and args.strict_dupes:
                print(
                    "prodc: refusing to add — --strict-dupes and a possible duplicate exists",
                    file=sys.stderr,
                )
                return 2
        edit = add_need(
            cfg,
            args.need_id,
            args.text,
            who=args.who,
            kind=args.kind,
            file=args.file,
            draft=args.draft or cfg.default_draft,
            expect_sha=args.expect_sha,
            dry_run=args.dry_run,
        )
    except (ConfigError, LoaderError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_attest(args: argparse.Namespace) -> int:
    """Record a human or AI review that a need's proofs establish its claim."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        edit = attest(
            cfg,
            args.need_id,
            who=args.by,
            date=args.date,
            kind="ai" if args.ai else "human",
            verdict=args.verdict,
            comment=args.comment,
            expect_sha=args.expect_sha,
            dry_run=args.dry_run,
        )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_accept(args: argparse.Namespace) -> int:
    """Record (or --revoke) a human acceptance pass on a need."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        edit = accept(
            cfg,
            args.need_id,
            who=args.who,
            date=args.date,
            revoke=args.revoke,
            expect_sha=args.expect_sha,
            dry_run=args.dry_run,
        )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_capture(args: argparse.Namespace) -> int:
    """Append a Source to an existing need (capture evidence)."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        edit = capture_source(
            cfg,
            args.need_id,
            kind=args.kind,
            who=args.who,
            date=args.date,
            quote=args.quote,
            locator=args.locator,
            observed_at=args.observed_at or date.today().isoformat(),
            expect_sha=args.expect_sha,
            dry_run=args.dry_run,
        )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_argument(args: argparse.Namespace) -> int:
    """Show the GSN assurance graph and its defects (unsupported claim, dangling assumption)."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    _cfg, model = loaded
    defects = argument_defects(list(model.argument))
    print(_argument_json(model, defects) if args.json else _render_argument(model, defects))
    return 1 if (args.strict and defects) else 0


@dataclass(frozen=True)
class _RepoRow:
    """One repo's line in the portfolio roll-up."""

    repo: str
    delivered: int
    total: int
    must_hole: int
    broken: int
    coverage: float
    provenance: dict[str, int]
    error: str | None = None


def _repo_row(config_path: str) -> _RepoRow:
    p = Path(config_path)
    name = p.parent.name or str(p)
    try:
        cfg = Config.load(p)
        needs = list(load(cfg).needs)
    except (ConfigError, LoaderError, OSError) as exc:
        return _RepoRow(name, 0, 0, 0, 0, 0.0, {}, error=str(exc))
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    s = summarize(results)
    return _RepoRow(
        repo=cfg.root.name,
        delivered=s.delivered,
        total=s.total,
        must_hole=s.must_hole,
        broken=s.broken,
        coverage=round(s.coverage, 4),
        provenance=_provenance_counts(results),
    )


def _render_portfolio(rows: list[_RepoRow]) -> str:
    out = [f"  {'repo':<18} {'cov':>4}  {'must-HOLE':>9}  {'BROKEN':>6}   prov prim/sec/asm/op"]
    for row in rows:
        if row.error is not None:
            out.append(f"  {row.repo:<18} error: {row.error}")
            continue
        p = row.provenance
        prov = f"{p['primary']}/{p['secondary']}/{p['assumption']}/{p['opinion']}"
        cov = f"{round(row.coverage * 100)}%"
        out.append(f"  {row.repo:<18} {cov:>4}  {row.must_hole:>9}  {row.broken:>6}   {prov}")
    return "\n".join(out)


def _cmd_portfolio(args: argparse.Namespace) -> int:
    """Roll up many repos into one scoreboard — coverage, must-HOLEs, provenance per repo."""
    rows = [_repo_row(path) for path in args.configs]
    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        print(_render_portfolio(rows))
    return 2 if any(r.error is not None for r in rows) else 0


def _cmd_diff(args: argparse.Namespace) -> int:
    """Diff the current board against a prior `status --json` snapshot."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    current = {r.need.id: r.state.value for r in resolve(needs, cfg.adapters, cfg.source_adapters)}

    snap = Path(args.snapshot)
    try:
        payload: object = json.loads(snap.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"prodc: cannot read snapshot {snap}: {exc}", file=sys.stderr)
        return 2
    raw_needs = (
        cast("dict[str, object]", payload).get("needs") if isinstance(payload, dict) else None
    )
    old: dict[str, str] = {}
    for n in cast("list[object]", raw_needs) if isinstance(raw_needs, list) else []:
        if isinstance(n, dict):
            entry = cast("dict[str, object]", n)
            nid, st = entry.get("id"), entry.get("state")
            if isinstance(nid, str) and isinstance(st, str):
                old[nid] = st

    new = {i: current[i] for i in sorted(current.keys() - old.keys())}
    removed = sorted(old.keys() - current.keys())
    changed = {
        i: [old[i], current[i]] for i in sorted(old.keys() & current.keys()) if old[i] != current[i]
    }
    if args.json:
        print(json.dumps({"new": new, "removed": removed, "changed": changed}, indent=2))
        return 0
    if not (new or removed or changed):
        print("no changes since snapshot")
        return 0
    out: list[str] = []
    for i, st in new.items():
        out.append(f"  new      {i:<10} ({st})")
    for i in removed:
        out.append(f"  removed  {i}")
    for i, (was, now) in changed.items():
        out.append(f"  changed  {i:<10} {was} → {now}")
    print("\n".join(out))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Render the board as a readable markdown document — a file a PM can read, share, or print."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    if args.client:
        scoped = applicable_needs(list(model.needs), args.client)
        model = Model(
            needs=tuple(scoped),
            goals=model.goals,
            releases=model.releases,
            roles=model.roles,
            argument=model.argument,
        )
    text = render_markdown(cfg, model, client=args.client, rev=_git_rev(cfg.root))
    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote report to {dest}")
    else:
        print(text)
    return 0


def _cmd_agent(args: argparse.Namespace) -> int:
    """Print prodc's agent playbook, or write it into the project.

    The playbook ships with prodc, so `prodc agent >> AGENTS.md` (or `--write`) drops the
    current, versioned guidance into a user's repo where their coding agent reads it — the agent
    then runs prodc as the project's PM. It improves when prodc improves; nobody hand-copies it.
    """
    text = importlib.resources.files("prodc").joinpath("agent.md").read_text(encoding="utf-8")
    if args.write:
        dest = Path(args.write)
        if dest.exists() and not args.force:
            print(f"prodc: {dest} already exists (use --force to overwrite)", file=sys.stderr)
            return 2
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote prodc agent playbook to {dest}")
        return 0
    print(text, end="")
    return 0


def _git_rev(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if ref.startswith("ref:"):
        target = root / ".git" / ref[4:].strip()
        try:
            return target.read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return None
    return ref[:7]


def _cmd_suggest(args: argparse.Namespace) -> int:
    """Propose candidate proof locators for HOLE needs from the adapters' inventories (#54)."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    if args.need_id:
        results = [r for r in results if r.need.id == args.need_id]
        if not results:
            print(f"prodc: no need '{args.need_id}'", file=sys.stderr)
            return 2
    suggestions = proof_suggestions(
        results, cfg.adapters, min_score=args.min_score, top=args.top, kind=args.kind
    )
    if args.apply:
        return _apply_suggestions(cfg, suggestions, args)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "need": s.need.id,
                        "adapter": s.adapter,
                        "locator": s.locator,
                        "score": round(s.score, 4),
                    }
                    for s in suggestions
                ],
                indent=2,
            )
        )
    else:
        last = None
        for s in suggestions:
            if s.need.id != last:
                print(f"{s.need.id}: {s.need.text}")
                last = s.need.id
            print(f"    {s.score:.2f}  {s.locator}")
        print(f"suggest: {len(suggestions)} candidate(s) at min-score {args.min_score:.2f}")
    return 0


def _apply_suggestions(
    cfg: Config, suggestions: list[ProofSuggestion], args: argparse.Namespace
) -> int:
    """Write the single best suggestion per need as a proof, printing each need's diff (#54).

    ``suggestions`` is already ranked best-first within each need, so the first seen per need id
    is its top candidate. Each need is one single-file, reload-validated edit (:func:`add_proof`),
    applied in id order; a write that the loader rejects aborts with a non-zero exit.
    """
    best: dict[str, ProofSuggestion] = {}
    for s in suggestions:
        best.setdefault(s.need.id, s)
    applied: list[tuple[ProofSuggestion, Edit]] = []
    for nid in sorted(best):
        s = best[nid]
        try:
            edit = add_proof(cfg, nid, s.locator, dry_run=args.dry_run)
        except WriteError as exc:
            print(f"prodc: {exc}", file=sys.stderr)
            return 2
        applied.append((s, edit))
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "need": s.need.id,
                        "locator": s.locator,
                        "score": round(s.score, 4),
                        "file": edit.path.name,
                        "dry_run": args.dry_run,
                        "diff": edit.diff,
                    }
                    for s, edit in applied
                ],
                indent=2,
            )
        )
    else:
        verb = "would write" if args.dry_run else "wrote"
        for s, edit in applied:
            print(f"{verb} {s.locator} → {s.need.id} ({s.score:.2f}) in {edit.path.name}")
            print(edit.diff, end="")
        print(f"suggest --apply: {verb} {len(applied)} proof(s) at min-score {args.min_score:.2f}")
    return 0


def _cmd_recurrence(args: argparse.Namespace) -> int:
    """Show baselines shared across clients; `--suggest` proposes unlinked variant groups (#56)."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    if args.suggest:
        threshold = args.threshold if args.threshold is not None else cfg.duplicate_threshold
        groups = variant_suggestions(needs, threshold)
        if args.apply:
            return _apply_recurrence(cfg, groups, args)
        if args.json:
            print(json.dumps([_variant_payload(g) for g in groups], indent=2))
        else:
            for g in groups:
                clients = ", ".join(sorted({m.client for m in g.members if m.client}))
                print(f"  {g.score:.2f}  {len(g.members)} needs across {clients}")
                for m in g.members:
                    print(f"        {m.id} ({m.client}): {m.text}")
            print(f"suggest: {len(groups)} unlinked variant group(s) at threshold {threshold:.2f}")
        return 0
    recs = recurrence(needs)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "baseline": r.baseline.id,
                        "text": r.baseline.text,
                        "count": r.count,
                        "clients": list(r.clients),
                    }
                    for r in recs
                ],
                indent=2,
            )
        )
    else:
        for r in recs:
            print(f"  {r.count}x  {r.baseline.id}: {r.baseline.text}  [{', '.join(r.clients)}]")
        print(f"recurrence: {len(recs)} shared baseline(s)")
    return 0


def _baseline_text(g: VariantGroup) -> str:
    """The text for a created baseline: the highest-importance member, ties broken by id."""
    chosen = sorted(g.members, key=lambda m: (-(m.importance or 0), m.id))[0]
    return chosen.text


def _apply_recurrence(cfg: Config, groups: list[VariantGroup], args: argparse.Namespace) -> int:
    """Link the top recurrence group to a newly created shared baseline (#56), transactionally.

    A suggested group is always cross-client (the matcher excludes client-less needs), so there
    is never a baseline to reuse — `--apply` creates one, which needs `--baseline-id` and `--file`.
    It links the single highest-scoring group per run (one id names one baseline); any remaining
    groups are reported as still unlinked, to rerun. `--dry-run` previews the diffs without writing.
    """
    if not groups:
        print("recurrence --apply: no unlinked groups to link")
        return 0
    if not args.baseline_id or not args.file:
        print(
            "prodc: recurrence --apply needs --baseline-id and --file (the baseline to create)",
            file=sys.stderr,
        )
        return 2
    group = groups[0]  # highest score first (variant_suggestions sorts by -score)
    try:
        edits = link_variant_group(
            cfg,
            member_ids=[m.id for m in group.members],
            baseline_id=args.baseline_id,
            create_baseline=True,
            baseline_text=_baseline_text(group),
            baseline_file=args.file,
            dry_run=args.dry_run,
        )
    except WriteError as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    verb = "would link" if args.dry_run else "linked"
    if args.json:
        print(
            json.dumps(
                {
                    "baseline": args.baseline_id,
                    "members": [m.id for m in group.members],
                    "dry_run": args.dry_run,
                    "remaining_groups": len(groups) - 1,
                    "edits": [{"file": e.path.name, "diff": e.diff} for e in edits],
                },
                indent=2,
            )
        )
    else:
        members = ", ".join(m.id for m in group.members)
        print(f"{verb} {members} → baseline {args.baseline_id} (in {args.file})")
        for e in edits:
            print(e.diff, end="")
        if len(groups) > 1:
            print(f"recurrence --apply: {len(groups) - 1} more group(s) unlinked — rerun to link")
    return 0


def _variant_payload(g: VariantGroup) -> dict[str, object]:
    return {
        "score": round(g.score, 4),
        "members": [{"id": m.id, "client": m.client, "text": m.text} for m in g.members],
    }


def _cmd_dupes(args: argparse.Namespace) -> int:
    """List candidate duplicate need pairs, ranked by text similarity (#55)."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    threshold = args.threshold if args.threshold is not None else cfg.duplicate_threshold
    pairs = duplicate_pairs(list(model.needs), threshold)
    if args.json:
        print(
            json.dumps(
                [_dup_payload(p) for p in pairs],
                indent=2,
            )
        )
    else:
        for p in pairs:
            scope = " [same client+goal]" if p.same_scope else ""
            print(f"  {p.score:.2f}  {p.a.id} ~ {p.b.id}{scope}")
            print(f"        {p.a.id}: {p.a.text}")
            print(f"        {p.b.id}: {p.b.text}")
        print(f"dupes: {len(pairs)} candidate pair(s) at threshold {threshold:.2f}")
    return 0


def _dup_payload(p: DupPair) -> dict[str, object]:
    return {
        "a": p.a.id,
        "b": p.b.id,
        "score": round(p.score, 4),
        "same_scope": p.same_scope,
        "a_text": p.a.text,
        "b_text": p.b.text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prodc", description="Product management as code.")
    parser.add_argument("--version", action="version", version=f"prodc {__version__}")
    parser.add_argument(
        "-C",
        "--chdir",
        metavar="DIR",
        default=None,
        help="run as if prodc was started in DIR (like `terraform -chdir`); must precede the command",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status", help="show the needs board")
    st.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    st.add_argument("--json", action="store_true", help="machine-readable output")
    st.add_argument("--strict", action="store_true", help="also exit 1 on opinions")
    st.add_argument("--wide", action="store_true", help="never truncate the need text")
    st.add_argument(
        "--client",
        default=None,
        metavar="ID",
        help="scope the board + coverage to one client (its variants + baselines)",
    )
    st.add_argument(
        "--goal",
        default=None,
        metavar="ID",
        help="scope the board + coverage to the needs serving one goal",
    )
    st.add_argument(
        "--columns",
        default=None,
        type=lambda s: [c.strip() for c in s.split(",")],
        metavar="COLS",
        help="flat table of just these columns, e.g. id,state,text,warrant",
    )
    st.add_argument("--only-must", action="store_true", help="show only must-have needs")
    st.add_argument(
        "--include-drafts",
        action="store_true",
        help="include draft (staged) needs in the board and coverage (#60)",
    )
    st.add_argument(
        "--stale",
        type=int,
        default=None,
        metavar="DAYS",
        help="show only needs whose newest evidence (observed_at) is older than DAYS (#58)",
    )
    st.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        metavar="FRAC",
        help="gate: exit 1 if delivered/total < FRAC (0..1)",
    )
    st.add_argument(
        "--max-dangling",
        type=int,
        default=None,
        metavar="N",
        help="gate: tolerate up to N broken locators instead of failing on any",
    )
    st.add_argument(
        "--max-orphans",
        type=int,
        default=None,
        metavar="N",
        help="gate: exit 1 if more than N proof scenarios are claimed by no need",
    )
    st.set_defaults(func=_cmd_status)

    ln = sub.add_parser("lint", help="gate the board: fail on BROKEN proofs and must-opinions")
    ln.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ln.add_argument("--json", action="store_true", help="machine-readable output")
    ln.add_argument("--strict", action="store_true", help="also fail on any hygiene warning")
    ln.set_defaults(func=_cmd_lint)

    sh = sub.add_parser("show", help="show one need as a citable answer")
    sh.add_argument("need_id", help="the need id to show, e.g. N-1")
    sh.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    sh.add_argument("--json", action="store_true", help="machine-readable output")
    sh.set_defaults(func=_cmd_show)

    br = sub.add_parser("brief", help="pre-meeting agenda for one client: open opinions and HOLEs")
    br.add_argument("client", help="the client/variant id to brief, e.g. acme")
    br.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    br.add_argument("--json", action="store_true", help="machine-readable output")
    br.set_defaults(func=_cmd_brief)

    pl = sub.add_parser("plan", help="ranked backlog from must + state + evidence (+ importance)")
    pl.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    pl.add_argument("--json", action="store_true", help="machine-readable output")
    pl.add_argument(
        "--include-drafts", action="store_true", help="include draft (staged) needs (#60)"
    )
    pl.set_defaults(func=_cmd_plan)

    ar = sub.add_parser("argument", help="show the GSN assurance graph and its defects")
    ar.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ar.add_argument("--json", action="store_true", help="machine-readable output")
    ar.add_argument("--strict", action="store_true", help="exit 1 if the graph has any defect")
    ar.set_defaults(func=_cmd_argument)

    st2 = sub.add_parser("set", help="set or append one field on a need (writes YAML)")
    st2.add_argument("need_id", help="the need id to edit, e.g. N-1")
    st2.add_argument("assignment", help="key=value, or key+=value to append (proofs/children)")
    st2.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    st2.add_argument("--json", action="store_true", help="machine-readable output")
    st2.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    st2.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    st2.set_defaults(func=_cmd_set)

    ad = sub.add_parser(
        "add", help="create a new agent-authored need, or declare a role (writes YAML)"
    )
    ad.add_argument("noun", choices=["need", "role"], help="what to add (need or role)")
    ad.add_argument("need_id", help="the new need's id (or role id for `add role`), e.g. N-9")
    ad.add_argument("--text", required=True, help="the need text (or the role description)")
    ad.add_argument(
        "--who",
        default=None,
        help="need only: the author (recorded on the provenance source); required for `add need`",
    )
    ad.add_argument(
        "--kind",
        choices=["assumption", "secondary", "internal", "proxy"],
        default="assumption",
        help="need only: provenance source kind — assumption (default) or secondary; never "
        "primary for an agent (internal/proxy accepted as aliases for assumption)",
    )
    ad.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="prodc file to write into, relative to the config (must match a glob)",
    )
    ad.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ad.add_argument("--json", action="store_true", help="machine-readable output")
    ad.add_argument(
        "--strict-dupes",
        action="store_true",
        help="refuse to add if a possible duplicate exists (#55)",
    )
    ad.add_argument(
        "--no-dupe-check", action="store_true", help="skip the duplicate check entirely (#55)"
    )
    ad.add_argument(
        "--draft",
        action="store_true",
        help="stage as a draft: loads but stays off the counted board until promoted (#60)",
    )
    ad.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    ad.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    ad.set_defaults(func=_cmd_add)

    cp = sub.add_parser("capture", help="append a source (evidence) to an existing need")
    cp.add_argument("need_id", help="the need id to add evidence to")
    cp.add_argument(
        "--kind",
        required=True,
        choices=["primary", "secondary", "assumption", "interview", "artifact", "proxy", "internal"],
        help="source kind, strongest first: primary > secondary > assumption "
        "(interview/artifact/proxy/internal accepted as aliases)",
    )
    cp.add_argument("--who", default=None, help="the person the evidence came from")
    cp.add_argument("--date", default=None, help="when (ISO, e.g. 2026-10-05)")
    cp.add_argument("--quote", default=None, help="a verbatim quote (for a primary source)")
    cp.add_argument("--locator", default=None, help="a source locator (for a secondary source)")
    cp.add_argument(
        "--observed-at",
        default=None,
        metavar="ISO",
        help="when this evidence was recorded/refreshed (default: today) (#58)",
    )
    cp.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    cp.add_argument("--json", action="store_true", help="machine-readable output")
    cp.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    cp.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    cp.set_defaults(func=_cmd_capture)

    at = sub.add_parser("attest", help="record a human or AI review of a need's warrant (#13)")
    at.add_argument("need_id", help="the need id being attested")
    at.add_argument("--by", required=True, help="who reviewed it — a person's name or a model id")
    at.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-05)")
    at.add_argument("--ai", action="store_true", help="the reviewer is an AI model, not a human")
    at.add_argument(
        "--verdict", default=None, help="the reviewer's conclusion, e.g. pass/concerns/fail"
    )
    at.add_argument("--comment", default=None, help="the review's feedback, kept on the record")
    at.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    at.add_argument("--json", action="store_true", help="machine-readable output")
    at.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    at.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    at.set_defaults(func=_cmd_attest)

    ac = sub.add_parser("accept", help="record a human acceptance pass (accept proof) on a need")
    ac.add_argument("need_id", help="the need id that was accepted")
    ac.add_argument("--who", required=True, help="who accepted it")
    ac.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-05)")
    ac.add_argument("--revoke", action="store_true", help="remove this accept proof instead")
    ac.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ac.add_argument("--json", action="store_true", help="machine-readable output")
    ac.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    ac.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    ac.set_defaults(func=_cmd_accept)

    pf = sub.add_parser("portfolio", help="roll up many repos into one scoreboard")
    pf.add_argument("configs", nargs="+", metavar="PRODC_TOML", help="one or more prodc.toml paths")
    pf.add_argument("--json", action="store_true", help="machine-readable output")
    pf.set_defaults(func=_cmd_portfolio)

    rc = sub.add_parser(
        "recurrence", help="baselines shared across clients; --suggest proposes unlinked groups"
    )
    rc.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    rc.add_argument("--json", action="store_true", help="machine-readable output")
    rc.add_argument(
        "--suggest",
        action="store_true",
        help="propose unlinked cross-client needs that could share a baseline (#56)",
    )
    rc.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="FRAC",
        help="similarity for --suggest (0..1); overrides [lint].duplicate_threshold",
    )
    rc.add_argument(
        "--apply",
        action="store_true",
        help="with --suggest: link each group to a shared baseline (reuses a client-less "
        "member, or creates one with --baseline-id/--file) (#56)",
    )
    rc.add_argument(
        "--baseline-id",
        default=None,
        metavar="ID",
        help="id for a baseline to create when a group has no client-less member",
    )
    rc.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help="file to write a created baseline into (must match a [prodc].needs glob)",
    )
    rc.add_argument(
        "--dry-run", action="store_true", help="with --apply: validate and show diffs, don't write"
    )
    rc.set_defaults(func=_cmd_recurrence)

    sg = sub.add_parser(
        "suggest", help="propose candidate proofs for HOLE needs from adapter inventories (#54)"
    )
    sg.add_argument("need_id", nargs="?", default=None, help="only this need (default: all HOLEs)")
    sg.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    sg.add_argument("--json", action="store_true", help="machine-readable output")
    sg.add_argument(
        "--min-score",
        type=float,
        default=0.3,
        metavar="FRAC",
        help="minimum text similarity to suggest (0..1, default 0.3)",
    )
    sg.add_argument("--top", type=int, default=3, metavar="N", help="max suggestions per need")
    sg.add_argument(
        "--kind", default=None, metavar="ADAPTER", help="only suggest from this adapter name"
    )
    sg.add_argument(
        "--apply",
        action="store_true",
        help="write the best suggestion per need as a proof (#54); honours --min-score",
    )
    sg.add_argument(
        "--dry-run",
        action="store_true",
        help="with --apply: validate and show the diff, don't write",
    )
    sg.set_defaults(func=_cmd_suggest)

    du = sub.add_parser("dupes", help="list candidate duplicate need pairs by text similarity")
    du.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    du.add_argument("--json", action="store_true", help="machine-readable output")
    du.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="FRAC",
        help="similarity to flag (0..1); overrides [lint].duplicate_threshold",
    )
    du.set_defaults(func=_cmd_dupes)

    rp = sub.add_parser(
        "report", help="render the board as a readable markdown document (for a PM to read/share)"
    )
    rp.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    rp.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="PATH",
        help="write the report to PATH (e.g. status.md) instead of stdout",
    )
    rp.add_argument(
        "--client", default=None, metavar="ID", help="scope the report to one client (as `status`)"
    )
    rp.set_defaults(func=_cmd_report)

    ag = sub.add_parser(
        "agent",
        help="print prodc's agent playbook (teach a coding agent to run prodc as the project's PM)",
    )
    ag.add_argument(
        "--write",
        default=None,
        metavar="PATH",
        help="write the playbook to PATH instead of stdout (e.g. AGENTS.md)",
    )
    ag.add_argument("--force", action="store_true", help="overwrite PATH if it already exists")
    ag.set_defaults(func=_cmd_agent)

    df = sub.add_parser(
        "diff", help="diff the current board against a prior status --json snapshot"
    )
    df.add_argument("snapshot", help="path to a saved `prodc status --json` file")
    df.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    df.add_argument("--json", action="store_true", help="machine-readable output")
    df.set_defaults(func=_cmd_diff)

    args = parser.parse_args(argv)
    if args.chdir is not None:
        try:
            os.chdir(args.chdir)
        except OSError as exc:
            print(f"prodc: cannot chdir to {args.chdir}: {exc}", file=sys.stderr)
            return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
