"""The glossary: what a term means, globally or for one client (#72).

A need lists the terms it uses in ``terms``. prodc checks that each listed term is defined for
that need's client, and flags a term whose client definition differs from its global one. It never
reads need text to find terms.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Need, Term


@dataclass(frozen=True)
class Collision:
    """One term with a global meaning and a different meaning for a client."""

    term: str
    global_text: str
    client: str
    client_text: str


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def collisions(glossary: tuple[Term, ...]) -> list[Collision]:
    """Terms defined globally and again for a client with different text, in term order."""
    global_text = {t.term: t.text for t in glossary if t.scope is None}
    out = [
        Collision(t.term, global_text[t.term], t.client or "", t.text)
        for t in glossary
        if t.scope is not None and t.term in global_text and not _same(t.text, global_text[t.term])
    ]
    return sorted(out, key=lambda c: (c.term, c.client))


def definition(glossary: tuple[Term, ...], term: str, client: str | None) -> Term | None:
    """The meaning of ``term`` for a need of ``client``: the client's own, else the global one."""
    own = next((t for t in glossary if t.term == term and client and t.client == client), None)
    return own or next((t for t in glossary if t.term == term and t.scope is None), None)


def glossary_findings(
    glossary: tuple[Term, ...], needs: list[Need]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Lint the glossary: ``(errors, warnings keyed by term or need id)`` (#72).

    - error: a need lists a term that has no definition applying to it.
    - warning: a term has a global meaning and a different one for a client.
    """
    errors: list[str] = []
    for n in needs:
        for term in n.terms:
            if definition(glossary, term, n.client) is None:
                where = f" for client {n.client}" if n.client else ""
                errors.append(f"{n.id}: terms lists '{term}', which is not defined{where}")
    warnings = [
        (
            c.term,
            f"term means one thing globally and another for client {c.client}: "
            f"global '{c.global_text}' vs '{c.client_text}' (#72)",
        )
        for c in collisions(glossary)
    ]
    return errors, warnings
