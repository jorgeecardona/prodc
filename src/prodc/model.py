"""The prodc data model: Need, Source, and the derived status states.

Three nouns (Torres): a Need is what a named person wants (an opportunity); a
Source is its provenance (evidence) — a Need with no Source is an opinion; a proof
is a locator to a delivery test, resolved by an adapter. Everything else is
expressed with these: a flow is a Need with children, a persona is ``who``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SourceKind(StrEnum):
    """How a need was evidenced, in descending epistemic weight (Torres, Ch. 5)."""

    INTERVIEW = "interview"  # behavioural evidence: a named customer, a date, a verbatim quote
    ARTIFACT = "artifact"  # documentary: a ticket, doc or email locator
    PROXY = "proxy"  # the author is a plausible user of this product, guessing as that user
    INTERNAL = "internal"  # a team member's own assertion — provenance, but not a customer's


class ProofState(StrEnum):
    """The state of a single proof locator, reported by its adapter."""

    DELIVERED = "delivered"  # the test exists and (if a results artifact is present) passes
    PENDING = "pending"  # declared/planned, not yet green
    BROKEN = "broken"  # the locator does not resolve to anything
    UNRESOLVED = "unresolved"  # the source could not be read at all (e.g. sibling repo absent)


class NeedState(StrEnum):
    """The rolled-up state of a Need (its proofs, or its children)."""

    DELIVERED = "delivered"
    PENDING = "pending"
    HOLE = "hole"  # no proof at all — an honest gap, never a build failure
    BROKEN = "broken"  # a proof locator points at nothing
    UNRESOLVED = "unresolved"  # a proof's source could not be read (e.g. sibling repo absent)


@dataclass(frozen=True)
class Source:
    """Where a need came from. Absence of any Source makes the need an opinion."""

    kind: SourceKind
    who: str | None = None
    date: str | None = None
    quote: str | None = None
    locator: str | None = None

    def warnings(self) -> list[str]:
        """Soft, Torres-derived hygiene checks — never fail the build."""
        out: list[str] = []
        if self.kind is SourceKind.INTERVIEW and not self.quote:
            out.append("interview source without a verbatim quote")
        if self.kind is SourceKind.INTERVIEW and not self.who:
            out.append("interview source without a named person")
        if self.kind is SourceKind.ARTIFACT and not self.locator:
            out.append("artifact source without a locator")
        if not self.date:
            out.append("source without a date")
        return out


@dataclass(frozen=True)
class Need:
    """What a named person wants, with its provenance and its proofs."""

    id: str
    text: str
    who: str | None = None
    must: bool = False
    sources: tuple[Source, ...] = ()
    proofs: tuple[str, ...] = ()  # locators, "<adapter>:<payload>"
    children: tuple[str, ...] = ()  # ids of sub-needs (a flow is a Need with children)
    label: str | None = None  # free text for the `who`, e.g. "design partner, Sincerely"

    @property
    def is_opinion(self) -> bool:
        """No source of any kind = opinion (Torres: an unvalidated desirability assumption)."""
        return len(self.sources) == 0

    @property
    def only_internal(self) -> bool:
        """Sourced, but only by the team's own assertion — not a customer."""
        return len(self.sources) > 0 and all(s.kind is SourceKind.INTERNAL for s in self.sources)


# A leading verb that usually signals a solution-in-disguise, not a need (Torres, Ch. 6).
SOLUTION_VERBS = (
    "implement",
    "add",
    "build",
    "create",
    "support",
    "integrate",
    "redesign",
    "refactor",
)


@dataclass
class NeedResult:
    """A resolved need: its state, its proof detail, and any hygiene warnings."""

    need: Need
    state: NeedState
    delivered: int = 0
    total: int = 0
    declared: bool = False  # true if DELIVERED rests on tags/existence, not a results artifact
    detail: list[str] = field(default_factory=list[str])
    warnings: list[str] = field(default_factory=list[str])
