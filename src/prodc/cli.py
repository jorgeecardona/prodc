"""``prodc`` command line: one verb, ``status`` — the board.

Prints the gap between needs and what the test suite proves, sorted by what needs
attention first. Exit 1 on a BROKEN proof; ``--strict`` also on an opinion. A HOLE
never fails — it is the honest gap you want people to keep writing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from . import __version__
from .config import Config, ConfigError
from .loader import LoaderError, load
from .model import Goal, Model, Need, NeedResult, NeedState, Release, SourceKind, ears_shape
from .status import (
    Recurrence,
    Summary,
    applicable_needs,
    argument_defects,
    goal_report,
    orphans,
    rank,
    recurrence,
    release_report,
    resolve,
    shared_proof_warnings,
    state_priority,
    summarize,
)
from .writer import Edit, WriteError, add_need, capture_source, set_field

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


def _warrant(need: Need) -> str:
    """The warrant column: the strongest source kind, or 'opinion' when unsourced."""
    strongest = need.strongest_kind  # the one source-strength ranking lives on the model
    if strongest is None:
        return "opinion"
    if strongest is SourceKind.INTERVIEW:
        who = next((s.who for s in need.sources if s.kind is SourceKind.INTERVIEW and s.who), None)
        return f"interview:{who}" if who else "interview"
    return strongest.value


def _provenance_counts(results: list[NeedResult]) -> dict[str, int]:
    """How many needs carry each warrant strength (interview/artifact/internal/opinion)."""
    counts = {"interview": 0, "artifact": 0, "proxy": 0, "internal": 0, "opinion": 0}
    for r in results:
        counts[_warrant(r.need).split(":", 1)[0]] += 1
    return counts


def _provenance_line(results: list[NeedResult]) -> str:
    """Per-persona provenance mix — makes internal-only ('0 OPINION' but unvalidated) visible.

    OPINION (no source) stays distinct from a weak INTERNAL source; the headline a PM
    wants is how many needs trace to a real user (interview), not just 'has any source'.
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


