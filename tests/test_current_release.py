"""The current release and the now-set: what ``plan`` ranks first."""

from __future__ import annotations

from dataclasses import dataclass

from prodc.adapters import Adapter, ProofResult
from prodc.model import Need, NeedResult, ProofState, Release
from prodc.status import current_release, now_ids, rank, resolve


@dataclass(frozen=True)
class _Stub:
    state: ProofState

    def resolve(self, payload: str) -> ProofResult:
        return ProofResult(self.state, declared=True, detail="stub")


_ADAPTERS: dict[str, Adapter] = {"ok": _Stub(ProofState.DELIVERED), "bad": _Stub(ProofState.BROKEN)}
R1 = Release(id="R1", text="first")
R2 = Release(id="R2", text="second")


def _need(
    nid: str, release: str | None = None, proof: str | None = None, *, must: bool = False
) -> Need:
    proofs = (f"{proof}:x",) if proof else ()
    return Need(id=nid, text=nid, release=release, proofs=proofs, must=must)


def _results(*needs: Need) -> list[NeedResult]:
    return resolve(list(needs), _ADAPTERS)


def _order(results: list[NeedResult], releases: list[Release]) -> list[str]:
    return [r.need.id for r in rank(results, None, now_ids(results, releases))]


def test_no_releases_keeps_the_old_order() -> None:
    results = _results(
        _need("A", "R2"), _need("B", must=True), _need("C", proof="bad"), _need("D", proof="ok")
    )
    assert current_release(results, []) is None
    assert now_ids(results, []) == frozenset()
    assert _order(results, []) == [r.need.id for r in rank(results)]


def test_first_release_done_advances_to_the_next() -> None:
    results = _results(_need("A", "R1", "ok"), _need("B", "R2"), _need("C", must=True))
    assert current_release(results, [R1, R2]) == R2
    assert now_ids(results, [R1, R2]) == {"B"}
    assert _order(results, [R1, R2])[0] == "B"  # ahead of the must-HOLE outside the release


def test_broken_outside_the_release_is_now() -> None:
    results = _results(_need("A", "R1"), _need("B", "R2", "bad"), _need("C"))
    assert now_ids(results, [R1, R2]) == {"A", "B"}
    assert _order(results, [R1, R2])[-1] == "C"


def test_an_empty_release_is_skipped() -> None:
    results = _results(_need("A", "R2"))
    assert current_release(results, [R1, R2]) == R2


def test_every_release_delivered_has_no_current() -> None:
    results = _results(_need("A", "R1", "ok"), _need("B"))
    assert current_release(results, [R1]) is None
    assert now_ids(results, [R1]) == frozenset()
