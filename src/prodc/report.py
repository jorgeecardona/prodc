"""Render the board as a readable document: ``prodc report`` (markdown).

The board (`prodc status`) is built for a terminal; a product manager often wants a file they can
read, share, or print. This renders the same resolved model as a markdown document: a summary, the
needs grouped by who, the goals/releases/roster/handoffs, and the open questions. It reuses the
status engine, so the document never drifts from the board. Dependency-free (PDF/HTML conversion is
left to the reader's own tooling: prodc stays pyyaml-only).
"""

from __future__ import annotations

import re
from datetime import date

from .adapters import StorybookAdapter
from .board import gather, path_summary
from .config import Config
from .glossary import collisions
from .model import Model, NeedResult, NeedState
from .status import active_decisions, group_state, state_priority

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


# (pattern, name) in order: the first pattern that matches a source locator names its type (#68).
_SOURCE_TYPES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), name)
    for p, name in (
        (r"/merge_requests/\d+|/pull/\d+|![0-9]+$", "merge request"),
        (r"/issues/\d+|/work_items/\d+|/browse/|(?-i:\b[A-Z][A-Z0-9]+-\d+\b)", "ticket"),
        (r"slack\.com/archives|discord\.com/channels|t\.me/|matrix\.to", "message"),
        (r"^mailto:|^mail:|\.eml\b|^<[^>]+@[^>]+>$", "email"),
        (r"canny\.io|productboard|uservoice|/feedback/|reddit\.com|news\.ycombinator", "post"),
    )
)


def source_type(locator: str | None) -> str | None:
    """The concrete type of a source (ticket, post, message, email...), read from its locator.

    None when the locator is missing or matches no known shape; the caller falls back to the
    source kind. Only reads the text: it never opens the locator.
    """
    if not locator:
        return None
    return next((name for pat, name in _SOURCE_TYPES if pat.search(locator)), None)


def display_title(identifier: str) -> str:
    """An identifier as a human label: ``safety-analyst`` becomes ``Safety analyst``.

    A plain word is returned as written, so a name like ``jordan`` is not rewritten.
    """
    if "-" not in identifier and "_" not in identifier:
        return identifier
    words = re.sub(r"[-_]+", " ", identifier).strip()
    return words[:1].upper() + words[1:]


def _warrant(r: NeedResult) -> str:
    """The user signal behind a need: its strongest source kind, or 'opinion' when unsourced.

    The kind is followed by the concrete type of the first strongest source that has one, for
    example ``secondary (ticket)``.
    """
    strongest = r.need.strongest_kind
    if strongest is None:
        return "opinion"
    kinds = (source_type(s.locator) for s in r.need.sources if s.kind is strongest)
    typed = next((t for t in kinds if t), None)
    return f"{strongest.value} ({typed})" if typed else strongest.value


def _summary_line(total: int, delivered: int, coverage: float, must_hole: int, broken: int) -> str:
    bits: list[str] = []
    if must_hole:
        bits.append(f"{must_hole} must-have gap{'s' if must_hole != 1 else ''}")
    if broken:
        bits.append(f"{broken} broken proof{'s' if broken != 1 else ''}")
    gaps = "; ".join(bits) if bits else "no blocking gaps"
    return f"**{delivered} of {total} delivered** ({round(coverage * 100)}%): {gaps}."


def _open_questions(results: list[NeedResult], *, hide_empty: bool) -> list[str]:
    """The Open questions section: opinions (no evidence) or HOLEs (no proof), must-haves first.

    Empty list when there is nothing open and ``hide_empty`` is set.
    """
    open_ = [
        r
        for r in results
        if r.need.product
        and not r.need.is_withdrawn
        and (r.need.is_opinion or r.state is NeedState.HOLE)
    ]
    open_.sort(key=lambda r: (not r.need.must, r.need.id))
    if not open_:
        return (
            []
            if hide_empty
            else [
                "## Open questions",
                "",
                "_Nothing open: every need has evidence and a proof._",
                "",
            ]
        )
    out = ["## Open questions", ""]
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
        out.append(f"- {must}`{r.need.id}`: {r.need.text} _({gaps})_")
    out.append("")
    return out


def story_links(cfg: Config, results: list[NeedResult]) -> list[tuple[str, str, str]]:
    """``(need id, story id, url)`` for every Storybook proof, when its table sets ``url``.

    A component locator links to its first story, the page a reviewer opens first.
    """
    books = {n: a for n, a in cfg.adapters.items() if isinstance(a, StorybookAdapter)}
    out: list[tuple[str, str, str]] = []
    for r in results:
        for proof in r.need.proofs:
            name, _, payload = proof.partition(":")
            book = books.get(name)
            if book is None:
                continue
            story = (
                payload
                if "--" in payload
                else next((s.id for s in book.load().of_component(payload)), None)
            )
            url = book.story_url(story) if story else None
            if story and url:
                out.append((r.need.id, story, url))
    return out


