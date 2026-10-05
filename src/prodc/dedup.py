"""Text-similarity matching for duplicate detection (#55).

A dependency-free trigram Jaccard over normalised need text — no external model, a
cheap deterministic signal the board can act on. Needs with the same `client` and `goal`
break ties, so a same-scope pair ranks above a cross-scope one at equal text score. The
same matcher feeds recurrence-link suggestion (#56) and proof discovery (#54).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Need

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    """Lowercase, collapse every run of non-alphanumerics to one space."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _trigrams(text: str) -> frozenset[str]:
    """Character trigrams of the normalised text, padded so short strings still yield some."""
    padded = f"  {_normalise(text)} "
    if len(padded) < 3:
        return frozenset()
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def similarity(a: str, b: str) -> float:
    """Trigram Jaccard of two texts, in 0..1 (1.0 = identical after normalisation)."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    return len(ta & tb) / union if union else 0.0


@dataclass(frozen=True)
class DupPair:
    """A candidate duplicate: two needs and their text-similarity score."""

    a: Need
    b: Need
    score: float
    same_scope: bool  # same client and goal — a stronger duplicate signal


def _acknowledged(a: Need, b: Need) -> bool:
    """True when either need has recorded the other in `not_duplicate_of` (#55)."""
    return b.id in a.not_duplicate_of or a.id in b.not_duplicate_of


def matches_for(
    text: str,
    needs: list[Need],
    threshold: float,
    *,
    exclude_id: str | None = None,
) -> list[tuple[Need, float]]:
    """Existing needs whose text is >= `threshold` similar to `text`, best first.

    Used at `add` time, before the new need is written, so `exclude_id` skips a need with
    the id being (re)written. Ties break by score then id for a stable order.
    """
    out = [
        (n, similarity(text, n.text))
        for n in needs
        if n.id != exclude_id
    ]
    hits = [(n, s) for n, s in out if s >= threshold]
    hits.sort(key=lambda p: (-p[1], p[0].id))
    return hits


def duplicate_pairs(
    needs: list[Need],
    threshold: float,
    *,
    include_acknowledged: bool = False,
) -> list[DupPair]:
    """Every need pair whose text similarity is >= `threshold`, highest score first.

    A pair either need has marked via `not_duplicate_of` is suppressed unless
    `include_acknowledged` is set. Same-scope pairs rank above cross-scope at equal score.
    """
    pairs: list[DupPair] = []
    for i in range(len(needs)):
        for j in range(i + 1, len(needs)):
            a, b = needs[i], needs[j]
            if not include_acknowledged and _acknowledged(a, b):
                continue
            score = similarity(a.text, b.text)
            if score >= threshold:
                same = a.client == b.client and a.goal == b.goal
                pairs.append(DupPair(a, b, score, same))
    pairs.sort(key=lambda p: (-p.score, not p.same_scope, p.a.id, p.b.id))
    return pairs
