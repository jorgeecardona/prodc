"""The prefix filter in ``candidate_pairs`` never drops a pair that reaches the threshold (#62)."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import random

import pytest

from prodc.dedup import (
    _jaccard,
    _trigrams,
    candidate_pairs,
    duplicate_pairs,
)
from prodc.model import Need

_WORDS = [f"w{i}" for i in range(25)]


def _texts(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    base = [" ".join(rng.choices(_WORDS, k=rng.randint(2, 8))) for _ in range(n // 2)]
    # near copies so some pairs really do clear a high threshold
    return base + [t + (" " + rng.choice(_WORDS) if rng.random() < 0.5 else "") for t in base]


@pytest.mark.parametrize("threshold", [0.3, 0.5, 0.8, 0.95, 1.0])
@pytest.mark.parametrize("seed", range(4))
def test_candidates_are_a_superset_of_the_true_matches(threshold: float, seed: int) -> None:
    sets = [_trigrams(t) for t in _texts(60, seed)]
    truth = {
        (i, j)
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
        if _jaccard(sets[i], sets[j]) >= threshold
    }
    got = set(candidate_pairs(sets, threshold))
    assert truth <= got
    assert all(i < j for i, j in got)


def test_empty_sets_match_nothing() -> None:
    assert list(candidate_pairs([frozenset(), frozenset({"abc"})], 0.5)) == []


def test_duplicate_pairs_match_brute_force() -> None:
    texts = _texts(80, 7)
    needs = [Need(id=f"N-{i}", text=t) for i, t in enumerate(texts)]
    sets = [_trigrams(t) for t in texts]
    expected = {
        (f"N-{i}", f"N-{j}")
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
        if _jaccard(sets[i], sets[j]) >= 0.8
    }
    assert expected  # the fixture has real duplicates
    assert {(p.a.id, p.b.id) for p in duplicate_pairs(needs, 0.8)} == expected
