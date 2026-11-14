"""Deprecation lines for the surface 0.11 keeps loading and 0.12 removes.

One format for every deprecated thing, so a user can grep for it: ``deprecated, removed in 0.12:
<thing>; <what to use instead>``. A run prints each line once, never once per need.
"""

from __future__ import annotations

import sys

REMOVED_IN = "0.12"


def deprecation(thing: str, instead: str) -> str:
    """The one-line deprecation message for ``thing``, with what to use ``instead``."""
    return f"deprecated, removed in {REMOVED_IN}: {thing}; {instead}"


def warn_deprecated(thing: str, instead: str) -> None:
    """Print the deprecation line for a command or flag to stderr, keeping ``--json`` clean."""
    print(f"prodc: {deprecation(thing, instead)}", file=sys.stderr)


def unique(lines: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """``lines`` with repeats dropped, first occurrence order kept."""
    return tuple(dict.fromkeys(lines))
