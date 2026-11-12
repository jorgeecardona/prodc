"""Text renderers for the terminal board and its sub-views.

Every ``render*`` that turns a resolved board into the lines ``prodc status`` (and the other
read commands) print, plus the column table and the state-label / column constants. Pure
formatting: it reads the resolved model and returns strings, never loads or writes.
"""

from __future__ import annotations

import datetime
import shutil
from collections.abc import Callable

from ..board import path_summary, warrant
from ..inbox import InboxItem
from ..model import (
    Decision,
    Goal,
    Issue,
    Need,
    NeedResult,
    NeedState,
    PrincipleState,
    Release,
    Role,
    ears_shape,
)
from ..status import (
    Contradiction,
    DecisionReadiness,
    Handoff,
    PrincipleReport,
    Recurrence,
    Summary,
    ViewRow,
    group_state,
    orphaned_decisions,
    rank,
    state_priority,
)
from .common import PortfolioTotals, RepoRow, brief_open

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


def provenance_counts(results: list[NeedResult]) -> dict[str, int]:
    """How many needs carry each evidence tier (primary/secondary/assumption/opinion)."""
    counts = {"primary": 0, "secondary": 0, "assumption": 0, "opinion": 0}
    for r in results:
        counts[warrant(r.need).split(":", 1)[0]] += 1
    return counts


def _provenance_line(results: list[NeedResult]) -> str:
    """Per-role evidence mix. Makes assumption-only needs (weak, but not sourceless) visible.

    The headline a PM wants is how many needs trace to a real user (primary), not just 'has any
    source'; a need resting only on an assumption is an opinion, shown here as its assumption tier.
    """
    counts = provenance_counts(results)
    return "provenance: " + "  ·  ".join(f"{counts[k]} {k}" for k in counts)


def summary_line(s: Summary) -> str:
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
    conf = f" ({r.confidence.value})" if r.confidence else ""
    return f"{_LABEL[r.state]}{star}{conf}{nm}"


def _marker(need: Need) -> str:
    """The 2-char left gutter: must beats flow when a need is both."""
    if need.must:
        return "!!"
    if need.children:
        return "⊟ "
    return "  "


