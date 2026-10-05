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
class Goal:
    """A measurable objective that needs trace up to (Impact Mapping: Goal → … → Deliverable).

    A need with no ``goal`` is flagged the way an unsourced need is flagged an opinion — it
    lets the board answer "are we moving the objective", not only "is this need delivered".
    """

    id: str
    text: str
    metric: str | None = None  # how the objective is measured, e.g. "churn < 5%"


@dataclass(frozen=True)
class Release:
    """A releasable slice of a journey (User Story Mapping, Patton).

    Declared in an ordered ``releases:`` list — position is the ship order. A need names
    the release it belongs to, so the board can show what a coherent release looks like,
    which a flow's flat ``children`` cannot express on its own.
    """

    id: str
    text: str  # a release has a name, like a Goal


class AttestationKind(StrEnum):
    """Who reviewed the warrant — a ladder of strength, human strongest (cf. SourceKind)."""

    HUMAN = "human"  # a person judged that the proofs establish the need
    AI = "ai"  # a model reviewed it — weaker than a human, stronger than nothing


@dataclass(frozen=True)
class Attestation:
    """A sign-off that a need's proofs actually establish its claim (#13).

    prodc can read that a proof resolves and passes, but not that it proves *this* need. An
    attestation records who reviewed that link and when — it does not prove fit, it makes the
    review visible and dated. A review can be a human's or an AI model's (``kind``); an AI
    review carries the model as ``who`` and keeps its verdict and comment for the register.
    """

    who: str  # a person's name, or the model id for an AI review
    date: str
    kind: AttestationKind = AttestationKind.HUMAN
    verdict: str | None = None  # the reviewer's conclusion, e.g. "pass" / "concerns" / "fail"
    comment: str | None = None  # the review's feedback / rationale, kept on the record


@dataclass(frozen=True)
class Need:
    """What a named person wants, with its provenance and its proofs."""

    id: str
    text: str
    who: str | None = None
    must: bool = False
    sources: tuple[Source, ...] = ()
    proofs: tuple[str, ...] = ()  # locators, "<adapter>:<payload>" (leaf needs)
    children: tuple[str, ...] = ()  # ids of sub-needs (a flow is a Need with children)
    seam: tuple[str, ...] = ()  # end-to-end proof locators for a flow's between-steps behaviour
    label: str | None = None  # free text for the `who`, e.g. "design partner, Sincerely"
    client: str | None = None  # which client this instance is for; None = shared baseline
    variant_of: str | None = None  # id of the baseline need this specialises; None = standalone
    importance: int | None = None  # author-supplied ordinal (higher = more); refines ranking
    claim: str | None = None  # what delivering this need would establish — the warrant to review
    attestation: Attestation | None = None  # human sign-off that the proofs establish the claim
    goal: str | None = None  # id of the Goal this need serves; None = no objective (flagged)
    release: str | None = None  # id of the Release slice this need ships in; None = unslotted
    product: bool = True  # False = infra/NFR/internal, excluded from product coverage (#48)

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


class ArgKind(StrEnum):
    """A node type in the assurance argument (GSN: Goal Structuring Notation)."""

    CLAIM = "claim"  # GSN Goal: a proposition being argued (kept distinct from a prodc Goal)
    STRATEGY = "strategy"  # GSN Strategy: how a claim is broken into sub-claims
    EVIDENCE = "evidence"  # GSN Solution: what discharges a claim (often cites a proof)
    CONTEXT = "context"  # GSN Context: the frame a claim is stated in
    ASSUMPTION = "assumption"  # GSN Assumption: taken true without evidence
    JUSTIFICATION = "justification"  # GSN Justification: why a strategy/claim is acceptable


@dataclass(frozen=True)
class ArgNode:
    """One node of the argument graph (#28). Cites prodc nouns by id; never duplicates them.

    ``supported_by`` are the ids of nodes that discharge this one (GSN SupportedBy, downward);
    ``in_context_of`` are context/assumption/justification nodes attached to it (GSN InContextOf).
    ``about`` points at a need id, goal id, or proof locator the node is grounded in.
    """

    id: str
    kind: ArgKind
    text: str
    supported_by: tuple[str, ...] = ()
    in_context_of: tuple[str, ...] = ()
    about: str | None = None


@dataclass(frozen=True)
class Model:
    """Everything loaded from the prodc files: the nouns and their cross-references.

    One aggregate so new nouns compose here instead of each inventing its own loader and
    config key. Needs and goals share this file set; references between them are string ids
    validated at load time.
    """

    needs: tuple[Need, ...] = ()
    goals: tuple[Goal, ...] = ()
    releases: tuple[Release, ...] = ()  # in declared order = ship sequence
    argument: tuple[ArgNode, ...] = ()  # the GSN assurance graph (#28)


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
