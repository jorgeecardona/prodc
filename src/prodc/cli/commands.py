"""The command handlers: one ``_cmd_*`` per subcommand, plus their non-render helpers.

Each handler loads the model (via :func:`prodc.cli.common.load_or_report`), does its command's
work against the engine, and prints through the text renderers or the JSON serialisers. The
argparse wiring that dispatches to these lives in :mod:`prodc.cli.app`.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import cast

from ..board import annotate_board_warnings as _annotate_board_warnings
from ..board import gather
from ..callbacks import advance_ledger, fire, read_ledger, transitions, write_ledger
from ..config import Config, ConfigError
from ..dedup import (
    VariantGroup,
    duplicate_pairs,
    matches_for,
    variant_suggestions,
    who_variants,
)
from ..loader import LoaderError, load
from ..model import Need, NeedResult, NeedState, board_needs
from ..report import render_markdown
from ..report_html import render_html
from ..status import (
    ProofSuggestion,
    RelinkSuggestion,
    applicable_needs,
    argument_defects,
    contradictions,
    decisions_for,
    evidence_age_days,
    importance_revisit_due,
    orphaned_decisions,
    principle_report,
    proof_suggestions,
    recurrence,
    relink_suggestions,
    resolve,
    stale_decisions,
    summarize,
)
from ..writer import (
    Edit,
    WriteError,
    accept,
    add_decision,
    add_need,
    add_principle,
    add_proof,
    add_role,
    attest,
    capture_source,
    delete_need,
    link_variant_group,
    reinstate,
    reinstate_decision,
    relink_proof,
    revise_principle,
    set_field,
    set_importance,
    withdraw,
    withdraw_decision,
)
from .common import (
    RepoRow,
    discover_configs,
    emit_edit,
    exit_code,
    git_rev,
    load_or_report,
    portfolio_totals,
)
from .render import (
    COLUMNS,
    provenance_counts,
    render,
    render_argument,
    render_brief,
    render_columns,
    render_contradictions,
    render_decisions,
    render_goals,
    render_handoffs,
    render_orphans,
    render_out_of_scope,
    render_plan,
    render_portfolio,
    render_principles,
    render_recurrence,
    render_releases,
    render_roles,
    render_show,
    summary_line,
)
from .serialize import (
    argument_json,
    brief_json,
    dup_payload,
    plan_json,
    show_json,
    to_json,
    variant_payload,
)


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


def _annotate_draft_age_warnings(results: list[NeedResult], cfg: Config) -> None:
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
            r.warnings.append("draft with no staged date (`add --draft` stamps one) — #60")
            continue
        try:
            days = (today - date.fromisoformat(when)).days
        except ValueError:
            continue
        if days > cfg.draft_max_age_days:
            r.warnings.append(
                f"draft staged {days}d ago (> {cfg.draft_max_age_days}d) — promote or drop (#60)"
            )


def _annotate_label_deprecation(results: list[NeedResult]) -> None:
    """Nudge needs still carrying the free-text `label` toward role + client (#52, deprecation).

    Since Role (#52) carries the archetype and `client` the org, the per-need `label` is redundant —
    "design partner, Sincerely" is `role` + `client`. Soft only: `label` is still parsed and still
    renders; this flags it so a board can migrate off it before it is removed.
    """
    for r in results:
        if r.need.label:
            r.warnings.append(
                f"'label' ({r.need.label!r}) is deprecated — express it with role + client (#52)"
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


def cmd_lint(args: argparse.Namespace) -> int:
    """Gate the board: fail on hard problems (BROKEN, must-opinion); list hygiene warnings.

    The red-gate counterpart to `status` — so drift is a CI failure, not something you notice
    by eye. `--strict` also fails on any hygiene warning.
    """
    loaded = load_or_report(args)
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
    _annotate_draft_age_warnings(results, cfg)
    _annotate_label_deprecation(results)
    # The principle ripple: a need withdrawn citing a principle that was revised *after* the decision
    # comes back up — the frame it was judged against has changed since. A warning, never a hard
    # error; prodc flags, the PM re-decides.
    for rep in principle_report(needs, list(model.principles)):
        for n in rep.stale:
            if n.id in by_id and n.withdrawn is not None:
                by_id[n.id].warnings.append(
                    f"withdrawn per principle {rep.principle.id} on {n.withdrawn.date}, but "
                    f"{rep.principle.id} was revised {rep.principle.revised_at} — re-review the decision"
                )
    # Unresolved contradiction: two needs oppose each other yet BOTH are still live — the product
    # vision has not decided between them. A warning on both sides (withdraw one out_of_scope citing
    # the principle that decides, or reconcile them).
    for c in contradictions(needs):
        if not c.unresolved:
            continue
        for near, far in ((c.a, c.b), (c.b, c.a)):
            if near.id in by_id:
                by_id[near.id].warnings.append(
                    f"unresolved contradiction with {far.id} — both live, the vision has not "
                    "decided yet (withdraw one out_of_scope citing the principle, or reconcile)"
                )
    errors = _lint_errors(results)
    warnings = [
        (r.need.id, w) for r in sorted(results, key=lambda x: x.need.id) for w in r.warnings
    ]
    # Decision drift (keyed by the decision id, not a need): a decision left serving only
    # withdrawn/non-product needs is engineering with no live product reason; a decision decided
    # under a principle that was revised later comes back up (the same ripple a withdrawal gets).
    decisions = list(model.decisions)
    for d in orphaned_decisions(decisions, needs):
        warnings.append(
            (
                d.id,
                "decision serves only withdrawn/non-product needs — re-tie it to a live need or withdraw it",
            )
        )
    for d, pid in stale_decisions(decisions, list(model.principles)):
        warnings.append(
            (
                d.id,
                f"decided {d.decided_at} under principle {pid}, revised later — re-review this solution",
            )
        )
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


def cmd_status(args: argparse.Namespace) -> int:
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    # Draft needs (#60) are staged: kept off the counted board (and coverage, recurrence,
    # orphans) until promoted with `set <id> draft=false`, unless --include-drafts is passed.
    draft_count = sum(1 for n in needs if n.draft and not n.is_withdrawn)
    withdrawn_count = sum(1 for n in needs if n.is_withdrawn)
    # Break withdrawals down by kind (#74 follow-up), so "declined but valid" (out_of_scope) is
    # legible on the board apart from plain won't-do; wont_do is the implicit default, not listed.
    withdrawn_kinds: dict[str, int] = {}
    for n in needs:
        if n.withdrawn and n.withdrawn.kind.value != "wont_do":
            withdrawn_kinds[n.withdrawn.kind.value] = (
                withdrawn_kinds.get(n.withdrawn.kind.value, 0) + 1
            )
    needs = board_needs(needs, include_drafts=args.include_drafts)
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
    board = gather(cfg, model, needs=needs, annotate_warnings=True)
    results = board.results
    summary = board.summary
    orphan_map = board.orphans
    recs = board.recurrence
    goal_cov, ungoaled = board.goal_cov, board.ungoaled
    rel_cov = board.rel_cov
    role_cov, unroled = board.role_cov, board.unroled
    hos = board.handoffs

    if args.columns:
        bad = [c for c in args.columns if c not in COLUMNS]
        if bad:
            print(
                f"prodc: unknown column(s) {', '.join(bad)} (available: {', '.join(COLUMNS)})",
                file=sys.stderr,
            )
            return 2

    if args.json:
        print(
            to_json(
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
                principles=board.principles,
                decisions=list(model.decisions),
            )
        )
    else:
        commit = git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(summary_line(summary))
        if draft_count and not args.include_drafts:
            print(f"drafts: {draft_count} staged (hidden — --include-drafts to show) (#60)")
        if withdrawn_count:
            extra = ", ".join(f"{c} {k}" for k, c in sorted(withdrawn_kinds.items()))
            suffix = f" — {extra}" if extra else ""
            print(f"withdrawn: {withdrawn_count} (decided against){suffix} (#74)")
        visible = [r for r in results if r.need.product]
        if args.only_must:
            visible = [r for r in visible if r.need.must]
        if args.columns:
            print(render_columns(visible, args.columns))
            return exit_code(args, summary, sum(len(v) for v in orphan_map.values()))
        print(render(visible, wide=args.wide))
        out_of_scope = [r for r in results if not r.need.product]
        if out_of_scope:
            print(render_out_of_scope(out_of_scope))
        if model.goals:
            print(render_goals(goal_cov, ungoaled))
        if model.releases:
            print(render_releases(rel_cov))
        if model.roles:
            print(render_roles(role_cov, unroled))
        if hos:
            print(render_handoffs(hos))
        if recs:
            print(render_recurrence(recs))
        if model.principles:
            print(render_principles(board.principles))
        if model.decisions:
            print(render_decisions(list(model.decisions), needs=list(model.needs)))
        unresolved = [c for c in contradictions(list(model.needs)) if c.unresolved]
        if unresolved:
            print(render_contradictions(unresolved))
        if orphan_map:
            print(render_orphans(orphan_map))

    return exit_code(args, summary, sum(len(v) for v in orphan_map.values()))


def cmd_show(args: argparse.Namespace) -> int:
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    by_id = {r.need.id: r for r in resolve(needs, cfg.adapters, cfg.source_adapters)}
    r = by_id.get(args.need_id)
    if r is None:
        print(f"prodc: no need '{args.need_id}'", file=sys.stderr)
        return 2
    decisions = decisions_for(args.need_id, list(model.decisions))  # the 'how' behind this need
    print(
        show_json(r, decisions=decisions)
        if args.json
        else render_show(r, cfg.importance_label(r.need.importance), decisions=decisions)
    )
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """Pre-meeting agenda for one client: its applicable needs that lack evidence or proof."""
    loaded = load_or_report(args)
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
    # "Confirm still wanted" (#58): needs whose evidence is older than the stale threshold, to
    # re-check with the client in the meeting. Only when [lint].stale_after_days is configured.
    stale: list[tuple[NeedResult, int]] = []
    if cfg.stale_after_days is not None:
        today = date.today()
        for r in results:
            age = evidence_age_days(r.need, today)
            if age is not None and age > cfg.stale_after_days:
                stale.append((r, age))
    print(
        brief_json(args.client, results, stale)
        if args.json
        else render_brief(args.client, results, stale)
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Emit a ranked backlog from recorded inputs — must+state+evidence, importance refines."""
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = board_needs(list(model.needs), include_drafts=args.include_drafts)  # drafts off (#60)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    recurrence_counts = {rec.baseline.id: rec.count for rec in recurrence(needs)}
    revisit = args.revisit is not None
    if revisit:
        today = date.today()
        results = [r for r in results if importance_revisit_due(r.need, today, args.revisit)]
    print(
        plan_json(results, recurrence_counts, revisit=revisit)
        if args.json
        else render_plan(results, recurrence_counts, revisit=revisit)
    )
    return 0


def cmd_set(args: argparse.Namespace) -> int:
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
    return emit_edit(edit, args.dry_run, args.json)


def cmd_add(args: argparse.Namespace) -> int:
    """Create a new need (with an assumption/secondary provenance source) or declare a role (#52)."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    if args.noun == "role":
        if args.text is None:
            print("prodc: add role requires --text", file=sys.stderr)
            return 2
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
        return emit_edit(edit, args.dry_run, args.json)
    if args.noun == "principle":
        try:
            cfg = Config.load(cfg_path)
            text, sources = args.text, ()
            if args.from_need:
                # Promote a need into a principle (the discovery lifecycle): the signals that
                # surfaced it travel with it as provenance, so the history stays honest. The origin
                # need stays on the board unchanged — a need and the principle it inspired coexist.
                origin = next((n for n in load(cfg).needs if n.id == args.from_need), None)
                if origin is None:
                    print(f"prodc: no need '{args.from_need}' to promote", file=sys.stderr)
                    return 2
                text = args.text or origin.text
                sources = origin.sources
            if text is None:
                print(
                    "prodc: add principle requires --text (or --from-need to take it from a need)",
                    file=sys.stderr,
                )
                return 2
            edit = add_principle(
                cfg,
                args.need_id,
                text,
                file=args.file,
                revised_at=date.today().isoformat(),
                sources=sources,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        except (ConfigError, LoaderError, WriteError) as exc:
            print(f"prodc: {exc}", file=sys.stderr)
            return 2
        return emit_edit(edit, args.dry_run, args.json)
    if args.noun == "decision":
        if args.text is None:
            print("prodc: add decision requires --text (the chosen solution)", file=sys.stderr)
            return 2
        needs = tuple(n.strip() for n in (args.needs or "").split(",") if n.strip())
        if not needs:
            print(
                "prodc: add decision requires --needs (the need(s) the solution serves)",
                file=sys.stderr,
            )
            return 2
        principles = tuple(p.strip() for p in (args.principles or "").split(",") if p.strip())
        try:
            cfg = Config.load(cfg_path)
            edit = add_decision(
                cfg,
                args.need_id,
                args.text,
                file=args.file,
                needs=needs,
                decided_at=args.date or date.today().isoformat(),
                alternatives=tuple(args.alternatives or ()),
                consequences=args.consequences,
                principles=principles,
                draft=args.draft,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        except (ConfigError, LoaderError, WriteError) as exc:
            print(f"prodc: {exc}", file=sys.stderr)
            return 2
        return emit_edit(edit, args.dry_run, args.json)
    if args.who is None:
        print("prodc: add need requires --who (the author recorded on the source)", file=sys.stderr)
        return 2
    if args.text is None:
        print("prodc: add need requires --text", file=sys.stderr)
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
    return emit_edit(edit, args.dry_run, args.json)


def cmd_attest(args: argparse.Namespace) -> int:
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
    return emit_edit(edit, args.dry_run, args.json)


def cmd_accept(args: argparse.Namespace) -> int:
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
    return emit_edit(edit, args.dry_run, args.json)


def cmd_withdraw(args: argparse.Namespace) -> int:
    """Record a decision against a need — withdrawn / won't-do (#74)."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        if args.target == "decision":
            # noun-first: ids are unique per noun, so a need and a decision may share one — the
            # noun disambiguates (matches `add decision` / `revise principle`).
            if not args.decision_id:
                print("prodc: withdraw decision needs a decision id", file=sys.stderr)
                return 2
            edit = withdraw_decision(
                cfg,
                args.decision_id,
                reason=args.reason,
                date=args.date or date.today().isoformat(),
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        else:
            edit = withdraw(
                cfg,
                args.target,
                reason=args.reason,
                date=args.date or date.today().isoformat(),
                kind=args.kind,
                principle=args.principle,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return emit_edit(edit, args.dry_run, args.json)


def cmd_reinstate(args: argparse.Namespace) -> int:
    """Remove a need's withdrawal, putting it back on the active board (#74)."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        if args.target == "decision":
            if not args.decision_id:
                print("prodc: reinstate decision needs a decision id", file=sys.stderr)
                return 2
            edit = reinstate_decision(
                cfg,
                args.decision_id,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
        else:
            edit = reinstate(
                cfg,
                args.target,
                expect_sha=args.expect_sha,
                dry_run=args.dry_run,
            )
    except (ConfigError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return emit_edit(edit, args.dry_run, args.json)


def cmd_revise(args: argparse.Namespace) -> int:
    """Revise a product principle in place: optional new text, always a fresh revised_at (the ripple).

    Re-stamping ``revised_at`` is the point — every need withdrawn citing this principle with an
    earlier date comes back up for re-review (surfaced by `lint`). Comment-safe: only the principle's
    own block is spliced, the rest of the file is untouched.
    """
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        edit = revise_principle(
            cfg,
            args.principle_id,
            text=args.text,
            revised_at=args.date or date.today().isoformat(),
            expect_sha=args.expect_sha,
            dry_run=args.dry_run,
        )
    except (ConfigError, LoaderError, WriteError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    return emit_edit(edit, args.dry_run, args.json)


def cmd_review(args: argparse.Namespace) -> int:
    """Triage draft needs: list them with a duplicate score, or --promote / --drop a batch (#60).

    The companion to `add --draft`: drafts pile up staged off the board, and this is the surface
    that clears them. With no action flag it lists each draft with its provenance and the nearest
    existing need (a dedup score, reusing #55), so a reviewer can see what is a duplicate before
    promoting. `--promote` flips `draft=false` (sugar over `set`); `--drop` deletes the draft
    outright (the #60 delete-need path). Both act only on drafts — a real need is withdrawn, not
    dropped, so its record survives.
    """
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    drafts = [n for n in needs if n.draft and not n.is_withdrawn]
    draft_ids = {n.id for n in drafts}

    drop = list(args.drop or [])
    if args.promote_all:
        promote = [n.id for n in drafts if n.id not in drop]
    else:
        promote = list(args.promote or [])

    unknown = [i for i in (*promote, *drop) if i not in draft_ids]
    if unknown:
        print(
            f"prodc: not a staged draft: {', '.join(unknown)} "
            "(review acts only on drafts — withdraw a real need instead)",
            file=sys.stderr,
        )
        return 2
    both = sorted(set(promote) & set(drop))
    if both:
        print(f"prodc: {', '.join(both)} named in both --promote and --drop", file=sys.stderr)
        return 2

    if not promote and not drop:
        return _review_list(cfg, drafts, needs, args.json)
    return _review_apply(cfg, promote, drop, args)


def _review_list(cfg: Config, drafts: list[Need], needs: list[Need], as_json: bool) -> int:
    """List the staged drafts with provenance and the nearest existing need (read-only)."""
    rows: list[dict[str, object]] = []
    for d in sorted(drafts, key=lambda n: n.id):
        others = [n for n in needs if n.id != d.id]
        hits = matches_for(d.text, others, cfg.duplicate_threshold, exclude_id=d.id)
        dup = {"id": hits[0][0].id, "score": round(hits[0][1], 4)} if hits else None
        rows.append(
            {
                "id": d.id,
                "text": d.text,
                "who": d.who,
                "client": d.client,
                "sources": [s.kind.value for s in d.sources],
                "staged": d.draft_added,
                "duplicate": dup,
            }
        )
    if as_json:
        print(json.dumps({"drafts": rows}, indent=2))
        return 0
    for r in rows:
        who = f" — {r['who']}" if r["who"] else ""
        client = f" [{r['client']}]" if r["client"] else ""
        staged = f" (staged {r['staged']})" if r["staged"] else ""
        print(f"{r['id']}{who}{client}{staged}: {r['text']}")
        kinds = cast("list[str]", r["sources"])
        if kinds:
            print(f"        sources: {', '.join(kinds)}")
        dup = cast("dict[str, object] | None", r["duplicate"])
        if dup is not None:
            print(f"        possible duplicate of {dup['id']} ({dup['score']:.2f}) — #55")
    print(f"review: {len(rows)} draft(s) staged")
    return 0


def _review_apply(
    cfg: Config, promote: list[str], drop: list[str], args: argparse.Namespace
) -> int:
    """Promote (`draft=false`) and/or drop (delete) the named drafts, each a validated edit (#60).

    Sequential and independent, like `suggest --apply`: each need is one reload-gated, single-file
    write applied in id order, and a rejection aborts with a non-zero exit (earlier writes stand).
    """
    applied: list[tuple[str, str, Edit]] = []  # (action, need_id, edit)
    try:
        for nid in sorted(promote):
            edit = set_field(cfg, nid, "draft=false", expect_sha=None, dry_run=args.dry_run)
            applied.append(("promote", nid, edit))
        for nid in sorted(drop):
            edit = delete_need(cfg, nid, dry_run=args.dry_run)
            applied.append(("drop", nid, edit))
    except WriteError as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "action": action,
                        "need": nid,
                        "file": edit.path.name,
                        "dry_run": args.dry_run,
                        "diff": edit.diff,
                    }
                    for action, nid, edit in applied
                ],
                indent=2,
            )
        )
        return 0
    for action, nid, edit in applied:
        verb = "would promote" if action == "promote" else "would drop"
        if not args.dry_run:
            verb = "promoted" if action == "promote" else "dropped"
        print(f"{verb} {nid} in {edit.path.name}")
        print(edit.diff, end="")
    n_prom = sum(1 for row in applied if row[0] == "promote")
    n_drop = len(applied) - n_prom
    print(f"review: {n_prom} promoted, {n_drop} dropped" + (" (dry-run)" if args.dry_run else ""))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
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
            role=args.role,
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
    return emit_edit(edit, args.dry_run, args.json)


def cmd_argument(args: argparse.Namespace) -> int:
    """Show the GSN assurance graph and its defects (unsupported claim, dangling assumption)."""
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    _cfg, model = loaded
    defects = argument_defects(list(model.argument))
    print(argument_json(model, defects) if args.json else render_argument(model, defects))
    return 1 if (args.strict and defects) else 0


def _repo_row(config_path: str) -> RepoRow:
    p = Path(config_path)
    name = p.parent.name or str(p)
    try:
        cfg = Config.load(p)
        # Drafts (#60) and withdrawn needs (#74) are off the counted board, same as `status`/`plan`,
        # so a repo's portfolio line never inflates with staged ideas.
        needs = board_needs(list(load(cfg).needs), include_drafts=False)
    except (ConfigError, LoaderError, OSError) as exc:
        return RepoRow(name, 0, 0, 0, 0, 0.0, {}, error=str(exc))
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    s = summarize(results)
    return RepoRow(
        repo=cfg.root.name,
        delivered=s.delivered,
        total=s.total,
        must_hole=s.must_hole,
        broken=s.broken,
        coverage=round(s.coverage, 4),
        provenance=provenance_counts(results),
    )


def cmd_portfolio(args: argparse.Namespace) -> int:
    """Roll up many boards into one scoreboard — coverage, must-HOLEs, provenance per board.

    Each argument is a ``prodc.toml`` path or a directory to discover boards under (every
    ``prodc.toml`` beneath it, pruning VCS/vendor/build and hidden dirs, capped at ``--max-depth``).
    Boards stay separate rows; a totals footer aggregates the clean ones. Never a merged board.
    """
    paths: list[str] = []
    for arg in args.configs:
        p = Path(arg)
        if p.is_dir():
            paths.extend(str(c) for c in discover_configs(p, max_depth=args.max_depth))
        else:
            paths.append(arg)
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        key = str(Path(path).resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    rows = [_repo_row(path) for path in unique]
    totals = portfolio_totals(rows)
    if args.json:
        payload = {"boards": [asdict(r) for r in rows], "totals": asdict(totals)}
        print(json.dumps(payload, indent=2))
    else:
        print(render_portfolio(rows, totals))
    return 2 if any(r.error is not None for r in rows) else 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Diff the current board against a prior `status --json` snapshot."""
    loaded = load_or_report(args)
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


def cmd_report(args: argparse.Namespace) -> int:
    """Render the board as a readable markdown document — a file a PM can read, share, or print."""
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    if args.client:
        # replace keeps every other noun (principles, decisions, …); a hand-rolled Model(...)
        # silently dropped them, which breaks the moment the report renders them (#0.4).
        scoped = applicable_needs(list(model.needs), args.client)
        model = replace(model, needs=tuple(scoped))
    if args.format == "html":
        text = render_html(cfg, model, client=args.client, rev=git_rev(cfg.root))
    else:
        text = render_markdown(cfg, model, client=args.client, rev=git_rev(cfg.root))
    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote report to {dest}")
    else:
        print(text)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Fire lifecycle callbacks for needs whose state changed since the last sync (#71).

    Resolves the board, diffs it against the state ledger, runs the configured callbacks for each
    transition (the need + board context piped as JSON on stdin), and writes the ledger forward.
    The first run records a baseline and fires nothing; a failed callback is reported and its need
    is left un-advanced so the next sync retries it. `--dry-run` shows what would fire.
    """
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    current = {r.need.id: r.state.value for r in results}
    summary = summarize(results)
    board: dict[str, object] = {
        "coverage_pct": round(summary.coverage * 100),
        "delivered": summary.delivered,
        "total": summary.total,
    }
    ledger_path = cfg.root / cfg.callback_state_file
    ledger = read_ledger(ledger_path)

    if ledger is None:  # first run: establish the baseline, never fire (all would look new)
        if not args.dry_run:
            write_ledger(ledger_path, current)
        n = len(current)
        print(
            f"sync: baseline recorded ({n} need{'s' if n != 1 else ''}) — no callbacks fired on first run"
        )
        return 0

    trans = transitions(ledger, current)
    if not trans:
        if current != ledger and not args.dry_run:
            write_ledger(ledger_path, current)  # pick up added/removed needs silently
        print("sync: no state changes")
        return 0

    if args.dry_run:
        for t in trans:
            n = sum(
                1 for c in cfg.callbacks if c.event == "state_change" and c.matches(t.frm, t.to)
            )
            print(f"  {t.need_id}: {t.frm} → {t.to} ({n} callback(s) would fire)")
        print(f"sync --dry-run: {len(trans)} transition(s); ledger not written")
        return 0

    context = {r.need.id: r.need for r in results}
    fired = fire(list(trans), list(cfg.callbacks), context=context, board=board, cwd=cfg.root)
    write_ledger(ledger_path, advance_ledger(current, ledger, fired))

    for t in trans:
        print(f"  {t.need_id}: {t.frm} → {t.to}")
    for f in fired:
        print(f"    → {' '.join(f.command)}: {'ok' if f.ok else 'FAILED'} ({f.detail})")
    failures = [f for f in fired if not f.ok]
    print(f"sync: {len(trans)} transition(s), {len(fired)} callback run(s), {len(failures)} failed")
    return 1 if failures else 0


def cmd_agent(args: argparse.Namespace) -> int:
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


def cmd_guide(args: argparse.Namespace) -> int:
    """Print prodc's human CLI guide (a short onboarding path), or write it to a file.

    The human sibling of :func:`cmd_agent`: where `agent` ships an instruction set for a coding
    agent, `guide` is the 60-second path a person reads to try prodc. Ships versioned with prodc;
    `--write` drops it into a repo.
    """
    text = importlib.resources.files("prodc").joinpath("guide.md").read_text(encoding="utf-8")
    if args.write:
        dest = Path(args.write)
        if dest.exists() and not args.force:
            print(f"prodc: {dest} already exists (use --force to overwrite)", file=sys.stderr)
            return 2
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote prodc guide to {dest}")
        return 0
    print(text, end="")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    """Propose candidate proof locators for HOLE needs (or relink BROKEN ones) from the inventories (#54)."""
    loaded = load_or_report(args)
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
    if args.relink:
        return _cmd_relink(cfg, results, args)
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


def _cmd_relink(cfg: Config, results: list[NeedResult], args: argparse.Namespace) -> int:
    """Propose (or --apply) a live inventory entry to replace each BROKEN proof locator (#54)."""
    suggestions = relink_suggestions(
        results, cfg.adapters, min_score=args.min_score, top=args.top, kind=args.kind
    )
    if args.apply:
        return _apply_relinks(cfg, suggestions, args)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "need": s.need.id,
                        "adapter": s.adapter,
                        "broken": s.broken,
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
            print(f"    {s.score:.2f}  {s.broken} → {s.locator}")
        print(
            f"suggest --relink: {len(suggestions)} candidate(s) at min-score {args.min_score:.2f}"
        )
    return 0


def _apply_relinks(
    cfg: Config, suggestions: list[RelinkSuggestion], args: argparse.Namespace
) -> int:
    """Apply the best relink per broken locator, printing each need's diff (#54 relink).

    Keyed by ``(need, broken locator)`` so a need with two broken proofs relinks both to their own
    best candidate. Each is one reload-gated single-file edit (:func:`relink_proof`), applied in a
    stable order; a rejected write aborts with a non-zero exit (earlier writes stand).
    """
    best: dict[tuple[str, str], RelinkSuggestion] = {}
    for s in suggestions:
        best.setdefault((s.need.id, s.broken), s)
    applied: list[tuple[RelinkSuggestion, Edit]] = []
    for key in sorted(best):
        s = best[key]
        try:
            edit = relink_proof(cfg, s.need.id, s.broken, s.locator, dry_run=args.dry_run)
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
                        "broken": s.broken,
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
        verb = "would relink" if args.dry_run else "relinked"
        for s, edit in applied:
            print(
                f"{verb} {s.broken} → {s.locator} on {s.need.id} ({s.score:.2f}) in {edit.path.name}"
            )
            print(edit.diff, end="")
        print(f"suggest --relink --apply: {verb} {len(applied)} locator(s)")
    return 0


def cmd_recurrence(args: argparse.Namespace) -> int:
    """Show baselines shared across clients; `--suggest` proposes unlinked variant groups (#56)."""
    loaded = load_or_report(args)
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
            print(json.dumps([variant_payload(g) for g in groups], indent=2))
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


def cmd_dupes(args: argparse.Namespace) -> int:
    """List candidate duplicate need pairs, ranked by text similarity (#55)."""
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    threshold = args.threshold if args.threshold is not None else cfg.duplicate_threshold
    pairs = duplicate_pairs(list(model.needs), threshold)
    if args.json:
        print(
            json.dumps(
                [dup_payload(p) for p in pairs],
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