def render_markdown(
    cfg: Config,
    model: Model,
    *,
    client: str | None = None,
    rev: str | None = None,
    title: str | None = None,
    hide_empty: bool = False,
    only_open: bool = False,
) -> str:
    """Render the resolved board as a markdown report.

    ``client`` scopes nothing yet beyond the heading note. The caller passes the already-scoped
    model (so `--client` reuses the same filter the board uses). ``rev`` is an optional short git
    revision to stamp the report, so a printed copy says which state it reflects. ``title``
    replaces the heading (the date stamp stays). ``hide_empty`` drops the explainer paragraph and
    an Open questions section with nothing in it. ``only_open`` renders the heading, the stamp and
    the Open questions section alone: the pre-meeting agenda (#67).
    """
    board = gather(cfg, model)
    results = board.results
    summary = board.summary
    goal_cov, ungoaled = board.goal_cov, board.ungoaled
    rel_cov = board.rel_cov
    role_cov, unroled = board.role_cov, board.unroled
    hos = board.handoffs
    recs = board.recurrence

    scope = f": {client}" if client else ""
    stamp = date.today().isoformat() + (f" · {rev}" if rev else "")
    heading = f"# {title or f'{cfg.board_name}{scope}: product status'}"
    out: list[str] = [heading, "", f"_{stamp}_", ""]
    if not only_open:
        out += [
            _summary_line(
                summary.total,
                summary.delivered,
                summary.coverage,
                summary.must_hole,
                summary.broken,
            )
        ]
        if not hide_empty:
            out += [
                "",
                "A need is something a person wants; it is an **opinion** until evidence backs "
                "it, and **delivered** only when a test proves it. A **HOLE** is an honest gap "
                "(a need no test proves yet), not a failure.",
            ]

    # Needs grouped by who, like the board. A withdrawn need (#74) is off the active board, so
    # it is dropped here (its trace is the YAML record and `prodc show`), never shown as a gap.
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        if not r.need.product or r.need.is_withdrawn:
            continue
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)
    if only_open:
        return "\n".join(out + _open_questions(results, hide_empty=False))
    if groups:
        out += ["", "## Needs", ""]
        for who in sorted(groups):
            rs = sorted(groups[who], key=state_priority)
            out.append(f"### {display_title(who)}")
            out.append("")
            out.append("| need | state | text | user signal |")
            out.append("|---|---|---|---|")
            for r in rs:
                must = "**(must)** " if r.need.must else ""
                text = r.need.text.replace("|", "\\|")
                conf = f" ({r.confidence.value})" if r.confidence else ""
                out.append(
                    f"| {r.need.id} | {_LABEL[r.state]}{conf} | {must}{text} | {_warrant(r)} |"
                )
            out.append("")

    # Stories: the rendered component state behind each Storybook proof, so a reviewer reads
    # the need and opens what it looks like.
    links = story_links(cfg, [r for r in results if not r.need.is_withdrawn])
    if links:
        out += ["## Stories", "", "| need | story |", "|---|---|"]
        out += [f"| {nid} | [{sid}]({url}) |" for nid, sid, url in links]
        out.append("")

    # Paths (#99): where a role starts, what done means, the click budget, and the proof state.
    paths = [r for r in results if r.need.path is not None and not r.need.is_withdrawn]
    if paths:
        out += ["## Paths", "", "| need | path |", "|---|---|"]
        for r in sorted(paths, key=lambda r: r.need.id):
            out.append(f"| {r.need.id} | {(path_summary(r) or '').replace('|', chr(92) + '|')} |")
        out.append("")

    if model.goals:
        out += [
            "## Goals",
            "",
            "| goal | state | delivered | target | goal |",
            "|---|---|---|---|---|",
        ]
        for goal, gsum in goal_cov:
            out.append(
                f"| {goal.id} | {_LABEL[group_state(gsum)]} "
                f"| {gsum.delivered}/{gsum.total} ({round(gsum.coverage * 100)}%) "
                f"| {goal.target or ''} | {goal.text} |"
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
                else "(no need yet)"
            )
            out.append(f"| {display_title(role.id)} | {cov} | {role.text} |")
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

    if model.principles:
        out += [
            "## Principles (the vision, held as given)",
            "",
            "| principle | scope | state | stated | needs declined under it |",
            "|---|---|---|---|---|",
        ]
        for rep in board.principles:
            text = rep.principle.text.replace("|", "\\|")
            declined = ", ".join(n.id for n in rep.declined) or "none"
            stale = f" _(re-review {', '.join(n.id for n in rep.stale)})_" if rep.stale else ""
            out.append(
                f"| {rep.principle.id}: {text} | {rep.principle.scope} | {rep.state.value.upper()} "
                f"| {rep.principle.revised_at or 'n/a'} | {declined}{stale} |"
            )
        out.append("")

    active = active_decisions(list(model.decisions))
    if active:
        out += [
            "## Decisions (the solution chosen for each need)",
            "",
            "| decision | serves | chosen over | rests on |",
            "|---|---|---|---|",
        ]
        for d in active:
            text = d.text.replace("|", "\\|")
            over = ", ".join(a.replace("|", "\\|") for a in d.alternatives) or "none"
            rests = ", ".join(d.principles) or "none"
            out.append(f"| {d.id}: {text} | {', '.join(d.needs)} | {over} | {rests} |")
        out.append("")

    if model.glossary:
        differing = {(c.term, c.client) for c in collisions(model.glossary)}
        out += ["## Glossary", "", "| term | scope | meaning |", "|---|---|---|"]
        for t in sorted(model.glossary, key=lambda x: (x.term, x.scope or "")):
            note = " _(differs from the global meaning)_" if (t.term, t.client) in differing else ""
            out.append(
                f"| {t.term} | {t.scope or 'global'} | {t.text.replace('|', chr(92) + '|')}{note} |"
            )
        out.append("")

    out += _open_questions(results, hide_empty=hide_empty)
    return "\n".join(out)
