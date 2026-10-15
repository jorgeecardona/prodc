"""Text renderers for the terminal board and its sub-views.

Every ``render*`` that turns a resolved board into the lines ``prodc status`` (and the other
read commands) print, plus the column table and the state-label / column constants. Pure
formatting: it reads the resolved model and returns strings, never loads or writes.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable

from ..board import warrant as _warrant
from ..model import (
    Goal,
    Model,
    Need,
    NeedResult,
    NeedState,
    Release,
    Role,
    ears_shape,
)
from ..status import Handoff, Recurrence, Summary, rank, state_priority
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
        counts[_warrant(r.need).split(":", 1)[0]] += 1
    return counts


def _provenance_line(results: list[NeedResult]) -> str:
    """Per-role evidence mix — makes assumption-only needs (weak, but not sourceless) visible.

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
    return f"{_LABEL[r.state]}{star}{nm}"


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


COLUMNS: dict[str, tuple[str, Callable[[NeedResult], str]]] = {
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


def render_columns(results: list[NeedResult], columns: list[str]) -> str:
    """A flat table of exactly the chosen columns — the board cut to the question asked (#40)."""
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


def render_out_of_scope(results: list[NeedResult]) -> str:
    """Non-product needs (infra/NFR/internal): listed, not counted, never a HOLE (#48)."""
    out = [f"\nout of scope (not product — excluded from coverage): {len(results)}"]
    for r in sorted(results, key=lambda x: x.need.id):
        out.append(f"  {r.need.id:<12} {_LABEL[r.state]:<10} {r.need.text[:54]}")
    return "\n".join(out)


def render_goals(goal_cov: list[tuple[Goal, Summary]], ungoaled: list[NeedResult]) -> str:
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


def render_handoffs(hos: list[Handoff]) -> str:
    """Derived cross-role journey: where a flow's ordered steps pass between roles (#52)."""
    out = [f"\nhandoffs (derived from ordered cross-role flows): {len(hos)}"]
    for h in hos:
        out.append(
            f"  {h.flow.id:<12} {h.from_role} → {h.to_role}    {h.from_need.id} → {h.to_need.id}"
        )
    return "\n".join(out)


def render_recurrence(recs: list[Recurrence]) -> str:
    """Baselines shared across clients, most-shared first — the #32 recurrence view."""
    out = [f"\nrecurrence (needs shared across clients): {len(recs)}"]
    for rec in recs:
        who = f" — {', '.join(rec.clients)}" if rec.clients else ""
        out.append(
            f"  {rec.baseline.id:<12} {rec.count} client{'s' if rec.count != 1 else ''}{who}"
            f"    {rec.baseline.text[:60]}"
        )
    return "\n".join(out)


def render_show(r: NeedResult, importance_label: str | None = None) -> str:
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
    if need.answer:
        lines.append(f"  answer: {need.answer.value}")
    if need.withdrawn:
        lines.append(f"  withdrawn: {need.withdrawn.reason} ({need.withdrawn.date})")
    if need.description:
        lines.append(f"  description: {need.description}")
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
                for k, v in (
                    ("who", s.who),
                    ("role", s.role),
                    ("date", s.date),
                    ("locator", s.locator),
                )
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


def render_brief(client: str, results: list[NeedResult]) -> str:
    open_ = brief_open(results)
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


def _importance_cell(need: Need) -> str:
    """The importance column; a value entered by a weak-warrant author is flagged a guess."""
    if need.importance is None:
        return ""
    # weak = no external evidence (only an assumption, or nothing) — the author is guessing
    weak = need.is_opinion
    return f"imp={need.importance}{' (guess)' if weak else ''}"


def render_plan(results: list[NeedResult], recurrence_counts: dict[str, int]) -> str:
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


def render_argument(model: Model, defects: list[str]) -> str:
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
