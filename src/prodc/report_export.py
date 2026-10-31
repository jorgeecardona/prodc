"""Render the board for product tooling: CSV, Jira wiki markup, Confluence storage format (#65).

One flat :class:`ExportRow` per need, built from the resolved board. The three renderers format
the same rows, so a column cannot differ between formats. Dependency-free (stdlib ``csv`` and
``html``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from html import escape

from .model import NeedResult, NeedState
from .report import source_type

COLUMNS: tuple[str, ...] = (
    "id",
    "client",
    "who",
    "state",
    "must",
    "importance",
    "goal",
    "release",
    "warrant",
    "source_type",
    "proof_detail",
    "text",
)


@dataclass(frozen=True)
class ExportRow:
    """One need as a table row. Empty fields are empty strings, never None."""

    id: str
    client: str
    who: str
    state: str
    must: str  # "yes" or ""
    importance: str
    goal: str
    release: str
    warrant: str  # the strongest source kind, or "opinion"
    source_type: str  # ticket, post, message...: read from the locator, "" when unknown
    proof_detail: str
    text: str

    def cells(self) -> tuple[str, ...]:
        """The row's values, in :data:`COLUMNS` order."""
        return (
            self.id,
            self.client,
            self.who,
            self.state,
            self.must,
            self.importance,
            self.goal,
            self.release,
            self.warrant,
            self.source_type,
            self.proof_detail,
            self.text,
        )


def export_rows(results: list[NeedResult]) -> list[ExportRow]:
    """One row per product need that is not withdrawn, sorted by id."""
    rows: list[ExportRow] = []
    for r in sorted(results, key=lambda x: x.need.id):
        n = r.need
        if not n.product or n.is_withdrawn:
            continue
        strongest = n.strongest_kind
        typed = next(
            (
                t
                for s in n.sources
                if s.kind is strongest and (t := source_type(s.locator)) is not None
            ),
            "",
        )
        rows.append(
            ExportRow(
                id=n.id,
                client=n.client or "",
                who=n.who or "",
                state=r.state.value.upper(),
                must="yes" if n.must else "",
                importance="" if n.importance is None else str(n.importance),
                goal=n.goal or "",
                release=n.release or "",
                warrant=strongest.value if strongest is not None else "opinion",
                source_type=typed,
                proof_detail="; ".join(r.detail),
                text=" ".join(n.text.split()),
            )
        )
    return rows


def render_csv(rows: list[ExportRow]) -> str:
    """The rows as CSV with a header line. A spreadsheet opens it directly."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(row.cells())
    return buf.getvalue()


_JIRA_COLOUR = {
    NeedState.DELIVERED.value.upper(): "green",
    NeedState.PENDING.value.upper(): "orange",
    NeedState.HOLE.value.upper(): "gray",
    NeedState.BROKEN.value.upper(): "red",
    NeedState.UNRESOLVED.value.upper(): "red",
}
_CONFLUENCE_COLOUR = {
    "green": "Green",
    "orange": "Yellow",
    "gray": "Grey",
    "red": "Red",
}


def _jira_cell(value: str) -> str:
    return value.replace("|", "\\|") or " "


def render_jira(rows: list[ExportRow], title: str) -> str:
    """The rows as Jira wiki markup: a heading and a table that pastes into a ticket or comment."""
    out = [f"h1. {title}", "", "||" + "||".join(COLUMNS) + "||"]
    for row in rows:
        cells = list(row.cells())
        colour = _JIRA_COLOUR.get(row.state, "gray")
        cells[COLUMNS.index("state")] = "{color:" + colour + "}" + row.state + "{color}"
        out.append("|" + "|".join(_jira_cell(c) for c in cells) + "|")
    return "\n".join(out) + "\n"


def _confluence_state(state: str) -> str:
    colour = _CONFLUENCE_COLOUR[_JIRA_COLOUR.get(state, "gray")]
    return (
        '<ac:structured-macro ac:name="status">'
        f'<ac:parameter ac:name="colour">{colour}</ac:parameter>'
        f'<ac:parameter ac:name="title">{escape(state)}</ac:parameter>'
        "</ac:structured-macro>"
    )


def render_confluence(rows: list[ExportRow], title: str) -> str:
    """The rows as Confluence storage format (XHTML) for a documentation page."""
    out = [f"<h1>{escape(title)}</h1>", "<table><tbody>"]
    out.append("<tr>" + "".join(f"<th>{c}</th>" for c in COLUMNS) + "</tr>")
    for row in rows:
        cells = [
            _confluence_state(c) if col == "state" else escape(c)
            for col, c in zip(COLUMNS, row.cells(), strict=True)
        ]
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out) + "\n"
