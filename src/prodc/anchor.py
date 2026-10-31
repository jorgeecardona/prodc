"""Check that a source quote still sits at the lines its anchor names (#57).

A source locator names a whole artifact. An ``anchor`` narrows it to one place: a line range for a
local file (``L120-L134``), a page, a timestamp, a URL fragment. Only a line range on a local file
is checked here. Every other anchor is passed through unverified.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import Source

_LINES_RE = re.compile(r"^L(\d+)(?:-L?(\d+))?$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def line_span(anchor: str) -> tuple[int, int] | None:
    """The 1-based inclusive ``(first, last)`` lines of an anchor like ``L120-L134``, else None."""
    m = _LINES_RE.match(anchor.strip())
    if m is None:
        return None
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else first
    return (first, last) if 1 <= first <= last else None


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def anchor_drift(root: Path, source: Source) -> str | None:
    """Why the source's quote is no longer at its anchored lines, or None when it is fine.

    Checks only a source with a ``quote``, a line-range ``anchor`` and a locator that is a plain
    path (no scheme, no ``#``). Whitespace and case are ignored when matching the quote.
    """
    if not (source.quote and source.anchor and source.locator):
        return None
    span = line_span(source.anchor)
    if span is None or "#" in source.locator or _SCHEME_RE.match(source.locator):
        return None
    path = root / source.locator
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return f"anchored file '{source.locator}' cannot be read"
    first, last = span
    if last > len(lines):
        return f"{source.locator} has {len(lines)} line(s), the anchor ends at line {last}"
    if _squash(source.quote) not in _squash("\n".join(lines[first - 1 : last])):
        return f"the quote no longer appears in {source.locator}#{source.anchor}"
    return None
