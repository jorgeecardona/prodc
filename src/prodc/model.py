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
class Attestation:
    """A human's sign-off that a need's proofs actually establish its claim (#13).

    prodc can read that a proof resolves and passes, but not that it proves *this* need.
    An attestation records who reviewed that link and when — it does not prove fit, it
    makes the human link visible and dated so an unreviewed one is distinguishable.
    """

    who: str
    date: str


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
    client: str | None = None  # which client this instance is for; None = shared baseline
    variant_of: str | None = None  # id of the baseline need this specialises; None = standalone
    importance: int | None = None  # author-supplied ordinal (higher = more); refines ranking
    claim: str | None = None  # what delivering this need would establish — the warrant to review
    attestation: Attestation | None = None  # human sign-off that the proofs establish the claim

    @property
    def is_variant(self) -> bool:
        """A client-specific specialisation of a baseline need."""
        return self.variant_of is not None

    @property
    def is_opinion(self) -> bool:
        """No source of any kind = opinion (Torres: an unvalidated desirability assumption)."""
        return len(self.sources) == 0

    @property
    def only_internal(self) -> bool:
        """Sourced, but only by the team's own assertion — not a customer."""
        return len(self.sources) > 0 and all(s.kind is SourceKind.INTERNAL for s in self.sources)

    @property
    def strongest_kind(self) -> SourceKind | None:
        """The strongest source kind backing this need, or None when it is an opinion."""
        order = list(SourceKind)  # declaration order is strongest-first
        kinds = {s.kind for s in self.sources}
        return next((k for k in order if k in kinds), None)


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


class EarsShape(StrEnum):
    """The EARS clause a need's text follows (Easy Approach to Requirements Syntax)."""

    EVENT = "event"  # "When <trigger>, <who> can <outcome>"
    STATE = "state"  # "While <state>, <who> can <outcome>"
    OPTIONAL = "optional"  # "Where <feature>, <who> can <outcome>"
    UNWANTED = "unwanted"  # "If <condition>, then <who> can <outcome>"
    UBIQUITOUS = "ubiquitous"  # a plain capability with no trigger clause
    UNCLASSIFIED = "unclassified"  # no recognisable outcome phrasing


# EARS trigger keyword (clause lead) → the shape it introduces. Each needs an outcome.
_EARS_TRIGGERS = {
    "when": EarsShape.EVENT,
    "while": EarsShape.STATE,
    "where": EarsShape.OPTIONAL,
    "if": EarsShape.UNWANTED,
}
# Markers of an observable outcome ("<who> can see", "the system shall …").
_EARS_OUTCOME = (" can ", " shall ", " is able to ", " able to ")


def _has_outcome(text: str) -> bool:
    return any(marker in f" {text.lower()} " for marker in _EARS_OUTCOME)


def ears_shape(text: str) -> EarsShape:
    """Classify a need's text into its EARS clause shape."""
    first = text.strip().split(" ", 1)[0].lower().rstrip(":,")
    trigger = _EARS_TRIGGERS.get(first)
    if trigger is not None:
        return trigger
    return EarsShape.UBIQUITOUS if _has_outcome(text) else EarsShape.UNCLASSIFIED


def ears_warnings(text: str) -> list[str]:
    """Soft structural checks on need text — EARS shape, never a hard failure.

    A trigger clause (When/While/Where/If) with no observable outcome is flagged, as is a
    need with no outcome phrasing at all. These upgrade the solution-in-disguise heuristic
    into a shape check without rejecting a PM's wording.
    """
    first = text.strip().split(" ", 1)[0].lower().rstrip(":,")
    out: list[str] = []
    if first in _EARS_TRIGGERS and not _has_outcome(text):
        out.append(f"EARS: '{first}' clause without an observable outcome ('can'/'shall')")
    elif ears_shape(text) is EarsShape.UNCLASSIFIED:
        out.append("EARS: no observable outcome — try 'When <trigger>, <who> can <outcome>'")
    return out


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
