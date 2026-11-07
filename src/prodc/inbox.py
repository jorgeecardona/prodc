"""The decision inbox: open questions on a board that only a person can answer (#113).

The inbox only lists. It never records an answer, so an agent that runs it cannot decide for
the human. Each item names the command for every option, ready to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model import Decision, Need, Verdict, board_needs
from .status import active_decisions


class InboxKind(StrEnum):
    """Why a person has to look at a need."""

    MUST_OPINION = "must_opinion"  # a must-have with no external evidence and no decision
    WARRANT_REVIEW = "warrant_review"  # a warrant review returned concerns or fail


@dataclass(frozen=True)
class InboxOption:
    """One way to answer an inbox item, with the command that records it."""

    label: str
    command: str


@dataclass(frozen=True)
class InboxItem:
    """One open decision for a person: the need, why it is open, and the options."""

    need_id: str
    text: str
    kind: InboxKind
    reason: str
    options: tuple[InboxOption, ...]


def _must_opinion(need: Need) -> InboxItem:
    has = "only an assumption" if need.only_assumption else "no source"
    return InboxItem(
        need_id=need.id,
        text=need.text,
        kind=InboxKind.MUST_OPINION,
        reason=f"must-have with {has}",
        options=(
            InboxOption(
                "record the decision that commits to it",
                f"prodc add decision D-? --needs {need.id} --text '...'",
            ),
            InboxOption("lower must", f"prodc set {need.id} must=false"),
            InboxOption(
                "add a real source", f"prodc capture {need.id} --kind secondary --locator ..."
            ),
        ),
    )


def _warrant_review(need: Need) -> InboxItem:
    att = need.attestation
    assert att is not None and att.verdict is not None
    note = f": {att.comment}" if att.comment else ""
    return InboxItem(
        need_id=need.id,
        text=need.text,
        kind=InboxKind.WARRANT_REVIEW,
        reason=f"{att.kind.value} review by {att.who} returned {att.verdict.value}{note}",
        options=(
            InboxOption(
                "accept the proofs",
                f"prodc attest {need.id} --verdict pass --by <you> --date <today>",
            ),
            InboxOption("fix the proofs", f"edit the proofs of {need.id}, then attest again"),
            InboxOption("withdraw the need", f"prodc withdraw {need.id} --reason '...'"),
        ),
    )


def inbox(needs: list[Need], decisions: list[Decision]) -> list[InboxItem]:
    """Every open human decision on the active board, must-have opinions first, by need id.

    A must-have opinion that an active decision covers is not open. Drafts are skipped.
    """
    decided = {nid for d in active_decisions(decisions) for nid in d.needs}
    active = sorted(board_needs(needs, include_drafts=False), key=lambda n: n.id)
    items = [_must_opinion(n) for n in active if n.must and n.is_opinion and n.id not in decided]
    items += [
        _warrant_review(n)
        for n in active
        if n.attestation is not None
        and n.attestation.verdict is not None
        and n.attestation.verdict is not Verdict.PASS
    ]
    return items
