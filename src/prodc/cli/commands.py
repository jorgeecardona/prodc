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
from dataclasses import asdict
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
from ..model import Model, Need, NeedResult, NeedState, board_needs
from ..report import render_markdown
from ..report_html import render_html
from ..status import (
    ProofSuggestion,
    applicable_needs,
    argument_defects,
    evidence_age_days,
    proof_suggestions,
    recurrence,
    resolve,
    summarize,
)
from ..writer import (
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
from .common import RepoRow, emit_edit, exit_code, git_rev, load_or_report
from .render import (
    COLUMNS,
    provenance_counts,
    render,
    render_argument,
    render_brief,
    render_columns,
    render_goals,
    render_handoffs,
    render_orphans,
    render_out_of_scope,
    render_plan,
    render_portfolio,
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


def cmd_status(args: argparse.Namespace) -> int:
    loaded = load_or_report(args)
    if loaded is None:
        return 2
    cfg, model = loaded
    needs = list(model.needs)
    # Draft needs (#60) are staged: kept off the counted board (and coverage, recurrence,
    # orphans) until promoted with `set <id> draft=false`, unless --include-drafts is passed.
    draft_count = sum(1 for n in needs if n.draft)
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
            )
        )
    else:
        commit = git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(summary_line(summary))
        if draft_count and not args.include_drafts:
            print(f"drafts: {draft_count} staged (hidden — --include-drafts to show) (#60)")
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
    print(show_json(r) if args.json else render_show(r, cfg.importance_label(r.need.importance)))
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
    print(brief_json(args.client, results) if args.json else render_brief(args.client, results))
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
    print(
        plan_json(results, recurrence_counts)
        if args.json
        else render_plan(results, recurrence_counts)
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
        needs = list(load(cfg).needs)
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
    """Roll up many repos into one scoreboard — coverage, must-HOLEs, provenance per repo."""
    rows = [_repo_row(path) for path in args.configs]
    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        print(render_portfolio(rows))
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
        scoped = applicable_needs(list(model.needs), args.client)
        model = Model(
            needs=tuple(scoped),
            goals=model.goals,
            releases=model.releases,
            roles=model.roles,
            argument=model.argument,
        )
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


def cmd_suggest(args: argparse.Namespace) -> int:
    """Propose candidate proof locators for HOLE needs from the adapters' inventories (#54)."""
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
