"""Resolve needs into states: the engine behind ``prodc status``.

A leaf need's state comes from its proofs; a need with children is a flow and its
state aggregates its sub-needs ("3 of 5"). ``HOLE`` (no proof) is deliberately not a
failure — it is an honest, visible gap.
"""

from __future__ import annotations

from .adapters import Adapter, ProofResult
from .model import (
    SOLUTION_VERBS,
    Need,
    NeedResult,
    NeedState,
    ProofState,
)


def _text_warnings(need: Need) -> list[str]:
    first = need.text.strip().split(" ", 1)[0].lower().rstrip(":")
    out: list[str] = []
    if first in SOLUTION_VERBS:
        out.append(f"text may be a solution in disguise (starts with '{first}')")
    for src in need.sources:
        out.extend(src.warnings())
    return out


def _resolve_proof(locator: str, adapters: dict[str, Adapter]) -> ProofResult:
    name, sep, payload = locator.partition(":")
    adapter = adapters.get(name)
    if not sep or adapter is None:
        return ProofResult(ProofState.BROKEN, False, f"no adapter '{name}' for '{locator}'")
    return adapter.resolve(payload)


class Resolver:
    def __init__(self, needs: list[Need], adapters: dict[str, Adapter]) -> None:
        self._by_id = {n.id: n for n in needs}
        self._adapters = adapters
        self._cache: dict[str, NeedResult] = {}
        self._visiting: set[str] = set()

    def resolve_all(self) -> list[NeedResult]:
        return [self.resolve(n.id) for n in self._by_id.values()]

    def resolve(self, need_id: str) -> NeedResult:
        if need_id in self._cache:
            return self._cache[need_id]
        need = self._by_id[need_id]
        if need_id in self._visiting:  # cycle — stop and report
            return NeedResult(need, NeedState.BROKEN, detail=["cycle in children"])
        self._visiting.add(need_id)
        result = self._compute(need)
        self._visiting.discard(need_id)
        result.warnings = _text_warnings(need) + result.warnings
        self._cache[need_id] = result
        return result

    def _compute(self, need: Need) -> NeedResult:
        if need.children:
            return self._aggregate_children(need)
        return self._resolve_leaf(need)

    def _resolve_leaf(self, need: Need) -> NeedResult:
        if not need.proofs:
            return NeedResult(need, NeedState.HOLE)
        results = [_resolve_proof(p, self._adapters) for p in need.proofs]
        detail = [f"{p} → {r.state.value}{'*' if r.declared else ''} ({r.detail})"
                  for p, r in zip(need.proofs, results, strict=True)]
        delivered = sum(1 for r in results if r.state is ProofState.DELIVERED)
        declared = any(r.declared for r in results if r.state is ProofState.DELIVERED)
        if any(r.state is ProofState.BROKEN for r in results):
            state = NeedState.BROKEN
        elif delivered == len(results):
            state = NeedState.DELIVERED
        else:
            state = NeedState.PENDING
        return NeedResult(need, state, delivered, len(results), declared, detail)

    def _aggregate_children(self, need: Need) -> NeedResult:
        warnings: list[str] = []
        child_states: list[NeedState] = []
        declared = False
        for cid in need.children:
            if cid not in self._by_id:
                warnings.append(f"unknown child id '{cid}'")
                continue
            cr = self.resolve(cid)
            child_states.append(cr.state)
            declared = declared or cr.declared
        delivered = sum(1 for s in child_states if s is NeedState.DELIVERED)
        total = len(child_states)
        if any(s is NeedState.BROKEN for s in child_states):
            state = NeedState.BROKEN
        elif total and delivered == total:
            state = NeedState.DELIVERED
        elif not child_states or all(s is NeedState.HOLE for s in child_states):
            state = NeedState.HOLE
        else:
            state = NeedState.PENDING
        detail = [f"{delivered} of {total} sub-needs delivered"]
        return NeedResult(need, state, delivered, total, declared, detail, warnings)


def resolve(needs: list[Need], adapters: dict[str, Adapter]) -> list[NeedResult]:
    """Resolve every need to a :class:`NeedResult`."""
    return Resolver(needs, adapters).resolve_all()
