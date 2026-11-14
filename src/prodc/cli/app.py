"""The argument parser and dispatch for ``prodc``: one subparser per command.

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
    cmd_inbox,
    cmd_lint,
    cmd_outcome,
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
    cmd_views,
    cmd_withdraw,
)
from .issue import add_issue_parser
from .mcp import add_mcp_parser


def build_parser() -> argparse.ArgumentParser:
    """Return the full ``prodc`` argument parser. The MCP server builds its argv against it."""
    parser = argparse.ArgumentParser(prog="prodc", description="Product management as code.")
    parser.add_argument("--version", action="version", version=f"prodc {__version__}")
    parser.add_argument(
        "-C",
        "--chdir",
        metavar="DIR",
        default=None,
        help="run as if prodc was started in DIR (like `terraform -chdir`); must precede the command",
    )
    config = argparse.ArgumentParser(add_help=False)
    config.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    json_out = argparse.ArgumentParser(add_help=False)
    json_out.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status", parents=[config, json_out], help="show the needs board")
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

    ln = sub.add_parser(
        "lint",
        parents=[config, json_out],
        help="gate the board: fail on BROKEN proofs and must-opinions",
    )
    ln.add_argument("--strict", action="store_true", help="also fail on any hygiene warning")
    ln.add_argument(
        "--all-warnings",
        action="store_true",
        help="list each warning per id instead of one summary line per repeated message (#87)",
    )
    ln.add_argument(
        "--baseline",
        metavar="FILE",
        default=None,
        help="show only the warnings not in FILE (written by --write-baseline)",
    )
    ln.add_argument(
        "--write-baseline",
        metavar="FILE",
        default=None,
        help="save the current warnings to FILE, to pass later with --baseline",
    )
    ln.set_defaults(func=cmd_lint)

    sh = sub.add_parser(
        "show", parents=[config, json_out], help="show one need or decision as a citable answer"
    )
    sh.add_argument("need_id", help="the need or decision id to show, e.g. N-1 or D-1")
    sh.set_defaults(func=cmd_show)

    br = sub.add_parser(
        "brief",
        parents=[config, json_out],
        help="pre-meeting agenda for one client: open opinions and HOLEs",
    )
    br.add_argument("client", help="the client/variant id to brief, e.g. acme")
    br.set_defaults(func=cmd_brief)

    ib = sub.add_parser(
        "inbox",
        parents=[config, json_out],
        help="open decisions only a person can make, each with its options (#113)",
    )
    ib.set_defaults(func=cmd_inbox)

    pl = sub.add_parser(
        "plan",
        parents=[config, json_out],
        help="ranked backlog from must + state + evidence (+ importance)",
    )
    pl.add_argument(
        "--include-drafts", action="store_true", help="include draft (staged) needs (#60)"
    )
    pl.add_argument(
        "--revisit",
        type=int,
        default=None,
        metavar="DAYS",
        help="only needs whose importance is undated or set more than DAYS ago. A refresh pass (#59)",
    )
    pl.set_defaults(func=cmd_plan)

    st2 = sub.add_parser(
        "set",
        parents=[config, json_out],
        help="set or append one field on a need, or a decision's awaits (writes YAML)",
    )
    st2.add_argument("need_id", help="the need (or decision) id to edit, e.g. N-1 or D-1")
    st2.add_argument(
        "assignment",
        help="key=value, or key+=value to append (proofs/children/…); on a decision, "
        "awaits+=REF / awaits-=REF",
    )
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
        parents=[config, json_out],
        help="create a need, or declare a role, a principle, or a decision (writes YAML)",
    )
    ad.add_argument("noun", choices=["need", "role", "principle", "decision"], help="what to add")
    ad.add_argument(
        "need_id",
        nargs="?",
        default=None,
        help="the new item's id: need (N-9), role, principle (P-1), or decision (D-1); "
        "omit only with --from-catalog (the catalog id is used)",
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
        help="principle only: promote a need into a principle: copy its text (unless --text "
        "overrides) and its sources as the provenance that surfaced it; the need stays on the board",
    )
    ad.add_argument(
        "--from-catalog",
        default=None,
        metavar="CATALOG_ID",
        dest="from_catalog",
        help="principle only: seed from a catalog entry (e.g. ux-fitts): writes id=catalog-id, "
        "scope=design, text from the entry's template, and a secondary source; prints the recipe",
    )
    ad.add_argument(
        "--decline",
        default=None,
        metavar="REASON",
        help="principle only (with --from-catalog): write the principle then immediately mark it "
        "withdrawn out_of_scope with REASON (records a deliberate decision to skip this law)",
    )
    ad.add_argument(
        "--scope",
        default="product",
        metavar="SCOPE",
        help="principle only: its scope: product (default), design, visual, engineering; "
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
        help="decision only: an option that was rejected (repeatable), what makes it a choice",
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
        help="decision only: when it was decided (default: today), the comparand for the ripple",
    )
    ad.add_argument(
        "--who",
        default=None,
        help="need only: the author (recorded on the provenance source); required for `add need`",
    )
    ad.add_argument(
        "--kind",
        choices=["assumption", "secondary"],
        default="assumption",
        help="need only: provenance source kind: assumption (default) or secondary; never "
        "primary for an agent",
    )
    ad.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="prodc file to write into, relative to the config (must match a glob)",
    )
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

    cp = sub.add_parser(
        "capture", parents=[config, json_out], help="append a source (evidence) to an existing need"
    )
    cp.add_argument("need_id", help="the need id to add evidence to")
    cp.add_argument(
        "--kind",
        required=True,
        choices=["primary", "secondary", "assumption"],
        help="source kind, strongest first: primary > secondary > assumption "
        "(interview/artifact/proxy/internal accepted as aliases)",
    )
    cp.add_argument("--who", default=None, help="the person the evidence came from")
    cp.add_argument(
        "--role",
        default=None,
        metavar="ID",
        help="the declared role the person spoke as (validated against roles:), whose signal it is (#52)",
    )
    cp.add_argument("--date", default=None, help="when (ISO, e.g. 2026-10-05)")
    cp.add_argument("--quote", default=None, help="a verbatim quote (for a primary source)")
    cp.add_argument("--locator", default=None, help="a source locator (for a secondary source)")
    cp.add_argument(
        "--anchor",
        default=None,
        help="an exact place inside the locator: L120-L134 for a local file, p.7, 00:14:32 (#57)",
    )
    cp.add_argument(
        "--observed-at",
        default=None,
        metavar="ISO",
        help="when this evidence was recorded/refreshed (default: today) (#58)",
    )
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

    at = sub.add_parser(
        "attest",
        parents=[config, json_out],
        help="record a human or AI review of a need's warrant (#13)",
    )
    at.add_argument("need_id", help="the need id being attested")
    at.add_argument("--by", required=True, help="who reviewed it: a person's name or a model id")
    at.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-05)")
    at.add_argument("--ai", action="store_true", help="the reviewer is an AI model, not a human")
    at.add_argument(
        "--verdict",
        choices=["pass", "concerns", "fail"],
        required=True,
        help="the reviewer's conclusion; only pass clears the warrant (anything else warns)",
    )
    at.add_argument("--comment", default=None, help="the review's feedback, kept on the record")
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

    oc = sub.add_parser(
        "outcome",
        parents=[config, json_out],
        help="record whether a delivered need moved its goal (#97)",
    )
    oc.add_argument("need_id", help="the need id")
    landed = oc.add_mutually_exclusive_group(required=True)
    landed.add_argument("--landed", dest="landed", action="store_true", help="it moved the goal")
    landed.add_argument(
        "--not-landed", dest="landed", action="store_false", help="it did not move the goal"
    )
    oc.add_argument("--by", required=True, help="who observed it")
    oc.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-24)")
    oc.add_argument("--evidence", default=None, help="what was observed, or where (a locator)")
    oc.add_argument(
        "--dry-run", action="store_true", help="validate and show the diff, don't write"
    )
    oc.add_argument(
        "--expect-sha",
        default=None,
        metavar="SHA256",
        help="refuse if the file's content hash differs (optimistic lock)",
    )
    oc.set_defaults(func=cmd_outcome)

    ac = sub.add_parser(
        "accept",
        parents=[config, json_out],
        help="record a human acceptance pass (accept proof) on a need",
    )
    ac.add_argument("need_id", help="the need id that was accepted")
    ac.add_argument("--who", required=True, help="who accepted it")
    ac.add_argument("--date", required=True, help="when (ISO, e.g. 2026-10-05)")
    ac.add_argument("--revoke", action="store_true", help="remove this accept proof instead")
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
        "withdraw",
        parents=[config, json_out],
        help="record a decision against a need: withdrawn / won't-do (#74)",
    )
    wd.add_argument(
        "target",
        help="the need id to withdraw, 'decision' to withdraw a decision, or 'principle' to withdraw a principle",
    )
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
        help="the product principle this decision rests on (validated against principles:). Revising it "
        "later flags this decision for re-review",
    )
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
        "reinstate",
        parents=[config, json_out],
        help="remove a need's withdrawal, putting it back on the board (#74)",
    )
    ri.add_argument(
        "target",
        help="the need id to reinstate, 'decision' to reinstate a decision, or 'principle' to reinstate a principle",
    )
    ri.add_argument(
        "decision_id", nargs="?", default=None, help="the decision id (when target is 'decision')"
    )
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
        "revise",
        parents=[config, json_out],
        help="revise a product principle in place: new text and/or a fresh revised_at",
    )
    rvz.add_argument("noun", choices=["principle"], help="what to revise (principle)")
    rvz.add_argument("principle_id", help="the principle id to revise, e.g. P-1")
    rvz.add_argument(
        "--text", default=None, help="new principle text (optional; omit to only re-date it)"
    )
    rvz.add_argument(
        "--date",
        default=None,
        help="the new revised_at (ISO, e.g. 2026-10-15; default: today), fires the ripple",
    )
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
        "review",
        parents=[config, json_out],
        help="triage staged drafts: list them, or --promote / --drop a batch (#60)",
    )
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
        help="delete these drafts outright (a draft, never a real need: withdraw that)",
    )
    rv.add_argument(
        "--dry-run", action="store_true", help="validate and show the diffs, don't write"
    )
    rv.set_defaults(func=cmd_review)

    pf = sub.add_parser(
        "portfolio", parents=[json_out], help="roll up many boards into one scoreboard"
    )
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
    pf.set_defaults(func=cmd_portfolio)

    rc = sub.add_parser(
        "recurrence",
        parents=[config, json_out],
        help="baselines shared across clients; --suggest proposes unlinked groups",
    )
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
        "suggest",
        parents=[config, json_out],
        help="propose candidate proofs for HOLE needs from adapter inventories (#54)",
    )
    sg.add_argument("need_id", nargs="?", default=None, help="only this need (default: all HOLEs)")
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

    du = sub.add_parser(
        "dupes",
        parents=[config, json_out],
        help="list candidate duplicate need pairs by text similarity",
    )
    du.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="FRAC",
        help="similarity to flag (0..1); overrides [lint].duplicate_threshold",
    )
    du.set_defaults(func=cmd_dupes)

    vw = sub.add_parser(
        "views",
        parents=[config, json_out],
        help="list each client's views with the needs that point at them",
    )
    vw.add_argument("--client", default=None, help="only this client's views (for example web)")
    vw.add_argument("--links", action="store_true", help="list each view's outgoing links and why")
    vw.add_argument(
        "--graph",
        choices=["mermaid"],
        default=None,
        help="print the links as one Mermaid flowchart per client instead of the table",
    )
    vw.add_argument("-o", "--output", default=None, help="with --graph: write to this file")
    vw.set_defaults(func=cmd_views)

    rp = sub.add_parser(
        "report",
        parents=[config],
        help="render the board as a shareable document (markdown, or an interactive HTML)",
    )
    rp.add_argument(
        "--format",
        choices=["md", "html", "csv", "jira", "confluence"],
        default="md",
        help="md (default); html: a self-contained, interactive viewer (#79); csv: one row per "
        "need; jira: wiki markup; confluence: storage format (#65)",
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
    rp.add_argument("--goal", default=None, metavar="ID", help="only needs serving this goal")
    rp.add_argument("--only-must", action="store_true", help="only must-have needs")
    rp.add_argument("--title", default=None, help="replace the heading (md only; the stamp stays)")
    rp.add_argument(
        "--hide-empty",
        action="store_true",
        help="md only: drop the explainer paragraph and an empty Open questions section",
    )
    rp.add_argument(
        "--only-open",
        action="store_true",
        help="md only: just the Open questions brief (opinions and HOLEs, must-haves first)",
    )
    rp.set_defaults(func=cmd_report)

    sy = sub.add_parser(
        "sync",
        parents=[config],
        help="run lifecycle callbacks for needs whose state changed since the last sync (#71)",
    )
    sy.add_argument(
        "--dry-run",
        action="store_true",
        help="show which transitions would fire callbacks; don't run them or write the ledger",
    )
    sy.set_defaults(func=cmd_sync)

    add_issue_parser(
        sub.add_parser("issue", help="read and write the issue register (docs/issues)")
    )
    add_mcp_parser(
        sub.add_parser("mcp", help="run prodc as an MCP server, or register it with a client")
    )

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

    df = sub.add_parser(
        "diff",
        parents=[config, json_out],
        help="diff the current board against a prior status --json snapshot",
    )
    df.add_argument("snapshot", help="path to a saved `prodc status --json` file")
    df.set_defaults(func=cmd_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.chdir is not None:
        try:
            os.chdir(args.chdir)
        except OSError as exc:
            print(f"prodc: cannot chdir to {args.chdir}: {exc}", file=sys.stderr)
            return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