def _render(results: list[NeedResult]) -> str:
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)

    # Size the need column to the terminal; ~54 cols go to the fixed id/state/nm
    # prefix and the warrant suffix. Falls back to 100 cols when there is no tty.
    width = max(30, shutil.get_terminal_size(fallback=(100, 24)).columns - 54)

    out: list[str] = []
    # The Toulmin split: GROUNDS (does a test prove it?) vs WARRANT (user signal it
    # matters?). A need can be green on one and empty on the other — that gap is the point.
    out.append(f"  {'':2} {'id':<9} {'GROUNDS':<10}{'':5} {'need':<{width}}  WARRANT")
    out.append(
        "  legend: * declared (no results artifact)  ·  !! must  ·  "
        "GROUNDS = test proof  ·  WARRANT = evidence source"
    )
    for who in sorted(groups):
        rs = sorted(groups[who], key=state_priority)
        label = next((x.need.label for x in rs if x.need.label), None)
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "  ·  ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        title = f"{who}" + (f" ({label})" if label else "")
        out.append(f"\n{title}    {head}")
        out.append(f"    {_provenance_line(rs)}")
        for r in rs:
            bang = "!!" if r.need.must else "  "
            star = "*" if r.declared and r.state is NeedState.DELIVERED else " "
            nm = f"{r.delivered}/{r.total}" if r.total else ""
            out.append(
                f"  {bang} {r.need.id:<9} {_LABEL[r.state]:<9}{star} {nm:<5} "
                f"{r.need.text[:width]:<{width}}  {_warrant(r.need)}"
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


def _render_orphans(orphan_map: dict[str, list[str]]) -> str:
    """The reverse report: proof units that no need references."""
    total = sum(len(v) for v in orphan_map.values())
    out = [f"\norphan proofs (claimed by no need): {total}"]
    for name in sorted(orphan_map):
        for sid in orphan_map[name]:
            out.append(f"     {name}:{sid}")
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
        "importance": need.importance,
        "claim": need.claim,
        "attestation": (
            {"who": need.attestation.who, "date": need.attestation.date}
            if need.attestation
            else None
        ),
        "delivered": r.delivered,
        "total": r.total,
        "declared": r.declared,
        "opinion": need.is_opinion,
        "only_internal": need.only_internal,
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
) -> str:
    payload = {
        "summary": _summary_payload(summary, orphan_map),
        "orphans": orphan_map,
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


def _cmd_status(args: argparse.Namespace) -> int:
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    shared = shared_proof_warnings(results)  # cross-need hygiene (#45), a board-level fact
    for r in results:
        if r.need.id in shared:
            r.warnings.append(shared[r.need.id])
    summary = summarize(results)
    orphan_map = orphans(needs, cfg.adapters)
    recs = recurrence(needs)
    goal_cov, ungoaled = goal_report(results, list(model.goals))
    rel_cov = release_report(results, list(model.releases))

    if args.json:
        print(_to_json(results, summary, orphan_map, recs, goal_cov, ungoaled, rel_cov))
    else:
        commit = _git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(_summary_line(summary))
        print(_render(results))
        if model.goals:
            print(_render_goals(goal_cov, ungoaled))
        if model.releases:
            print(_render_releases(rel_cov))
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


def _render_show(r: NeedResult) -> str:
    """One need as a citable answer — the artifact you drop into a thread."""
    need = r.need
    who = (need.who + (f" ({need.label})" if need.label else "")) if need.who else "(unassigned)"
    nm = f"  {r.delivered}/{r.total}" if r.total else ""
    lines = [
        f"{need.id}{'  !!' if need.must else ''}  {need.text}",
        f"  who: {who}",
        f"  grounds: {_LABEL[r.state]}{nm}    warrant: {_warrant(need)}",
        f"  shape: {ears_shape(need.text).value}",
    ]
    if need.goal:
        lines.append(f"  goal: {need.goal}")
    if need.release:
        lines.append(f"  release: {need.release}")
    if need.claim:
        lines.append(f"  claim: {need.claim}")
    if need.attestation:
        lines.append(f"  attested: {need.attestation.who} ({need.attestation.date})")
    elif need.proofs and r.state is NeedState.DELIVERED:
        lines.append("  attested: (none — proof link not human-reviewed, #13)")
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
    print(_show_json(r) if args.json else _render_show(r))
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
    weak = need.strongest_kind is None or need.strongest_kind in (
        SourceKind.PROXY,
        SourceKind.INTERNAL,
    )
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
                        r.need.importance is not None
                        and (
                            r.need.strongest_kind is None
                            or r.need.strongest_kind in (SourceKind.PROXY, SourceKind.INTERNAL)
                        )
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
        edit = set_field(
            cfg, args.need_id, args.assignment, expect_sha=args.expect_sha, dry_run=args.dry_run
        )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return _emit_edit(edit, args.dry_run, args.json)


def _cmd_add(args: argparse.Namespace) -> int:
    """Create a new need from an agent, with a proxy/internal provenance source."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        edit = add_need(
            cfg,
            args.need_id,
            args.text,
            who=args.who,
            kind=args.kind,
            file=args.file,
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
    out = [f"  {'repo':<18} {'cov':>4}  {'must-HOLE':>9}  {'BROKEN':>6}   prov intv/art/prx/int/op"]
    for row in rows:
        if row.error is not None:
            out.append(f"  {row.repo:<18} error: {row.error}")
            continue
        p = row.provenance
        prov = f"{p['interview']}/{p['artifact']}/{p['proxy']}/{p['internal']}/{p['opinion']}"
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

    ad = sub.add_parser("add", help="create a new agent-authored need (writes YAML)")
    ad.add_argument("noun", choices=["need"], help="what to add (need)")
    ad.add_argument("need_id", help="the new need's id, e.g. N-9")
    ad.add_argument("--text", required=True, help="the need text")
    ad.add_argument("--who", required=True, help="the author (recorded on the provenance source)")
    ad.add_argument(
        "--kind",
        choices=["internal", "proxy"],
        default="internal",
        help="provenance source kind (never interview for an agent)",
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
        choices=["interview", "artifact", "proxy", "internal"],
        help="source kind (strongest first: interview > artifact > proxy > internal)",
    )
    cp.add_argument("--who", default=None, help="the person the evidence came from")
    cp.add_argument("--date", default=None, help="when (ISO, e.g. 2026-10-05)")
    cp.add_argument("--quote", default=None, help="a verbatim quote (for an interview)")
    cp.add_argument("--locator", default=None, help="a source locator (for an artifact)")
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

    pf = sub.add_parser("portfolio", help="roll up many repos into one scoreboard")
    pf.add_argument("configs", nargs="+", metavar="PRODC_TOML", help="one or more prodc.toml paths")
    pf.add_argument("--json", action="store_true", help="machine-readable output")
    pf.set_defaults(func=_cmd_portfolio)

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
