"""Render the board as a readable document — `prodc report` (markdown).

The board (`prodc status`) is built for a terminal; a product manager often wants a file they can
read, share, or print. This renders the same resolved model as a markdown document: a summary, the
needs grouped by who, the goals/releases/roster/handoffs, and the open questions. It reuses the
status engine, so the document never drifts from the board. Dependency-free (PDF/HTML conversion is
left to the reader's own tooling — prodc stays pyyaml-only).
"""

from __future__ import annotations

from datetime import date

from .config import Config
from .model import Model, NeedResult, NeedState
from .status import (
    goal_report,
    handoffs,
    recurrence,
    release_report,
    resolve,
    role_report,
    state_priority,
    summarize,
)

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


def _warrant(r: NeedResult) -> str:
    """The user signal behind a need: its strongest source kind, or 'opinion' when unsourced."""
    strongest = r.need.strongest_kind
    return strongest.value if strongest is not None else "opinion"


def _summary_line(total: int, delivered: int, coverage: float, must_hole: int, broken: int) -> str:
    bits: list[str] = []
    if must_hole:
        bits.append(f"{must_hole} must-have gap{'s' if must_hole != 1 else ''}")
    if broken:
        bits.append(f"{broken} broken proof{'s' if broken != 1 else ''}")
    gaps = "; ".join(bits) if bits else "no blocking gaps"
    return f"**{delivered} of {total} delivered** ({round(coverage * 100)}%) — {gaps}."


def render_markdown(
    cfg: Config, model: Model, *, client: str | None = None, rev: str | None = None
) -> str:
    """Render the resolved board as a markdown report.

    ``client`` scopes nothing yet beyond the heading note — the caller passes the already-scoped
    model (so `--client` reuses the same filter the board uses). ``rev`` is an optional short git
    revision to stamp the report, so a printed copy says which state it reflects.
    """
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    summary = summarize(results)
    goal_cov, ungoaled = goal_report(results, list(model.goals))
    rel_cov = release_report(results, list(model.releases))
    role_cov, unroled = role_report(results, list(model.roles))
    hos = handoffs(needs)
    recs = recurrence(needs)

    scope = f" — {client}" if client else ""
    stamp = date.today().isoformat() + (f" · {rev}" if rev else "")
    out: list[str] = [
        f"# {cfg.root.name}{scope} — product status",
        "",
        f"_{stamp}_",
        "",
        _summary_line(
            summary.total, summary.delivered, summary.coverage, summary.must_hole, summary.broken
        ),
        "",
        "A need is something a person wants; it is an **opinion** until evidence backs it, and "
        "**delivered** only when a test proves it. A **HOLE** is an honest gap — a need no test "
        "proves yet — not a failure.",
    ]

    # Needs grouped by who, like the board.
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        if not r.need.product:
            continue
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)
    if groups:
        out += ["", "## Needs", ""]
        for who in sorted(groups):
            rs = sorted(groups[who], key=state_priority)
            label = next((x.need.label for x in rs if x.need.label), None)
            out.append(f"### {who}" + (f" ({label})" if label else ""))
            out.append("")
            out.append("| need | state | text | user signal |")
            out.append("|---|---|---|---|")
            for r in rs:
                must = "**(must)** " if r.need.must else ""
                text = r.need.text.replace("|", "\\|")
                out.append(f"| {r.need.id} | {_LABEL[r.state]} | {must}{text} | {_warrant(r)} |")
            out.append("")

    if model.goals:
        out += ["## Goals", "", "| goal | delivered | goal |", "|---|---|---|"]
        for goal, gsum in goal_cov:
            out.append(
                f"| {goal.id} | {gsum.delivered}/{gsum.total} ({round(gsum.coverage * 100)}%) "
                f"| {goal.text} |"
            )
        if ungoaled:
            out.append("")
            out.append(
                f"_{len(ungoaled)} need(s) serve no goal: {', '.join(r.need.id for r in ungoaled)}._"
            )
        out.append("")

    if model.releases:
        out += ["## Releases (ship order)", "", "| release | delivered | name |", "|---|---|---|"]
        for rel, rsum in rel_cov:
            out.append(
                f"| {rel.id} | {rsum.delivered}/{rsum.total} ({round(rsum.coverage * 100)}%) "
                f"| {rel.text} |"
            )
        out.append("")

    if model.roles:
        out += ["## Roster", "", "| role | delivered | role |", "|---|---|---|"]
        for role, rsum in role_cov:
            cov = (
                f"{rsum.delivered}/{rsum.total} ({round(rsum.coverage * 100)}%)"
                if rsum.total
                else "— (no need yet)"
            )
            out.append(f"| {role.id} | {cov} | {role.text} |")
        if unroled:
            out.append("")
            out.append(
                f"_Need(s) whose who plays no declared role: {', '.join(r.need.id for r in unroled)}._"
            )
        out.append("")

    if hos:
        out += ["## Handoffs", "", "| flow | from → to | steps |", "|---|---|---|"]
        for h in hos:
            out.append(
                f"| {h.flow.id} | {h.from_role} → {h.to_role} | {h.from_need.id} → {h.to_need.id} |"
            )
        out.append("")

    if recs:
        out += ["## Recurring across clients", "", "| baseline | clients | want |", "|---|---|---|"]
        for rec in recs:
            out.append(
                f"| {rec.baseline.id} | {rec.count} | {rec.baseline.text.replace('|', chr(92) + '|')} |"
            )
        out.append("")

    # Open questions: the brief — opinions (no evidence) or HOLEs (no proof), must-haves first.
    open_ = [
        r for r in results if r.need.product and (r.need.is_opinion or r.state is NeedState.HOLE)
    ]
    open_.sort(key=lambda r: (not r.need.must, r.need.id))
    out += ["## Open questions", ""]
    if not open_:
        out.append("_Nothing open — every need has evidence and a proof._")
    else:
        for r in open_:
            gaps = ", ".join(
                g
                for g in (
                    "no evidence" if r.need.is_opinion else "",
                    "no proof" if r.state is NeedState.HOLE else "",
                )
                if g
            )
            must = "**(must)** " if r.need.must else ""
            out.append(f"- {must}`{r.need.id}` — {r.need.text} _({gaps})_")
    out.append("")
    return "\n".join(out)
