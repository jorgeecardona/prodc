"""The argument parser and dispatch for ``prodc`` — one subparser per command.

Builds the argparse tree, wires each subcommand to its handler in :mod:`prodc.cli.commands`,
and runs it. ``main`` is the console entry point (``prodc.cli:main``), re-exported from the
package ``__init__``.
"""

from __future__ import annotations

import argparse
import os
import sys

from .. import __version__
from .commands import (
    cmd_accept,
    cmd_add,
    cmd_agent,
    cmd_attest,
    cmd_brief,
    cmd_capture,
    cmd_diff,
    cmd_dupes,
    cmd_guide,
    cmd_lint,
    cmd_plan,
    cmd_portfolio,
    cmd_recurrence,
    cmd_reinstate,
    cmd_report,
    cmd_review,
    cmd_revise,
    cmd_set,
    cmd_show,
    cmd_status,
    cmd_suggest,
    cmd_sync,
    cmd_withdraw,
)


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
        "--tag",
        default=None,
        metavar="TAG",
        help="scope the board + coverage to the needs carrying one tag (#80)",
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
    st.set_defaults(func=cmd_status)

    ln = sub.add_parser("lint", help="gate the board: fail on BROKEN proofs and must-opinions")
    ln.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ln.add_argument("--json", action="store_true", help="machine-readable output")
    ln.add_argument("--strict", action="store_true", help="also fail on any hygiene warning")
    ln.set_defaults(func=cmd_lint)

    sh = sub.add_parser("show", help="show one need or decision as a citable answer")
    sh.add_argument("need_id", help="the need or decision id to show, e.g. N-1 or D-1")
    sh.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    sh.add_argument("--json", action="store_true", help="machine-readable output")
    sh.set_defaults(func=cmd_show)

    br = sub.add_parser("brief", help="pre-meeting agenda for one client: open opinions and HOLEs")
    br.add_argument("client", help="the client/variant id to brief, e.g. acme")
    br.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    br.add_argument("--json", action="store_true", help="machine-readable output")
    br.set_defaults(func=cmd_brief)

    pl = sub.add_parser("plan", help="ranked backlog from must + state + evidence (+ importance)")
    pl.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    pl.add_argument("--json", action="store_true", help="machine-readable output")
    pl.add_argument(
        "--include-drafts", action="store_true", help="include draft (staged) needs (#60)"
    )
    pl.add_argument(
        "--revisit",
        type=int,
        default=None,
        metavar="DAYS",
        help="only needs whose importance is undated or set more than DAYS ago — a refresh pass (#59)",
    )
    pl.set_defaults(func=cmd_plan)

    st2 = sub.add_parser(
        "set", help="set or append one field on a need, or a decision's awaits (writes YAML)"
    )
    st2.add_argument("need_id", help="the need (or decision) id to edit, e.g. N-1 or D-1")
    st2.add_argument(
        "assignment",
        help="key=value, or key+=value to append (proofs/children/…); on a decision, "
        "awaits+=REF / awaits-=REF",
    )
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
    st2.set_defaults(func=cmd_set)

    ad = sub.add_parser(
        "add",
        help="create a need, or declare a role, a principle, or a decision (writes YAML)",
    )
    ad.add_argument("noun", choices=["need", "role", "principle", "decision"], help="what to add")
    ad.add_argument(
        "need_id",
        help="the new item's id — need (N-9), role, principle (P-1), or decision (D-1)",
    )
    ad.add_argument(
        "--text",
        default=None,
        help="the need text (or the role / principle text); required except `add principle "
        "--from-need`, which takes the text from the need",
    )
    ad.add_argument(
        "--from-need",
        default=None,
        metavar="ID",
        help="principle only: promote a need into a principle — copy its text (unless --text "
        "overrides) and its sources as the provenance that surfaced it; the need stays on the board",
    )
    ad.add_argument(
        "--scope",
        default="product",
        metavar="SCOPE",
        help="principle only: its scope — product (default), design, visual, engineering; "
        "must be declared in [principles].scopes",
    )
    ad.add_argument(
        "--implemented-in",
        default=None,
        metavar="LOCATOR",
        dest="implemented_in",
        help="principle only: a locator to the one place its values live (a pointer, not a copy)",
    )
    ad.add_argument(
        "--proof",
        action="append",
        default=None,
        dest="principle_proofs",
        metavar="LOCATOR",
        help="principle only: a guard-test locator proving the code obeys it (repeatable); "
        "never a need: reference",
    )
    ad.add_argument(
        "--needs",
        default=None,
        metavar="IDS",
        help="decision only: comma-separated ids of the needs this decision serves (required; "
        "validated at load)",
    )
    ad.add_argument(
        "--alternative",
        action="append",
        default=None,
        dest="alternatives",
        metavar="TEXT",
        help="decision only: an option that was rejected (repeatable) — what makes it a choice",
    )
    ad.add_argument(
        "--consequences",
        default=None,
        help="decision only: what the chosen solution costs / rules out",
    )
    ad.add_argument(
        "--principles",
        default=None,
        metavar="IDS",
        help="decision only: comma-separated principle ids the decision rests on (validated); "
        "revising one flags the decision stale",
    )
    ad.add_argument(
        "--date",
        default=None,
        metavar="ISO",
        help="decision only: when it was decided (default: today) — the comparand for the ripple",
    )
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
    ad.set_defaults(func=cmd_add)

    cp = sub.add_parser("capture", help="append a source (evidence) to an existing need")
    cp.add_argument("need_id", help="the need id to add evidence to")
    cp.add_argument(
        "--kind",
        required=True,
        choices=[
            "primary",
            "secondary",
            "assumption",
            "interview",
            "artifact",
            "proxy",
            "internal",
        ],
        help="source kind, strongest first: primary > secondary > assumption "
        "(interview/artifact/proxy/internal accepted as aliases)",
    )
    cp.add_argument("--who", default=None, help="the person the evidence came from")
    cp.add_argument(
        "--role",
        default=None,
        metavar="ID",
        help="the declared role the person spoke as (validated against roles:) — whose signal it is (#52)",
    )
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
    cp.set_defaults(func=cmd_capture)

    at = sub.add_parser("attest", help="record a human or AI review of a need's warrant (#13)")
    at.add_argument("need_id", help="the need id being attested")
    at.add_argument("--by", required=True, help="who reviewed it — a person's name or a model id")
    at.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-05)")
    at.add_argument("--ai", action="store_true", help="the reviewer is an AI model, not a human")
    at.add_argument(
        "--verdict",
        choices=["pass", "concerns", "fail"],
        default=None,
        help="the reviewer's conclusion; only pass clears the warrant (anything else warns)",
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
    at.set_defaults(func=cmd_attest)

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
    ac.set_defaults(func=cmd_accept)

    wd = sub.add_parser(
        "withdraw", help="record a decision against a need — withdrawn / won't-do (#74)"
    )
    wd.add_argument("target", help="the need id to withdraw, or 'decision' to withdraw a decision")
    wd.add_argument(
        "decision_id", nargs="?", default=None, help="the decision id (when target is 'decision')"
    )
    wd.add_argument(
        "--reason", required=True, help="why it was decided against (kept on the record)"
    )
    wd.add_argument(
        "--kind",
        choices=["wont_do", "out_of_scope", "duplicate"],
        default="wont_do",
        help="the decision's kind: wont_do (default), out_of_scope (real but not this product), "
        "or duplicate (#74)",
    )
    wd.add_argument("--date", default=None, help="when (ISO, e.g. 2026-10-10; default: today)")
    wd.add_argument(
        "--of",
        default=None,
        metavar="ID",
        help="the need this one duplicates (validated); required with --kind duplicate",
    )
    wd.add_argument(
        "--principle",
        default=None,
        metavar="ID",
        help="the product principle this decision rests on (validated against principles:) — revising it "
        "later flags this decision for re-review",
    )
    wd.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    wd.add_argument("--json", action="store_true", help="machine-readable output")
    wd.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    wd.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    wd.set_defaults(func=cmd_withdraw)

    ri = sub.add_parser(
        "reinstate", help="remove a need's withdrawal, putting it back on the board (#74)"
    )
    ri.add_argument(
        "target", help="the need id to reinstate, or 'decision' to reinstate a decision"
    )
    ri.add_argument(
        "decision_id", nargs="?", default=None, help="the decision id (when target is 'decision')"
    )
    ri.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    ri.add_argument("--json", action="store_true", help="machine-readable output")
    ri.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    ri.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    ri.set_defaults(func=cmd_reinstate)

    rvz = sub.add_parser(
        "revise", help="revise a product principle in place — new text and/or a fresh revised_at"
    )
    rvz.add_argument("noun", choices=["principle"], help="what to revise (principle)")
    rvz.add_argument("principle_id", help="the principle id to revise, e.g. P-1")
    rvz.add_argument(
        "--text", default=None, help="new principle text (optional; omit to only re-date it)"
    )
    rvz.add_argument(
        "--date",
        default=None,
        help="the new revised_at (ISO, e.g. 2026-10-15; default: today) — fires the ripple",
    )
    rvz.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    rvz.add_argument("--json", action="store_true", help="machine-readable output")
    rvz.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    rvz.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    rvz.set_defaults(func=cmd_revise)

    rv = sub.add_parser(
        "review", help="triage staged drafts: list them, or --promote / --drop a batch (#60)"
    )
    rv.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    rv.add_argument("--json", action="store_true", help="machine-readable output")
    rv.add_argument(
        "--promote",
        nargs="+",
        default=None,
        metavar="ID",
        help="promote these drafts onto the board (sets draft=false)",
    )
    rv.add_argument(
        "--promote-all",
        action="store_true",
        help="promote every staged draft (except any named in --drop)",
    )
    rv.add_argument(
        "--drop",
        nargs="+",
        default=None,
        metavar="ID",
        help="delete these drafts outright (a draft, never a real need — withdraw that)",
    )
    rv.add_argument(
        "--dry-run", action="store_true", help="validate and show the diffs, don't write"
    )
    rv.set_defaults(func=cmd_review)

    pf = sub.add_parser("portfolio", help="roll up many boards into one scoreboard")
    pf.add_argument(
        "configs",
        nargs="+",
        metavar="PATH",
        help="prodc.toml paths and/or directories to discover boards under",
    )
    pf.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="how deep to descend when discovering boards under a directory (default 4)",
    )
    pf.add_argument("--json", action="store_true", help="machine-readable output")
    pf.set_defaults(func=cmd_portfolio)

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
        help="file to write a created baseline into (must match a [prodc].files glob)",
    )
    rc.add_argument(
        "--dry-run", action="store_true", help="with --apply: validate and show diffs, don't write"
    )
    rc.set_defaults(func=cmd_recurrence)

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
        "--relink",
        action="store_true",
        help="BROKEN-need mode: propose a live inventory entry to replace each broken locator (#54)",
    )
    sg.add_argument(
        "--apply",
        action="store_true",
        help="write the best suggestion per need as a proof (relink: replace the broken one) (#54)",
    )
    sg.add_argument(
        "--dry-run",
        action="store_true",
        help="with --apply: validate and show the diff, don't write",
    )
    sg.set_defaults(func=cmd_suggest)

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
    du.set_defaults(func=cmd_dupes)

    rp = sub.add_parser(
        "report", help="render the board as a shareable document (markdown, or an interactive HTML)"
    )
    rp.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    rp.add_argument(
        "--format",
        choices=["md", "html"],
        default="md",
        help="md (default) or html — a self-contained, interactive, read-only viewer (#79)",
    )
    rp.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="PATH",
        help="write the report to PATH (e.g. status.md / status.html) instead of stdout",
    )
    rp.add_argument(
        "--client", default=None, metavar="ID", help="scope the report to one client (as `status`)"
    )
    rp.set_defaults(func=cmd_report)

    sy = sub.add_parser(
        "sync",
        help="run lifecycle callbacks for needs whose state changed since the last sync (#71)",
    )
    sy.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    sy.add_argument(
        "--dry-run",
        action="store_true",
        help="show which transitions would fire callbacks; don't run them or write the ledger",
    )
    sy.set_defaults(func=cmd_sync)

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
    ag.set_defaults(func=cmd_agent)

    gd = sub.add_parser(
        "guide", help="print prodc's human CLI guide (a short, scannable onboarding path)"
    )
    gd.add_argument(
        "--write",
        default=None,
        metavar="PATH",
        help="write the guide to PATH instead of stdout",
    )
    gd.add_argument("--force", action="store_true", help="overwrite PATH if it already exists")
    gd.set_defaults(func=cmd_guide)

    df = sub.add_parser(
        "diff", help="diff the current board against a prior status --json snapshot"
    )
    df.add_argument("snapshot", help="path to a saved `prodc status --json` file")
    df.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    df.add_argument("--json", action="store_true", help="machine-readable output")
    df.set_defaults(func=cmd_diff)

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
