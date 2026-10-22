"""JSON serialisers for the ``--json`` output of each read command.

Each builds the machine-readable payload for one command. The per-need record itself comes from
:func:`prodc.board.need_payload` (the one shared serialiser), so ``status --json`` and the HTML
viewer never drift; these functions wrap that with the board/plan/brief/argument framing.
"""

from __future__ import annotations

import json

from ..board import need_payload
from ..board import warrant as _warrant
from ..dedup import DupPair, VariantGroup
from ..model import Decision, Goal, NeedResult, NeedState, Release, Role
from ..status import (
    DecisionReadiness,
    Handoff,
    PrincipleReport,
    Recurrence,
    Summary,
    group_state,
    rank,
)
from .common import brief_open


def _decision_payload(d: Decision) -> dict[str, object]:
    """One decision as a JSON record: the OST chosen-solution node and its edges."""
    return {
        "id": d.id,
        "text": d.text,
        "needs": list(d.needs),
        "alternatives": list(d.alternatives),
        "consequences": d.consequences,
        "principles": list(d.principles),
        "decided_at": d.decided_at,
        "draft": d.draft,
        "awaits": list(d.awaits),
        "withdrawn": (
            {
                "reason": d.withdrawn.reason,
                "date": d.withdrawn.date,
                "kind": d.withdrawn.kind.value,
                "principle": d.withdrawn.principle,
            }
            if d.withdrawn
            else None
        ),
    }


def _summary_payload(summary: Summary, orphan_map: dict[str, list[str]]) -> dict[str, object]:
    return {
        "total": summary.total,
        "delivered": summary.delivered,
        "pending": summary.pending,
        "hole": summary.hole,
        "must_hole": summary.must_hole,
        "broken": summary.broken,
        "unresolved": summary.unresolved,
        "opinion": summary.opinion,
        "coverage": round(summary.coverage, 4),
        "orphans": sum(len(v) for v in orphan_map.values()),
    }


def to_json(
    results: list[NeedResult],
    summary: Summary,
    orphan_map: dict[str, list[str]],
    recs: list[Recurrence],
    goal_cov: list[tuple[Goal, Summary]],
    ungoaled: list[NeedResult],
    rel_cov: list[tuple[Release, Summary]],
    role_cov: list[tuple[Role, Summary]],
    unroled: list[NeedResult],
    hos: list[Handoff],
    principles: list[PrincipleReport] | None = None,
    decisions: list[Decision] | None = None,
) -> str:
    payload = {
        "summary": _summary_payload(summary, orphan_map),
        "orphans": orphan_map,
        "roles": [
            {
                "id": role.id,
                "text": role.text,
                "coverage": round(rsum.coverage, 4),
                "delivered": rsum.delivered,
                "total": rsum.total,
                "orphan": rsum.total == 0,
            }
            for role, rsum in role_cov
        ],
        "unroled": [r.need.id for r in unroled],
        "handoffs": [
            {
                "flow": h.flow.id,
                "from_role": h.from_role,
                "to_role": h.to_role,
                "from_need": h.from_need.id,
                "to_need": h.to_need.id,
            }
            for h in hos
        ],
        "releases": [
            {
                "id": rel.id,
                "text": rel.text,
                "coverage": round(rsum.coverage, 4),
                "delivered": rsum.delivered,
                "total": rsum.total,
            }
            for rel, rsum in rel_cov
        ],
        "recurrence": [
            {
                "baseline": rec.baseline.id,
                "text": rec.baseline.text,
                "count": rec.count,
                "clients": list(rec.clients),
            }
            for rec in recs
        ],
        "goals": [
            {
                "id": goal.id,
                "text": goal.text,
                "metric": goal.metric,
                "description": goal.description,
                "target": goal.target,
                "state": group_state(gsum).value,
                "coverage": round(gsum.coverage, 4),
                "delivered": gsum.delivered,
                "total": gsum.total,
            }
            for goal, gsum in goal_cov
        ],
        "ungoaled": [r.need.id for r in ungoaled],
        "principles": [
            {
                "id": rep.principle.id,
                "text": rep.principle.text,
                "revised_at": rep.principle.revised_at,
                "declined": [n.id for n in rep.declined],
                "stale": [n.id for n in rep.stale],
            }
            for rep in (principles or [])
        ],
        "decisions": [_decision_payload(d) for d in (decisions or [])],
        "needs": [need_payload(r) for r in results],
    }
    return json.dumps(payload, indent=2)


def decision_show_json(
    d: Decision, warnings: list[str], readiness: DecisionReadiness | None = None
) -> str:
    """``prodc show D-1 --json`` (#95): the decision record, its readiness (#93), its warnings."""
    payload = _decision_payload(d)
    payload["readiness"] = (
        {
            "blocked": readiness.blocked,
            "waits": [
                {"ref": w.ref, "state": w.state.value, "detail": w.detail} for w in readiness.waits
            ],
        }
        if readiness is not None
        else None
    )
    payload["warnings"] = warnings
    return json.dumps(payload, indent=2)


def show_json(r: NeedResult, decisions: list[Decision] | None = None) -> str:
    need = r.need
    payload = need_payload(r)  # the shared core, never drifts from the board
    payload.update(
        {
            "decisions": [_decision_payload(d) for d in (decisions or [])],
            "sources": [
                {
                    "kind": s.kind.value,
                    "who": s.who,
                    "role": s.role,
                    "date": s.date,
                    "quote": s.quote,
                    "locator": s.locator,
                }
                for s in need.sources
            ],
            "proofs": list(need.proofs),
            "children": [{"id": c.id, "step": c.step} for c in need.children],
            "seam": list(need.seam),
        }
    )
    return json.dumps(payload, indent=2)


def brief_json(
    client: str,
    results: list[NeedResult],
    stale: list[tuple[NeedResult, int]] | None = None,
) -> str:
    open_ = brief_open(results)
    return json.dumps(
        {
            "client": client,
            "open": [
                {
                    "id": r.need.id,
                    "text": r.need.text,
                    "must": r.need.must,
                    "opinion": r.need.is_opinion,
                    "hole": r.state is NeedState.HOLE,
                    "warrant": _warrant(r.need),
                }
                for r in open_
            ],
            "confirm_still_wanted": [
                {"id": r.need.id, "text": r.need.text, "evidence_age": age}
                for r, age in sorted(stale or [], key=lambda t: (-t[1], t[0].need.id))
            ],
        },
        indent=2,
    )


def plan_json(
    results: list[NeedResult], recurrence_counts: dict[str, int], *, revisit: bool = False
) -> str:
    ranked = rank(results, recurrence_counts)
    return json.dumps(
        {
            "revisit": revisit,
            "plan": [
                {
                    "rank": i,
                    "id": r.need.id,
                    "text": r.need.text,
                    "must": r.need.must,
                    "state": r.state.value,
                    "warrant": _warrant(r.need),
                    "recurrence": recurrence_counts.get(r.need.id, 0),
                    "importance": r.need.importance,
                    "importance_is_guess": (r.need.importance is not None and r.need.is_opinion),
                }
                for i, r in enumerate(ranked, 1)
            ],
        },
        indent=2,
    )


def variant_payload(g: VariantGroup) -> dict[str, object]:
    return {
        "score": round(g.score, 4),
        "members": [{"id": m.id, "client": m.client, "text": m.text} for m in g.members],
    }


def dup_payload(p: DupPair) -> dict[str, object]:
    return {
        "a": p.a.id,
        "b": p.b.id,
        "score": round(p.score, 4),
        "same_scope": p.same_scope,
        "a_text": p.a.text,
        "b_text": p.b.text,
    }
