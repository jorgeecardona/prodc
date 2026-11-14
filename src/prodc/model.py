"""The prodc data model: the nouns and the derived status states.

Three core nouns (Torres): a Need is what a named person wants (an opportunity); a
Source is its provenance (evidence). A Need with no Source is an opinion; a proof
is a locator to a delivery test, resolved by an adapter. Five more earn a place by
the admission test in docs/model.md (#92): Goal, Release, Role, Principle, Decision.
Everything else is a field: a flow is a Need with children, a question is a Need with
``claim``/``answer``, a review is ``draft`` plus an Attestation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class SourceKind(StrEnum):
    """How strongly a need is evidenced, strongest first: the academic primary/secondary split,
    plus the floor every need has at least (Torres, Ch. 5).

    PRIMARY and SECONDARY are the two recognised research tiers; ASSUMPTION is our own stated guess.
    A need with no PRIMARY or SECONDARY source is an *opinion* (see :attr:`Need.is_opinion`): a
    belief not yet grounded in the user or the world. "Nothing falls from the sky": a bare need is
    really an unrecorded assumption, which is why ASSUMPTION is the floor rather than "no source".
    """

    PRIMARY = "primary"  # straight from the user: an interview, their own email/message/ticket
    SECONDARY = (
        "secondary"  # existing/mediated material about them: a report, a third-party/internal doc
    )
    ASSUMPTION = "assumption"  # our own stated belief, no external evidence yet (the floor)


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
    HOLE = "hole"  # no proof at all: an honest gap, never a build failure
    BROKEN = "broken"  # a proof locator points at nothing
    UNRESOLVED = "unresolved"  # a proof's source could not be read (e.g. sibling repo absent)


class Confidence(StrEnum):
    """How far a DELIVERED need's recorded facts back the delivery (#97). Derived, never set.

    Declaration order is weakest-first, so a flow takes the ``min`` of its children.
    """

    WEAK = "weak"  # a recorded fact undercuts the delivery
    MEDIUM = "medium"  # green, with no fact against it
    STRONG = "strong"  # human pass, primary source, results-backed proof


class PrincipleState(StrEnum):
    """Whether a principle's proofs show the code still obeys it (#89).

    A principle proof is a *guard against regression*, the mirror of a need proof's *progress toward*
    an outcome: a failing need proof is "not yet", but a failing principle guard is "the code
    contradicts this stance right now" (exactly the tokens.css event where a reversed rule's old
    wording lived on for months). So a failing guard is VIOLATED, never merely PENDING, and the board
    cannot read a contradicted principle as green.
    """

    ENFORCED = "enforced"  # every proof resolved green: the code demonstrably obeys it
    STATED = "stated"  # no active guard (no proofs, or only declared-pending ones): honest, allowed
    VIOLATED = "violated"  # a guard ran and failed: the code contradicts the stance now
    BROKEN = "broken"  # a proof or implemented_in locator resolves to nothing. Lint fails.
    UNRESOLVED = "unresolved"  # a proof's source could not be read (e.g. sibling repo absent)


class Stage(StrEnum):
    """Where a need is in the capture funnel: raw idea, reviewed, or accepted as work (#77).

    Only ``committed`` needs count toward coverage. ``captured`` is what ``draft: true`` always
    meant (hidden until promoted), so ``draft: true`` and ``stage: captured`` are the same stage.
    A need with neither is ``committed``, so no existing board changes.
    """

    CAPTURED = "captured"
    TRIAGED = "triaged"
    COMMITTED = "committed"

    @property
    def next(self) -> Stage:
        """The stage one promotion up the funnel; ``committed`` stays ``committed``."""
        order = list(Stage)
        return order[min(order.index(self) + 1, len(order) - 1)]


class ProofKind(StrEnum):
    """The kind of proof a need is expected to be delivered by (#78).

    Advisory metadata on a need: it says what a HOLE is waiting for and where ``suggest`` should
    look. It never changes how a proof resolves. Each value groups adapter kinds: ``test`` is
    gherkin, pytest and vitest; ``eval`` is evalgate; ``observed`` is the observable-outcome
    (``external``) adapter; ``accept`` and ``prototype`` are their own adapters.
    """

    TEST = "test"
    EVAL = "eval"
    OBSERVED = "observed"
    ACCEPT = "accept"
    PROTOTYPE = "prototype"

    @property
    def with_article(self) -> str:
        """The kind with its article: ``an eval``, ``a test``."""
        return f"{'an' if self.value[0] in 'aeiou' else 'a'} {self.value}"

    @property
    def awaiting(self) -> str:
        """The HOLE reason: ``awaiting an eval``, ``awaiting a test``."""
        return f"awaiting {self.with_article}"


class Answer(StrEnum):
    """Which way a settled question resolved: the research board's direction axis.

    A product need has one axis: is the outcome achieved? A research question has two: is it
    *settled* (DELIVERED, the proof resolved green) and, if so, *which way*. DELIVERED means
    settled; ``answer`` records the direction. A disproven hypothesis is therefore a settled
    result that still counts toward coverage. DELIVERED with ``answer: no``: not a gap.

    Direction is always authored, never computed: an adapter can only map a proof to
    delivered/pending/broken/unresolved, so no adapter can emit a settled-NO. The act of
    concluding "this is the answer, and it is no" is the author's decision, so ``answer`` lives
    on the :class:`Need` (authored lifecycle), not on a proof or need result (computed). A product
    board never sets it and behaves exactly as before.
    """

    YES = "yes"  # the question settled affirmatively
    NO = "no"  # the question settled negatively: a result, not a gap (e.g. a disproven hypothesis)
    INCONCLUSIVE = "inconclusive"  # settled that the evidence cannot decide it either way


@dataclass(frozen=True)
class Source:
    """Where a need came from. Absence of any Source makes the need an opinion."""

    kind: SourceKind
    who: str | None = None
    role: str | None = (
        None  # id of the Role the ``who`` spoke as: whose signal this is (#52 follow-up)
    )
    date: str | None = None
    quote: str | None = None
    locator: str | None = None
    observed_at: str | None = None  # ISO date this evidence was recorded/refreshed (#58)
    anchor: str | None = None  # an exact place inside ``locator``: L120-L134, p.7, 00:14:32 (#57)

    @property
    def ref(self) -> str | None:
        """The locator with its anchor, ``locator#anchor``, ready to paste; None without a locator."""
        if not self.locator:
            return None
        return f"{self.locator}#{self.anchor}" if self.anchor else self.locator

    def warnings(self) -> list[str]:
        """Soft hygiene checks from Torres. Never fails the build."""
        out: list[str] = []
        if self.kind is SourceKind.PRIMARY and not self.who:
            out.append("primary source without a named person")
        if self.kind is SourceKind.PRIMARY and not self.quote and not self.locator:
            out.append("primary source without a verbatim quote or a locator")
        if self.kind is SourceKind.SECONDARY and not self.locator:
            out.append("secondary source without a locator")
        if self.anchor and not self.locator:
            out.append("source anchor without a locator")
        if not self.date:
            out.append("source without a date")
        return out


@dataclass(frozen=True)
class Goal:
    """A measurable objective that needs trace up to (Impact Mapping: Goal → … → Deliverable).

    A need with no ``goal`` is flagged the way an unsourced need is flagged an opinion. It
    lets the board answer "are we moving the objective", not only "is this need delivered".

    A goal is also the home for the long-lived container other trackers call an *initiative* or
    *epic* (#80): a ``description`` and an optional ``target`` window give it a title, a blurb and a
    deadline, and its state is *derived* from the needs that cite it (:func:`~prodc.status.group_state`),
    never hand-set. An "is this big piece of work done" rolls up from the proofs, not a status
    field that drifts. No separate ``initiative`` noun: an output bundle that is neither an outcome
    (goal) nor a ship slice (release) is engineering tracking, not product.
    """

    id: str
    text: str
    metric: str | None = None  # how the objective is measured, e.g. "churn < 5%"
    description: str | None = None  # optional longer blurb: the initiative's prose (#80)
    target: str | None = (
        None  # optional ISO date the objective is aimed at; past + not DELIVERED warns
    )


@dataclass(frozen=True)
class Release:
    """A releasable slice of a journey (User Story Mapping, Patton).

    Declared in an ordered ``releases:`` list: position is the ship order. A need names
    the release it belongs to, so the board can show what a coherent release looks like,
    which a flow's flat ``children`` cannot express on its own.
    """

    id: str
    text: str  # a release has a name, like a Goal


@dataclass(frozen=True)
class Role:
    """A role in the product's world: the archetype a need's ``who`` plays (#52).

    The role is the noun; a concrete person is the instance. "Owner" and "Roaster" are
    roles; John-at-Sincerely (``who: john, client: sincerely``) and Jacob-at-Sincerely are
    instances of them, and a person's role can change (Roaster Aux → Head) without changing who
    they are. Roles are client-agnostic: one ``owner`` is reused across every client, so the
    board can answer "every Owner across all clients", not just within one. Kept thin on
    purpose: evidence lives on the Need (``sources``), not here. A role is a structural
    function (enumerated from the org), not an evidence-built user archetype (a UX persona).
    """

    id: str
    text: str


@dataclass(frozen=True)
class Principle:
    """A founding product commitment: the vision, held as given rather than validated.

    In the logic-system reading prodc already uses (a need is a proposition, a proof its
    answer-with-evidence, an ``assumption`` a conjecture taken on faith *to be tested*), a principle
    differs in intent: it is a chosen frame the product is built on, not a bet pending validation.
    It is what decides between clients who want opposite things: a need that contradicts it is
    withdrawn ``out_of_scope`` citing it (:attr:`Withdrawal.principle`).

    Principles are discovered, not decreed: ``sources`` keeps the signals that surfaced one (often a
    client), and ``revised_at`` dates its latest statement. A decision taken under an older version
    of the principle is flagged for re-review when the principle is revised (the ripple). A separate noun
    (like :class:`Role`), not a Need marker: a principle is a stance, not what a person wants, so it
    never enters coverage, the plan, or the opinion check, in every ``scope`` (#88).

    ``scope`` says which kind of commitment it is (product, design, visual, engineering), so design,
    visual and engineering principles live on the board beside product ones instead of in prose docs
    and code comments, where a Decision or an ``out_of_scope`` withdrawal cannot cite them. The scope
    must be one declared in ``[principles].scopes`` (default ``["product"]``); an undeclared scope is a
    load error the author owns.

    ``proofs`` tie the principle to the guard tests that prove the code still obeys it, resolved by
    the same adapters as a need's proofs, and ``implemented_in`` points at the one place the values
    live (e.g. a tokens file). A pointer, not a copy: the hex/font values stay in code. Together
    they give the principle a :class:`PrincipleState` (ENFORCED / STATED / VIOLATED / BROKEN); a
    principle may not carry a ``need:`` proof: it guards the code, it does not wait on a need to
    settle. It still never enters coverage or the plan.
    """

    id: str
    text: str
    scope: str = (
        "product"  # product/design/visual/engineering: declared in [principles].scopes (#88)
    )
    revised_at: str | None = None  # ISO date the principle was last stated or revised
    sources: tuple[Source, ...] = ()  # the signals that surfaced it: provenance, not validation
    implemented_in: str | None = (
        None  # locator to the ONE place the values live; a pointer, not a copy (#89)
    )
    proofs: tuple[
        str, ...
    ] = ()  # guard-test locators, resolved by the same adapters as needs (#89)
    withdrawn: Withdrawal | None = None  # retired / out-of-scope: the record stays as its trace


@dataclass(frozen=True)
class Decision:
    """How a need gets built: the solution chosen for it, and the alternatives rejected.

    Not an ADR (an engineer's record) but the Opportunity-Solution-Tree node (Torres): a need is
    the opportunity, and a decision is *the solution picked for it over the ones considered*. prodc
    pushes solutions out of :class:`Need` (the solution-verb lint), so this is their only honest
    home. ``text`` is the chosen solution; ``alternatives`` are what was rejected. Without them a
    decision is a memo, not a choice. ``needs`` is required (a decision with no need it serves is
    engineering with no product reason, which the loader refuses), and ``principles`` ties the
    choice to the vision it rests on, so revising a principle after ``decided_at`` flags the
    decision stale: the same ripple a withdrawal gets. Like a Principle it never enters coverage,
    the plan, or the opinion check; its lifecycle reuses the Need verbs (``draft`` = proposed,
    ``withdrawn`` = superseded, keeping the record) rather than a status enum of its own.
    """

    id: str
    text: str  # the chosen solution
    needs: tuple[str, ...]  # the needs this decision serves: required, validated at load
    alternatives: tuple[str, ...] = ()  # the options rejected: what makes it a choice, not a memo
    consequences: str | None = None  # what the choice costs / rules out
    principles: tuple[str, ...] = ()  # the principle(s) it rests on; revising one ripples to here
    decided_at: str | None = None  # ISO date decided: the comparand for the principle ripple
    draft: bool = False  # proposed, not yet committed (reuses the Need draft lifecycle)
    withdrawn: Withdrawal | None = None  # superseded / abandoned: the record stays as its trace
    # The research this choice waits on (#93): ``<need-id>`` or ``<need-id>@yes|no|inconclusive``,
    # the ``need:`` proof grammar. Each is an ordinary need with a ``claim`` whose
    # state comes from its own proofs, so readiness is derived, never hand-set. "Waits on" is not
    # "serves" (``needs``): the loader refuses an id in both.
    awaits: tuple[str, ...] = ()


class AttestationKind(StrEnum):
    """Who reviewed the warrant: a ladder of strength, human strongest (cf. SourceKind)."""

    HUMAN = "human"  # a person judged that the proofs establish the need
    AI = "ai"  # a model reviewed it: weaker than a human, stronger than nothing


class Verdict(StrEnum):
    """A warrant review's conclusion. Only ``pass`` clears the need; anything else is a warning.

    A recorded ``fail`` or ``concerns`` must not read as a green warrant. The board cannot lie.
    """

    PASS = "pass"  # the proofs establish the need
    CONCERNS = "concerns"  # reviewed, but with reservations: not a clean pass
    FAIL = "fail"  # the proofs do NOT establish the need


@dataclass(frozen=True)
class Attestation:
    """A sign-off that a need's proofs actually establish its claim (#13).

    prodc can read that a proof resolves and passes, but not that it proves *this* need. An
    attestation records who reviewed that link and when: it does not prove fit, it makes the
    review visible and dated. A review can be a human's or an AI model's (``kind``); an AI
    review carries the model as ``who`` and keeps its verdict and comment for the register.
    """

    who: str  # a person's name, or the model id for an AI review
    date: str
    kind: AttestationKind = AttestationKind.HUMAN
    verdict: Verdict | None = None  # the reviewer's conclusion; only pass clears the warrant
    comment: str | None = None  # the review's feedback / rationale, kept on the record


class WithdrawalKind(StrEnum):
    """Why a need is off the board: the decision's *kind*, as data, not only free-text reason.

    All three take the need off the active board and out of coverage identically; the kind records
    *why* so the board can tell a validated-but-off-strategy need apart from one killed as not
    worth doing. ``OUT_OF_SCOPE`` is the case a real, client-evidenced need is declined because it
    is not the product being built, distinct from ``WONT_DO`` (decided against on its merits) and
    ``DUPLICATE`` (the same want is tracked under another need).
    """

    WONT_DO = "wont_do"  # decided against on its merits (the default, #74's original meaning)
    OUT_OF_SCOPE = "out_of_scope"  # real and valid, but not this product
    DUPLICATE = "duplicate"  # the same want is tracked elsewhere


@dataclass(frozen=True)
class Withdrawal:
    """A decision not to pursue a need: withdrawn / won't-do (#74).

    Unlike a draft (staged, not yet decided), a withdrawal is a decision *against*: the need is
    taken off the active board and out of coverage, with its ``reason``, ``date`` and ``kind`` kept
    on the record as the durable trace (``prodc show`` still renders it). Reinstate to put it back.
    ``principle`` names the :class:`Principle` the decision rests on (typically for ``out_of_scope``), so a
    later revision of that principle can flag this decision for re-review.
    """

    reason: str
    date: str
    kind: WithdrawalKind = WithdrawalKind.WONT_DO
    principle: str | None = None  # id of the Principle this decision rests on
    of: str | None = None  # id of the need this one duplicates (required when kind is duplicate)


@dataclass(frozen=True)
class Child:
    """One edge of a flow: the sub-need and, optionally, the ``step`` it plays in the journey (#90).

    A flow's ``children`` are ordered, and a use case ("job") is just a flow with a ``role`` set and
    a ``step`` on each edge (locate / execute / conclude). The step annotates the *edge*, not the
    sub-need. The same need can be the ``execute`` step of one flow and the ``locate`` of another,
    so it lives here, not on :class:`Need`. A bare ``US-050`` in YAML loads as ``Child("US-050")``
    with no step, so every existing flow keeps working unchanged.
    """

    id: str
    step: str | None = None


@dataclass(frozen=True)
class Outcome:
    """Whether a delivered need moved its goal: an observation, recorded by a person (#97).

    The proofs can pass while the feature changes nothing. ``landed: false`` keeps the need
    DELIVERED (its proofs are green) but makes its confidence weak and stops it counting toward
    its goal. prodc never reads the goal metric; ``evidence`` says where the observation came from.
    """

    landed: bool
    date: str
    who: str
    evidence: str | None = None  # free text or a locator: what was observed


@dataclass(frozen=True)
class NeedPath:
    """Where a role starts, what "done" looks like, and how many clicks it may take (#99).

    prodc does not model routes or count clicks. The project's own test counts them; ``proof``
    is the locator of that test, resolved like any other proof. The router stays the truth for
    routes.
    """

    start: str  # where the role begins, e.g. a route
    outcome: str  # a test id or route that means "done"
    max_clicks: int | None = None  # the click budget from start to outcome
    proof: str | None = None  # locator of the test that enforces the budget


@dataclass(frozen=True)
class Need:
    """What a named person wants, with its provenance and its proofs."""

    id: str
    text: str
    description: str | None = None  # optional free-form markdown detail; not EARS-checked (#73)
    who: str | None = None
    role: str | None = None  # id of the Role (role) this need's `who` plays (#52)
    must: bool = False
    sources: tuple[Source, ...] = ()
    proofs: tuple[str, ...] = ()  # locators, "<adapter>:<payload>" (leaf needs)
    children: tuple[Child, ...] = ()  # ordered sub-need edges (a flow is a Need with children)
    seam: tuple[str, ...] = ()  # end-to-end proof locators for a flow's between-steps behaviour
    client: str | None = None  # which client this instance is for; None = shared baseline
    variant_of: str | None = None  # id of the baseline need this specialises; None = standalone
    importance: int | None = None  # author-supplied ordinal (higher = more); refines ranking
    importance_set_at: str | None = None  # ISO date importance was last set/revisited (#59)
    claim: str | None = None  # what delivering this need would establish: the warrant to review
    attestation: Attestation | None = None  # human sign-off that the proofs establish the claim
    goal: str | None = None  # id of the Goal this need serves; None = no objective (flagged)
    release: str | None = None  # id of the Release slice this need ships in; None = unslotted
    expects: ProofKind | None = None  # the proof kind this need is waiting for (#78); advisory
    product: bool = True  # False = infra/NFR/internal, excluded from product coverage (#48)
    stage: Stage = Stage.COMMITTED  # the capture funnel (#77)
    draft_added: str | None = (
        None  # ISO date this need was staged (#60); lets a lint age-gate it later
    )
    withdrawn: Withdrawal | None = None  # a decision against this need: off the board (#74)
    answer: Answer | None = (
        None  # which way a settled need resolved (yes/no/inconclusive); None=open-ended
    )
    not_duplicate_of: tuple[str, ...] = ()  # ids this need is confirmed NOT a duplicate of (#55)
    not_variant_of: tuple[str, ...] = ()  # ids this need is confirmed NOT a shared variant of (#56)
    contradicts: tuple[
        str, ...
    ] = ()  # ids of needs this one opposes; symmetric, a principle decides
    outcome: Outcome | None = None  # did the delivery move the goal? (#97)
    path: NeedPath | None = None  # start, outcome, and click budget for this need (#99)
    tags: tuple[
        str, ...
    ] = ()  # flat, many-to-many, stateless labels: a filter axis, not a group (#80)
    terms: tuple[str, ...] = ()  # glossary terms this need uses (#72); each must be defined

    @property
    def draft(self) -> bool:
        """True while the need is staged off the board: the captured stage (#60, #77)."""
        return self.stage is Stage.CAPTURED

    @property
    def is_variant(self) -> bool:
        """A client-specific specialisation of a baseline need."""
        return self.variant_of is not None

    @property
    def is_opinion(self) -> bool:
        """No external evidence yet: no primary or secondary source, only an assumption or nothing.

        Not "no source": a bare need is an unrecorded assumption, so an opinion is a belief not yet
        grounded in the user or the world (Torres: an unvalidated desirability assumption).
        """
        return not any(s.kind in (SourceKind.PRIMARY, SourceKind.SECONDARY) for s in self.sources)

    @property
    def only_assumption(self) -> bool:
        """Has a source, but all of them are assumptions: a stated guess, no external evidence."""
        return len(self.sources) > 0 and all(s.kind is SourceKind.ASSUMPTION for s in self.sources)

    @property
    def strongest_kind(self) -> SourceKind | None:
        """The strongest source kind backing this need, or None when it is an opinion."""
        order = list(SourceKind)  # declaration order is strongest-first
        kinds = {s.kind for s in self.sources}
        return next((k for k in order if k in kinds), None)

    @property
    def is_withdrawn(self) -> bool:
        """A decision has been recorded against this need: withdrawn / won't-do (#74)."""
        return self.withdrawn is not None

    @property
    def counts_toward_coverage(self) -> bool:
        """Whether this need is a unit of product coverage. :func:`~prodc.status.summarize`
        counts.

        A leaf product need that has not been withdrawn. A flow (a need with ``children``) is a
        roll-up of its leaves, so counting it too would double-count (#43); a non-product need
        (infra/NFR/internal) is excluded from product coverage (#48); a withdrawn need is a
        decision against, so it is out of coverage entirely (#74). Draft staging is a separate,
        upstream filter (:func:`board_needs`), not part of this rule. A draft still counts
        once promoted onto the board (e.g. under ``--include-drafts``).
        """
        return not self.children and self.product and not self.is_withdrawn

    @property
    def excluded_reason(self) -> str | None:
        """Why this need is off the counted board, or ``None`` when it is on it.

        The single home for the lifecycle exclusions, so a new state lands here once: ``"withdrawn"``
        (a decision against, #74), ``"draft"`` (staged, not yet promoted, #60), and ``"nonproduct"``
        (infra/NFR/internal, #48). Withdrawal is checked first: a decision against overrides
        staging or scope. A flow is not excluded (it is a roll-up row on the board), so
        ``children`` is not a reason here (that axis is :attr:`counts_toward_coverage`).
        """
        if self.is_withdrawn:
            return "withdrawn"
        if self.draft:
            return "draft"
        if self.stage is Stage.TRIAGED:
            return "triaged"
        if not self.product:
            return "nonproduct"
        return None


def board_needs(needs: list[Need], *, include_drafts: bool) -> list[Need]:
    """The needs on the active board: a withdrawn need (#74) is always off it, and a draft (#60)
    is staged off until promoted.

    A withdrawn need is a decision against, so it is dropped unconditionally. There is no
    ``--include`` flag for it (its durable trace is the YAML record and ``prodc show``). Drafts
    are kept when ``include_drafts`` (the ``--include-drafts`` flag). The one place the
    board-membership rule lives, shared by ``status`` and ``plan`` so the two never diverge.
    """
    kept = [n for n in needs if not n.is_withdrawn]
    return kept if include_drafts else [n for n in kept if n.stage is Stage.COMMITTED]


class IssueStatus(StrEnum):
    """Where an issue's work stands, as its ``status:`` line records it."""

    OPEN = "open"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"  # waiting on a decision, a credential, or another issue
    DONE = "done"  # keeps the file; requires fixed_in


def _freeze(fields: Mapping[str, str | tuple[str, ...]]) -> Mapping[str, str | tuple[str, ...]]:
    return MappingProxyType(dict(fields))


@dataclass(frozen=True)
class Issue:
    """One issue file in a ``docs/issues/`` register: the engineering work behind needs (#36).

    :mod:`prodc.issue_store` is the only reader and writer. ``needs`` names the need ids the issue
    serves; ``sources`` holds pointers into other systems (``gitlab:#123``). ``extra`` holds the
    other front matter keys in file order, read-only, and is written back unchanged.
    """

    path: Path
    title: str
    status: IssueStatus
    area: str
    filed: str
    owner: str | None = None
    blocked_by: tuple[str, ...] = ()
    fixed_in: str | None = None
    extra: Mapping[str, str | tuple[str, ...]] = field(default_factory=lambda: _freeze({}))
    body: str = ""
    #: the front matter keys in the order the file had them; empty for an issue built in memory.
    order: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.extra, MappingProxyType):
            object.__setattr__(self, "extra", _freeze(self.extra))

    @property
    def id(self) -> str:
        """The file name without ``.md``."""
        return self.path.stem

    @property
    def slug(self) -> str:
        """The file name without ``.md`` and without its leading date (either date style)."""
        return re.sub(r"^(\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})-", "", self.path.stem)

    @property
    def open(self) -> bool:
        """True until the status is ``done``."""
        return self.status is not IssueStatus.DONE

    @property
    def is_closed(self) -> bool:
        """True when the status is ``done``."""
        return not self.open


@dataclass(frozen=True)
class Term:
    """What a word means here, globally or for one client (#72).

    The same word can mean different things in different places ("risk" for one client is not
    "risk" for the next). An entry names the term, says what it means, and says where: ``scope`` is
    ``None`` for every need, or ``client:<id>`` for the needs of that client. A need lists the terms
    it uses in ``terms``. prodc never looks for terms in need text: a listed term is a claim.
    """

    term: str
    text: str
    scope: str | None = None  # None = global; "client:<id>" = that client's needs only

    @property
    def client(self) -> str | None:
        """The client id of a ``client:<id>`` scope, else None."""
        return self.scope.partition(":")[2] if self.scope else None


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
    roles: tuple[Role, ...] = ()  # the roles needs' `who` play (#52)
    principles: tuple[Principle, ...] = ()  # the product vision, held as given
    decisions: tuple[Decision, ...] = ()  # the solutions chosen for needs (OST), with alternatives
    glossary: tuple[Term, ...] = ()  # what each term means, globally or per client (#72)
    issues: tuple[Issue, ...] = ()  # the engineering work behind needs, from [prodc].issues (#36)
    issues_skipped: tuple[str, ...] = ()  # "<file>: <why>" per issue file the store could not read
    # Removed keys (0.3 `label:`, `argument:`) found and ignored. `lint` fails on any (#96).
    notices: tuple[str, ...] = ()
    # Fields 0.12 removes that the files still use: printed once per run, a lint warning.
    deprecations: tuple[str, ...] = ()


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
    """Soft structural checks on need text: EARS shape, never a hard failure.

    A trigger clause (When/While/Where/If) with no observable outcome is flagged, as is a
    need with no outcome phrasing at all. These upgrade the solution-in-disguise heuristic
    into a shape check without rejecting a PM's wording.
    """
    first = text.strip().split(" ", 1)[0].lower().rstrip(":,")
    out: list[str] = []
    if first in _EARS_TRIGGERS and not _has_outcome(text):
        out.append(f"EARS: '{first}' clause without an observable outcome ('can'/'shall')")
    elif ears_shape(text) is EarsShape.UNCLASSIFIED:
        out.append("EARS: no observable outcome. Try 'When <trigger>, <who> can <outcome>'")
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
    confidence: Confidence | None = None  # only for a DELIVERED need (#97)
    confidence_detail: list[str] = field(default_factory=list[str])  # the rule that matched
    path_state: ProofState | None = None  # state of ``need.path.proof``; None when it has none
    declared_only: bool = False  # true if every proof of a DELIVERED leaf is declared (#103)
