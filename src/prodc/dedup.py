"""Text-similarity matching for duplicate detection (#55).

A dependency-free trigram Jaccard over normalised need text. No external model, a
cheap deterministic signal the board can act on. Needs with the same `client` and `goal`
break ties, so a same-scope pair ranks above a cross-scope one at equal text score. The
same matcher feeds recurrence-link suggestion (#56) and proof discovery (#54).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from .model import Need

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    """Lowercase, collapse every run of non-alphanumerics to one space."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


@cache
def _trigrams(text: str) -> frozenset[str]:
    """Character trigrams of the normalised text, padded so short strings still yield some.

    Cached per distinct string: an O(n²) matcher compares each need's text O(n) times, so
    recomputing its trigrams every call was the bulk of the cost (#62). The cache keeps it
    one compute per distinct string for the life of the process; results are immutable.
    """
    padded = f"  {_normalise(text)} "
    if len(padded) < 3:
        return frozenset()
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def _jaccard(ta: frozenset[str], tb: frozenset[str]) -> float:
    """Jaccard overlap of two trigram sets, in 0..1."""
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    return len(ta & tb) / union if union else 0.0


def _score_if_reachable(ta: frozenset[str], tb: frozenset[str], threshold: float) -> float:
    """:func:`_jaccard`, but skip the set work when the size ratio alone rules it out (#62).

    Jaccard = intersection / union <= min(|ta|,|tb|) / max(|ta|,|tb|), since the intersection is at
    most the smaller set and the union at least the larger. So when that ratio is below ``threshold``
    the score cannot reach it: an exact prune that returns 0.0 without the (costly) intersection,
    never changing which pairs clear the threshold.
    """
    if not ta or not tb:
        return 0.0
    lo, hi = (len(ta), len(tb)) if len(ta) <= len(tb) else (len(tb), len(ta))
    if lo < threshold * hi:
        return 0.0
    return _jaccard(ta, tb)


def similarity(a: str, b: str) -> float:
    """Trigram Jaccard of two texts, in 0..1 (1.0 = identical after normalisation)."""
    return _jaccard(_trigrams(a), _trigrams(b))


@dataclass(frozen=True)
class DupPair:
    """A candidate duplicate: two needs and their text-similarity score."""

    a: Need
    b: Need
    score: float
    same_scope: bool  # same client and goal: a stronger duplicate signal


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
    out = [(n, similarity(text, n.text)) for n in needs if n.id != exclude_id]
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
        return False  # already linked to a baseline: not an unlinked candidate
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
    trigrams = {n.id: _trigrams(n.text) for n in needs}

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
            score = _score_if_reachable(trigrams[a.id], trigrams[b.id], threshold)
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
    trigrams = {n.id: _trigrams(n.text) for n in needs}
    for i in range(len(needs)):
        for j in range(i + 1, len(needs)):
            a, b = needs[i], needs[j]
            if not include_acknowledged and _acknowledged(a, b):
                continue
            score = _score_if_reachable(trigrams[a.id], trigrams[b.id], threshold)
            if score >= threshold:
                same = a.client == b.client and a.goal == b.goal
                pairs.append(DupPair(a, b, score, same))
    pairs.sort(key=lambda p: (-p.score, not p.same_scope, p.a.id, p.b.id))
    return pairs


@dataclass(frozen=True)
class WhoVariant:
    """A cluster of `who` strings that likely name the same person within one client (#61)."""

    client: str | None
    whos: tuple[str, ...]  # the distinct who-strings in the cluster, sorted
    need_ids: tuple[str, ...]  # the needs carrying any of them, sorted


def who_variants(needs: list[Need], threshold: float) -> list[WhoVariant]:
    """Clusters of ``who`` strings that drift apart within one client, e.g. John vs john (#61).

    `role` (#52) is validated at load; `who` is free text, so the same person splits the board
    when spelled inconsistently. Scoped per client (same name at two clients is not flagged):
    two whos cluster when they are equal after normalisation (case/whitespace) or their text
    similarity is >= `threshold`. Only clusters of two or more distinct whos are returned. A soft
    lint signal. The fix is to normalise the data, so there is no suppression knob.
    """
    by_client: dict[str | None, list[Need]] = {}
    for n in needs:
        if n.who is not None:
            by_client.setdefault(n.client, []).append(n)

    out: list[WhoVariant] = []
    for client, group in by_client.items():
        whos = sorted({n.who for n in group if n.who is not None})
        if len(whos) < 2:
            continue
        parent = {w: w for w in whos}

        def find(x: str, parent: dict[str, str] = parent) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(whos)):
            for j in range(i + 1, len(whos)):
                a, b = whos[i], whos[j]
                if _normalise(a) == _normalise(b) or similarity(a, b) >= threshold:
                    parent[find(a)] = find(b)

        clusters: dict[str, list[str]] = {}
        for w in whos:
            clusters.setdefault(find(w), []).append(w)
        for members in clusters.values():
            if len(members) < 2:
                continue
            member_set = set(members)
            ids = sorted(n.id for n in group if n.who in member_set)
            out.append(WhoVariant(client, tuple(sorted(members)), tuple(ids)))
    out.sort(key=lambda v: (v.client or "", v.whos))
    return out


def tag_warnings(
    needs: list[Need], structural_ids: set[str], threshold: float
) -> list[tuple[str, str]]:
    """Keep the flat tag space from rotting (#80): singletons, near-dup spellings, hidden structure.

    Tags are undeclared and many-to-many, so nothing stops a typo (`search` vs `searching`) or a
    one-off from accumulating. Three cheap hygiene signals, each a warning keyed by the tag:
    a tag equal to a declared goal/role/release/client id ("structure hiding in a tag": use the
    first-class field instead), a singleton (one need only: a likely typo or a tag not worth it),
    and a near-duplicate spelling of another tag (same :func:`similarity` the dedup checks use).
    """
    counts: dict[str, int] = {}
    for n in needs:
        for t in n.tags:
            counts[t] = counts.get(t, 0) + 1
    out: list[tuple[str, str]] = []
    tags = sorted(counts)
    for t in tags:
        if t in structural_ids:
            out.append(
                (t, "tag equals a declared goal/role/release/client id: use that field, not a tag")
            )
        elif counts[t] == 1:
            out.append(
                (t, "tag used on only one need: a singleton (likely a typo or not worth a tag)")
            )
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            a, b = tags[i], tags[j]
            if _normalise(a) != _normalise(b) and similarity(a, b) >= threshold:
                out.append((a, f"tag may be a near-duplicate spelling of {b!r}"))
    return out
