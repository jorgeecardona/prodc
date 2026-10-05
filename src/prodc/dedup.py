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


@dataclass(frozen=True)
class VariantGroup:
    """A set of per-client needs that look like the same want, for a shared baseline (#56)."""

    members: tuple[Need, ...]  # the similar needs, each a different client
    score: float  # the lowest pairwise similarity in the group (its weakest link)


def _variant_candidate(a: Need, b: Need) -> bool:
    """Two needs that could be variants of one baseline: distinct clients, neither linked yet."""
    if a.variant_of is not None or b.variant_of is not None:
        return False  # already linked to a baseline — not an unlinked candidate
    if a.client is None or b.client is None or a.client == b.client:
        return False  # recurrence is a cross-client signal; same/none client doesn't count
    # anything left is a candidate unless it was explicitly acknowledged as not the same want
    return b.id not in a.not_variant_of and a.id not in b.not_variant_of


def variant_suggestions(needs: list[Need], threshold: float) -> list[VariantGroup]:
    """Groups of unlinked, cross-client, similar needs that could share one baseline (#56).

    Builds connected components over the candidate pairs (union-find), so three clients asking
    the same thing surface as one group, not three pairs. Each group's score is its weakest
    pairwise link. Most-similar groups first.
    """
    parent = {n.id: n.id for n in needs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges: list[tuple[str, str, float]] = []
    for i in range(len(needs)):
        for j in range(i + 1, len(needs)):
            a, b = needs[i], needs[j]
            if not _variant_candidate(a, b):
                continue
            score = similarity(a.text, b.text)
            if score >= threshold:
                edges.append((a.id, b.id, score))
                parent[find(a.id)] = find(b.id)

    by_id = {n.id: n for n in needs}
    groups: dict[str, list[str]] = {}
    for nid in parent:
        if any(nid in (e[0], e[1]) for e in edges):
            groups.setdefault(find(nid), []).append(nid)

    out: list[VariantGroup] = []
    for root, ids in groups.items():
        member_scores = [s for a, _b, s in edges if find(a) == root]
        members = tuple(sorted((by_id[i] for i in ids), key=lambda n: n.id))
        out.append(VariantGroup(members, min(member_scores)))
    out.sort(key=lambda g: (-g.score, g.members[0].id))
    return out


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