def render(results: list[NeedResult], wide: bool = False) -> str:
    if not results:
        return "  (no needs)"
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)

    # Fit every column to its widest content across the WHOLE board, so columns line up
    # the same in every role block. The need column takes whatever width is left.
    id_w = max([len("id"), *(len(r.need.id) for r in results)])
    grounds_w = max([len("grounds"), *(len(_grounds_cell(r)) for r in results)])
    warrant_w = max([len("warrant"), *(len(warrant(r.need)) for r in results)])
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
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "   ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        out.append(f"\n{who}    {head}")
        out.append(f"    {_provenance_line(rs)}\n")
        for r in rs:
            out.append(
                row(
                    _marker(r.need),
                    r.need.id,
                    _grounds_cell(r),
                    _clip(r.need.text, need_w),
                    warrant(r.need),
                )
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


COLUMNS: dict[str, tuple[str, Callable[[NeedResult], str]]] = {
    "id": ("id", lambda r: r.need.id),
    "state": ("state", lambda r: _LABEL[r.state]),
    "grounds": ("grounds", lambda r: f"{r.delivered}/{r.total}" if r.total else ""),
    "text": ("need", lambda r: r.need.text),
    "who": ("who", lambda r: r.need.who or ""),
    "role": ("role", lambda r: r.need.role or ""),
    "warrant": ("warrant", lambda r: warrant(r.need)),
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


def render_columns(results: list[NeedResult], columns: list[str]) -> str:
    """A flat table of exactly the chosen columns, cut to the question asked (#40)."""
    rows = sorted(results, key=state_priority)
    cells = [[COLUMNS[c][1](r) for c in columns] for r in rows]
    headers = [COLUMNS[c][0] for c in columns]
    widths = [max([len(headers[i]), *(len(row[i]) for row in cells)]) for i in range(len(columns))]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    for row in cells:
        out.append("  ".join(row[i].ljust(widths[i]) for i in range(len(columns))))
    return "\n".join(out)


def render_orphans(orphan_map: dict[str, list[str]]) -> str:
    """The reverse report: proof units that no need references."""
    total = sum(len(v) for v in orphan_map.values())
    out = [f"\norphan proofs (claimed by no need): {total}"]
    for name in sorted(orphan_map):
        for sid in orphan_map[name]:
            out.append(f"     {name}:{sid}")
    return "\n".join(out)


def render_views(
    rows: list[ViewRow], unreachable: dict[str, int] | None = None, show_links: bool = False
) -> str:
    """The view inventory, one tree per client, with each view's needs and their state (#102).

    ``in/out`` counts the links that end and start at the view (#107). ``show_links`` lists each
    view's outgoing links under it with their reason (#104). ``unreachable`` maps a client to the
    number of views no entry view leads to (#105).
    """
    out: list[str] = []
    client: str | None = None
    for row in rows:
        if row.view.client != client:
            client = row.view.client
            out.append(f"{'' if not out else chr(10)}{client}")
            out.append(
                f"  {'view':<44} {'kind':<10} {'section':<10} {'state':<10} {'in/out':<7} needs"
            )
        flags = [
            f
            for f, on in (
                ("unjustified", not row.justified),
                ("untyped", row.untyped),
                ("orphan", row.orphan),
            )
            if on
        ]
        name = "  " * row.depth + row.view.id
        state = _LABEL[row.state] if row.state is not None else "-"
        links = f"{len(row.inbound)}/{len(row.outbound)}"
        line = (
            f"  {name:<44} {row.view.kind or '-':<10} {row.view.section or '-':<10} "
            f"{state:<10} {links:<7} {', '.join(row.needs) or '-'}"
        )
        out.append(line + (f"  [{', '.join(flags)}]" if flags else ""))
        if show_links:
            pad = "  " * (row.depth + 2)
            for lk in row.outbound:
                out.append(f"{pad}-> {lk.target}" + (f": {lk.why}" if lk.why else ""))
    unjustified = sum(1 for r in rows if not r.justified)
    untyped = sum(1 for r in rows if r.untyped)
    orphans = sum(1 for r in rows if r.orphan)
    out.append(
        f"\nviews: {len(rows)}, unjustified: {unjustified}, untyped: {untyped}, orphan: {orphans}"
    )
    for c, n in (unreachable or {}).items():
        out.append(f"{c}: unreachable from an entry view: {n}")
    return "\n".join(out)


def _mermaid_text(text: str) -> str:
    return text.replace('"', "#quot;").replace("|", "#124;").replace("\n", " ")


def _view_class(row: ViewRow) -> str:
    if not row.justified:
        return "unjustified"
    if row.view.needless_ok:
        return "noneed"
    if row.state is None:
        return "plain"
    return "delivered" if row.state is NeedState.DELIVERED else "gap"


def render_views_mermaid(rows: list[ViewRow]) -> str:
    """The view links as one Mermaid flowchart per client, in a Markdown section each (#104).

    A node is a view, classed by state (``delivered``, ``gap``, ``unjustified``, ``noneed``,
    ``plain``). A link is an arrow labelled with its ``why``. Containment is a dotted line from
    the parent. Views nobody links to sit in their own ``orphans`` subgraph.
    """
    out: list[str] = []
    for client in dict.fromkeys(r.view.client for r in rows):
        mine = [r for r in rows if r.view.client == client]
        node = {r.view.id: f"v{i}" for i, r in enumerate(mine)}
        lines = ["flowchart LR"]

        decl = {
            r.view.id: f'{node[r.view.id]}["{_mermaid_text(r.view.id)}"]:::{_view_class(r)}'
            for r in mine
        }
        lines += [f"  {decl[r.view.id]}" for r in mine if not r.orphan]
        orphans = [r for r in mine if r.orphan]
        if orphans:
            lines.append('  subgraph orphans ["no inbound link"]')
            lines += [f"    {decl[r.view.id]}" for r in orphans]
            lines.append("  end")
        for r in mine:
            if r.view.parent in node:
                lines.append(f"  {node[r.view.parent]} -.- {node[r.view.id]}")
        for r in mine:
            for lk in r.outbound:
                if lk.target not in node:
                    continue
                label = f'|"{_mermaid_text(lk.why)}"|' if lk.why else ""
                lines.append(f"  {node[r.view.id]} -->{label} {node[lk.target]}")
        lines += [
            "  classDef delivered fill:#d3f9d8,stroke:#2f9e44",
            "  classDef gap fill:#ffe3e3,stroke:#e03131",
            "  classDef unjustified fill:#fff3bf,stroke:#f08c00",
            "  classDef noneed fill:#e9ecef,stroke:#868e96",
            "  classDef plain fill:#fff,stroke:#868e96",
        ]
        out.append(f"## {client}\n\n```mermaid\n" + "\n".join(lines) + "\n```")
    return "\n\n".join(out)


def render_out_of_scope(results: list[NeedResult]) -> str:
    """Non-product needs (infra/NFR/internal): listed, not counted, never a HOLE (#48)."""
    out = [f"\nout of scope (not product, excluded from coverage): {len(results)}"]
    for r in sorted(results, key=lambda x: x.need.id):
        out.append(f"  {r.need.id:<12} {_LABEL[r.state]:<10} {r.need.text[:54]}")
    return "\n".join(out)


def render_goals(goal_cov: list[tuple[Goal, Summary]], ungoaled: list[NeedResult]) -> str:
    """Per-goal coverage with a derived state and target, plus the needs that serve no objective (#27, #80)."""
    today = datetime.date.today().isoformat()
    out = ["\ngoals (objectives needs trace up to):"]
    for goal, gsum in goal_cov:
        state = group_state(gsum)
        metric = f"  [{goal.metric}]" if goal.metric else ""
        pct = round(gsum.coverage * 100)
        overdue = (
            goal.target is not None and goal.target < today and state is not NeedState.DELIVERED
        )
        target = ""
        if goal.target:
            target = f"  ⚠ overdue {goal.target}" if overdue else f"  target {goal.target}"
        out.append(
            f"  {goal.id:<12} {_LABEL[state]:<10} {gsum.delivered}/{gsum.total} ({pct}%)"
            f"{metric}{target}  {goal.text}"
        )
    if ungoaled:
        ids = ", ".join(r.need.id for r in ungoaled)
        out.append(f"  ⚠ {len(ungoaled)} need(s) serve no goal: {ids}")
    return "\n".join(out)


def render_releases(rel_cov: list[tuple[Release, Summary]]) -> str:
    """Per-release coverage, in ship order (#30)."""
    out = ["\nreleases (ship order):"]
    for rel, rsum in rel_cov:
        pct = round(rsum.coverage * 100)
        title = f"  {rel.text}" if rel.text else ""
        out.append(f"  {rel.id:<12} {rsum.delivered}/{rsum.total} ({pct}%){title}")
    return "\n".join(out)


def render_roles(role_cov: list[tuple[Role, Summary]], unroled: list[NeedResult]) -> str:
    """The roster: coverage per declared role, orphan roles (0 needs), and unroled needs (#52)."""
    out = ["\nroles (the roster: who plays which function):"]
    for role, rsum in role_cov:
        if rsum.total:
            pct = round(rsum.coverage * 100)
            out.append(f"  {role.id:<12} {rsum.delivered}/{rsum.total} ({pct}%)  {role.text}")
        else:
            out.append(f"  {role.id:<12}   (orphan role: no need plays it yet)  {role.text}")
    if unroled:
        ids = ", ".join(r.need.id for r in unroled)
        out.append(
            f"  ⚠ need(s) with a who but no role: {ids} "
            "(set role: <role-id> on the need, or role: at the top of the file)"
        )
    return "\n".join(out)


def render_handoffs(hos: list[Handoff]) -> str:
    """Derived cross-role journey: where a flow's ordered steps pass between roles (#52)."""
    out = [f"\nhandoffs (derived from ordered cross-role flows): {len(hos)}"]
    for h in hos:
        out.append(
            f"  {h.flow.id:<12} {h.from_role} → {h.to_role}    {h.from_need.id} → {h.to_need.id}"
        )
    return "\n".join(out)


def render_recurrence(recs: list[Recurrence]) -> str:
    """Baselines shared across clients, most-shared first (#32 recurrence view)."""
    out = [f"\nrecurrence (needs shared across clients): {len(recs)}"]
    for rec in recs:
        who = f": {', '.join(rec.clients)}" if rec.clients else ""
        out.append(
            f"  {rec.baseline.id:<12} {rec.count} client{'s' if rec.count != 1 else ''}{who}"
            f"    {rec.baseline.text[:60]}"
        )
    return "\n".join(out)


def render_principles(reports: list[PrincipleReport]) -> str:
    """The product vision as principles, with the decisions resting on each and which have gone stale.

    An principle is held as given, not validated; ``declined`` are the needs withdrawn citing it, and
    ``stale`` (the ripple) are those decided before its latest ``revised_at``, flagged to re-review.
    """
    out = ["\nprinciples (the vision, held as given):"]
    for rep in reports:
        a = rep.principle
        rev = f"revised {a.revised_at}" if a.revised_at else "undated"
        scope = "" if a.scope == "product" else f"[{a.scope}] "
        flag = "⚠ " if rep.state in (PrincipleState.VIOLATED, PrincipleState.BROKEN) else ""
        out.append(f"  {a.id:<6} {flag}{rep.state.value.upper():<9} {scope}{rev}  {a.text}")
        if a.implemented_in:
            out.append(f"        implemented in: {a.implemented_in}")
        if rep.declined:
            out.append(f"        declined: {', '.join(n.id for n in rep.declined)}")
        if rep.stale:
            ids = ", ".join(n.id for n in rep.stale)
            out.append(f"        ⚠ decided before the latest revision: {ids}: re-review")
    tally = _principle_tally(reports)
    if tally:
        out.append(f"  {tally}")
    return "\n".join(out)


def _principle_tally(reports: list[PrincipleReport]) -> str:
    """A per-scope ENFORCED/STATED/… count line, scopes and states in declared enum order (#89)."""
    by_scope: dict[str, dict[PrincipleState, int]] = {}
    for rep in reports:
        counts = by_scope.setdefault(rep.principle.scope, {})
        counts[rep.state] = counts.get(rep.state, 0) + 1
    parts: list[str] = []
    for scope, counts in by_scope.items():
        inner = ", ".join(f"{counts[s]} {s.value}" for s in PrincipleState if counts.get(s))
        parts.append(f"{scope}: {inner}")
    return "  ·  ".join(parts)


def render_contradictions(contras: list[Contradiction]) -> str:
    """Unresolved contradictions on the board: two needs in tension the vision has not decided."""
    out = ["\ncontradictions (two needs in tension: the vision has not decided):"]
    for c in contras:
        out.append(f"  {c.a.id} vs {c.b.id}    {c.a.text[:32]}  /  {c.b.text[:32]}")
    return "\n".join(out)


def _readiness_tag(r: DecisionReadiness | None) -> str:
    if r is None:
        return ""
    return f" BLOCKED: {', '.join(r.open_refs)}" if r.blocked else " READY"


def render_decisions(
    decisions: list[Decision],
    needs: list[Need],
    readiness: dict[str, DecisionReadiness] | None = None,
) -> str:
    """The solution chosen for each need (OST), what it rejected, and the needs it serves.

    Shows the decisions still in force (a superseded one is off the board, its record kept). A
    decision left serving only withdrawn/non-product needs is flagged orphaned (the 'how' without its
    'what').
    """
    orphans = {d.id for d in orphaned_decisions(decisions, needs)}
    active = sorted((d for d in decisions if d.withdrawn is None), key=lambda x: x.id)
    out = ["\ndecisions (the solution chosen for a need, how it gets built):"]
    for d in active:
        tag = (" (proposed)" if d.draft else "") + _readiness_tag((readiness or {}).get(d.id))
        out.append(f"  {d.id:<6}{tag} {d.text}")
        out.append(f"        serves: {', '.join(d.needs)}")
        if d.alternatives:
            out.append(f"        over: {', '.join(d.alternatives)}")
        if d.principles:
            out.append(f"        rests on: {', '.join(d.principles)}")
        if d.id in orphans:
            out.append("        ⚠ serves only withdrawn/non-product needs. Re-tie or withdraw")
    return "\n".join(out)


def render_decision_show(
    d: Decision,
    needs: list[Need],
    warnings: list[str],
    readiness: DecisionReadiness | None = None,
) -> str:
    """One decision as a citable answer (#95): the chosen solution, what it serves and rejected.

    The decision counterpart of :func:`render_show`. ``prodc show D-1`` answers "how is this
    built, over what, and why" the way ``prodc show N-1`` answers "is this delivered".
    """
    by_id = {n.id: n for n in needs}
    tag = " (proposed)" if d.draft else ""
    lines = [f"{d.id}{tag}{_readiness_tag(readiness)}  {d.text}"]
    if readiness is not None:
        settled = len(readiness.waits) - len(readiness.open_refs)
        lines.append(f"  awaits ({settled} of {len(readiness.waits)} settled):")
        lines += [f"    - {w.ref:<20} {w.state.value:<10} {w.detail}" for w in readiness.waits]
    lines.append("  serves:")
    for nid in d.needs:
        n = by_id.get(nid)
        lines.append(f"    - {nid}: {n.text}" if n else f"    - {nid}")
    if d.alternatives:
        lines.append(f"  over: {', '.join(d.alternatives)}")
    if d.consequences:
        lines.append(f"  consequences: {d.consequences}")
    if d.principles:
        lines.append(f"  rests on: {', '.join(d.principles)}")
    if d.decided_at:
        lines.append(f"  decided: {d.decided_at}")
    if d.withdrawn:
        lines.append(
            f"  withdrawn ({d.withdrawn.kind.value}, {d.withdrawn.date}): {d.withdrawn.reason}"
        )
    lines += [f"  ⚠ {w}" for w in warnings]
    return "\n".join(lines)


def render_show(
    r: NeedResult,
    importance_label: str | None = None,
    decisions: list[Decision] | None = None,
    issues: list[Issue] | None = None,
) -> str:
    """One need as a citable answer. Drop it into a thread."""
    need = r.need
    who = need.who or "(unassigned)"
    who += f" ({need.role})" if need.role else ""
    nm = f"  {r.delivered}/{r.total}" if r.total else ""
    lines = [
        f"{need.id}{'  !!' if need.must else ''}{'  (draft)' if need.draft else ''}  {need.text}",
        f"  who: {who}",
        f"  grounds: {_LABEL[r.state]}{nm}    warrant: {warrant(need)}",
        *(
            [f"  confidence: {r.confidence.value} ({'; '.join(r.confidence_detail)})"]
            if r.confidence
            else []
        ),
        f"  shape: {ears_shape(need.text).value}",
    ]
    if need.answer:
        lines.append(f"  answer: {need.answer.value}")
    if need.withdrawn:
        w = need.withdrawn
        of = f" of {w.of}" if w.of else ""
        tag = "" if w.kind.value == "wont_do" else f" [{w.kind.value}{of}]"
        per = f" per {w.principle}" if w.principle else ""
        lines.append(f"  withdrawn{tag}{per}: {w.reason} ({w.date})")
    if need.description:
        lines.append(f"  description: {need.description}")
    if need.importance is not None:
        label = f" ({importance_label})" if importance_label else ""
        seen = f", set {need.importance_set_at}" if need.importance_set_at else ""
        lines.append(f"  importance: {need.importance}{label}{seen}")
    if need.goal:
        lines.append(f"  goal: {need.goal}")
    if need.outcome:
        o = need.outcome
        said = "landed" if o.landed else "did not land"
        seen = f": {o.evidence}" if o.evidence else ""
        lines.append(f"  outcome: {said} ({o.who}, {o.date}){seen}")
    path = path_summary(r)
    if path:
        lines.append(f"  path: {path}")
    if need.release:
        lines.append(f"  release: {need.release}")
    if need.claim:
        lines.append(f"  claim: {need.claim}")
    if need.attestation:
        a = need.attestation
        tag = " (AI)" if a.kind.value == "ai" else ""
        verdict = f" ({a.verdict})" if a.verdict else ""
        lines.append(f"  attested: {a.who}{tag} ({a.date}){verdict}")
        if a.comment:
            lines.append(f"    ↳ {a.comment}")
    elif need.proofs and r.state is NeedState.DELIVERED:
        lines.append("  attested: (none; proof link not reviewed, #13)")
    if need.sources:
        lines.append("  sources:")
        for s in need.sources:
            bits = [s.kind.value]
            bits += [
                f"{k}={v}"
                for k, v in (
                    ("who", s.who),
                    ("role", s.role),
                    ("date", s.date),
                    ("locator", s.ref),
                )
                if v
            ]
            line = "    - " + "  ".join(bits)
            lines.append(line + (f'  "{s.quote}"' if s.quote else ""))
    else:
        lines.append("  sources: (none, opinion)")
    if need.children:
        rendered = ", ".join(c.id if c.step is None else f"{c.id}@{c.step}" for c in need.children)
        lines.append(f"  children: {rendered}")
    if need.contradicts:
        lines.append(f"  contradicts: {', '.join(need.contradicts)}")
    if need.tags:
        lines.append(f"  tags: {', '.join(need.tags)}")
    if need.seam:
        lines.append(f"  seam: {', '.join(need.seam)}")
    if need.proofs:
        lines.append("  proofs:")
        lines += [f"    - {d}" for d in r.detail]
    elif not need.children:
        why = f", {need.expects.awaiting}" if need.expects else ""
        lines.append(f"  proofs: (none, HOLE{why})")
    if decisions:
        lines.append("  decisions (how it's built):")
        for d in decisions:
            alt = f"  (over {', '.join(d.alternatives)})" if d.alternatives else ""
            lines.append(f"    - {d.id}: {d.text}{alt}")
    if issues:
        lines.append("  issues (the work):")
        lines += [f"    - {i.id} [{i.status}] {i.title}" for i in issues]
    lines += [f"  ⚠ {w}" for w in r.warnings]
    return "\n".join(lines)


def render_issues(issues: list[Issue], by_state: dict[str, str]) -> str:
    """The issue list: id, recorded status, the state of the needs it serves, and its title (#36)."""
    out = [f"  {'issue':<52} {'status':<12} {'needs':<26} title"]
    for i in issues:
        needs = ", ".join(f"{n}:{by_state.get(n, '?')}" for n in i.needs) or "(none)"
        flag = "" if i.needs else "  [no need]"
        out.append(f"  {i.id[:52]:<52} {i.status:<12} {needs[:26]:<26} {i.title}{flag}")
    out.append(f"\nissues: {len(issues)}, serving no need: {sum(1 for i in issues if not i.needs)}")
    return "\n".join(out)


def render_brief(
    client: str,
    results: list[NeedResult],
    stale: list[tuple[NeedResult, int]] | None = None,
) -> str:
    open_ = brief_open(results)
    out = [f"brief {client}: {len(open_)} open question{'s' if len(open_) != 1 else ''}"]
    if not open_:
        out.append("  (nothing open: every applicable need has evidence and a proof)")
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
    if stale:
        out.append(f"  confirm still wanted ({len(stale)} with evidence past the stale threshold):")
        for r, age in sorted(stale, key=lambda t: (-t[1], t[0].need.id)):
            out.append(f"    ~ {r.need.id:<12} {age}d old   {r.need.text}")
    return "\n".join(out)


def _importance_cell(need: Need) -> str:
    """The importance column; a value entered by a weak-warrant author is flagged a guess."""
    if need.importance is None:
        return ""
    # weak = no external evidence (only an assumption, or nothing): the author is guessing
    weak = need.is_opinion
    return f"imp={need.importance}{' (guess)' if weak else ''}"


def render_plan(
    results: list[NeedResult],
    recurrence_counts: dict[str, int],
    *,
    revisit: bool = False,
    now: frozenset[str] = frozenset(),
    current: Release | None = None,
) -> str:
    ranked = rank(results, recurrence_counts, now)
    header = (
        f"plan: revisit: {len(ranked)} need(s) with undated or stale importance (#59)"
        if revisit
        else "plan: ranked backlog (must + state + evidence + recurrence, importance refines)"
    )
    out = [header]
    if current is not None:
        out.append(f"  now: release {current.id} ({current.text})")
    for i, r in enumerate(ranked, 1):
        if now and i > 1 and ranked[i - 2].need.id in now and r.need.id not in now:
            out.append("  ---- later " + "-" * 40)
        bang = "!!" if r.need.must else "  "
        imp = _importance_cell(r.need)
        out.append(
            f"  {i:>3}. {bang} {r.need.id:<12} {_LABEL[r.state]:<10} "
            f"{warrant(r.need):<16} {imp:<12} {r.need.text[:48]}"
        )
    return "\n".join(out)


def render_portfolio(rows: list[RepoRow], totals: PortfolioTotals | None = None) -> str:
    if not rows:
        return "  no boards found"
    out = [f"  {'repo':<18} {'cov':>4}  {'must-HOLE':>9}  {'BROKEN':>6}   prov prim/sec/asm/op"]
    for row in rows:
        if row.error is not None:
            out.append(f"  {row.repo:<18} error: {row.error}")
            continue
        p = row.provenance
        prov = f"{p['primary']}/{p['secondary']}/{p['assumption']}/{p['opinion']}"
        cov = f"{round(row.coverage * 100)}%"
        out.append(f"  {row.repo:<18} {cov:>4}  {row.must_hole:>9}  {row.broken:>6}   {prov}")
    if totals is not None:
        cov = f"{round(totals.coverage * 100)}%"
        label = f"TOTAL ({totals.boards} boards)"
        out.append(f"  {'─' * 48}")
        out.append(
            f"  {label:<18} {cov:>4}  {totals.must_hole:>9}  {totals.broken:>6}   "
            f"{totals.delivered}/{totals.total} delivered"
        )
    return "\n".join(out)


def render_inbox(items: list[InboxItem]) -> str:
    """The decision inbox as text: each open item, why it is open, and its options (#113)."""
    if not items:
        return "inbox: nothing waits on you"
    lines = [f"inbox: {len(items)} decision(s) wait on you", ""]
    for i in items:
        lines.append(f"  {i.need_id}  {i.reason}")
        lines.append(f"      {' '.join(i.text.split())}")
        for o in i.options:
            lines.append(f"      - {o.label}: {o.command}")
        lines.append("")
    return "\n".join(lines).rstrip()
