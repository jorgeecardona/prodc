# Research-board profile: posed questions traced to answers-with-evidence

scope: L
verify: test
area: model

## Context

prodc models product work as needs (desired user outcomes) traced to evidence and resolved by a
proof. The same spine fits research: a **need becomes a posed question or claim**, the **proof
becomes the answer-with-evidence** (an experiment result, an eval gate, a formal proof, a cited
paper), and an **opinion** is a conjecture held without evidence yet. The intended uses are a
personal maths-research board and an ML-research-ideas board.

Most of the research board is a *reinterpretation* of the existing model, verified against the code
at 0.3.66:

- `is_opinion` (no primary/secondary source) already means "belief without evidence" → a conjecture.
- Source kinds reinterpret cleanly: primary = your own worked derivation/computation; secondary =
  a cited paper; assumption = a conjecture taken on faith.
- Declared-DELIVERED adapters (`accept`, `prototype`) already model "a human vouched, prodc did not
  check the proof" — the right shape for a cited published result.
- The `command` hook (#70) already shells out and reads back a state → a Lean/Coq check is zero new
  code, records-only (prodc never runs the prover, it reads the result).
- `Attestation` (#13) already models "I checked this, human/AI, dated" → the human attestation that
  a *formalization matches the informal claim*.
- `draft` (#60) already stages an uncounted need → a raw research idea before it is promoted to a
  hypothesis.
- `UNRESOLVED` ("source could not be read") already distinguishes "experiment has not run / results
  file missing" from BROKEN (locator points at nothing) and PENDING (ran, not green).

Two things are genuinely missing. They are the whole of this issue.

## Corrections to the initial framing (checked against the code)

- **#74 `withdrawn` cannot represent "settled-no."** It is a `Withdrawal` dataclass and
  `board_needs()` (model.py) drops withdrawn needs *unconditionally* — off-board, gone from
  coverage. A disproven hypothesis filed as withdrawn would hide that something was learned.
  `withdrawn` keeps its real meaning here too: a line of inquiry *abandoned without being settled*.
- **No `relates` need→need edge exists.** The only need→need edges are `children` (flow → sub-needs,
  a tree) and `variant_of` (variant → baseline). A proof is always a `"<adapter>:<payload>"` string;
  it never points at a need today. The sole precedent for cross-referencing need-ids is the GSN
  argument overlay (#28, `ArgNode.about` / `supported_by`).
- **#80 (tags/initiative) and #75 (eval-gate) are still proposals** — not in the code.

## Proposal

### 1. The data-model pivot: `answer` authored on the `Need` — do this first, alone

A need today conflates two axes: "is the outcome achieved?" and (for research) "is the question
settled?" DELIVERED means both "proven" and "yes." A research question answered **NO** is
DELIVERED-grade settledness with a NO answer — a result, not a gap.

Add an `Answer` StrEnum (`yes` / `no` / `inconclusive`) and an `answer: Answer | None = None` field
on the frozen `Need` — authored in YAML, validated by the loader via the existing
`try: Enum(name) except ValueError: raise LoaderError` pattern (as `SourceKind`/`ArgKind`), spliced
by the #53 one-need-block writer, serialized in the single `board.need_payload`. DELIVERED means
*settled*; `answer` says which way. Coverage (`counts_toward_coverage`, `summarize`) never reads
direction, so **a settled-no is DELIVERED and counts** — progress, not a gap. Product boards never
set `answer` and load/resolve/render identically to today.

**Named `answer`, not `verdict`, deliberately.** `verdict` is already taken: `Attestation.verdict`
(model.py:139) is the warrant reviewer's conclusion (pass/concerns/fail). Two "verdict" meanings in
one model — both surfacing in the board JSON as `need.verdict` vs `need.attestation.verdict` — would
be a data-model defect. `answer` also matches this doc's own spine: "a proof becomes the
answer-with-evidence," "a question answered NO."

**The proof asserts settledness; the answer says which way.** A proof resolves green when the
question is *settled* (e.g. `{"experiment_concluded": true}`, or a `command:lean/not_P` check that a
counterexample exists); the authored `answer` records the direction. Direction is always authored,
never computed — even a preregistered metric cannot produce a settled-NO, because `evalgate` and
`OutcomeAdapter` map below-threshold/failing to PENDING, never to a settled result. The act of
concluding "stop, this is the answer" is itself the authored decision; so is its direction.

**Decided (three independent code-grounded reviews): `answer` lives on `Need`, NOT on `ProofResult`
and NOT on `NeedResult`.** Rejected placing it on the proof result because:

- Proofs merge by an AND on *state* only (`_resolve_leaf`); there is no direction in the resolve
  path, so three green proofs disagreeing (yes/yes/no) would give DELIVERED with no derivable answer
  — a lossy merge with no honest default.
- `inconclusive` exists only at the question level; no adapter can emit it (adapters return
  delivered/pending/broken/unresolved only). On a proof the field would mean "what this evidence
  shows," on a need "what the answer is" — one field, two meanings.
- Its lifecycle is *authored*, not computed: direction is known by whoever wrote the locator, not
  derived by records-only prodc. That is the `withdrawn`/`attestation` lifecycle, i.e. the `Need`.
- Placement on `Need` leaves `ProofResult`, `NeedResult`, `_resolve_leaf`, every adapter, and the
  coverage math byte-for-byte unchanged — strictly smaller and lower-risk than touching the path.

Also rejected: a `SETTLED_NEGATIVE` sibling in `NeedState` — it pollutes every product code path and
the coverage math. `DELIVERED + answer` expresses *settled ≠ achieved* without a new enum value.

Honesty check (mirrors `_warrant_warnings`): warn only when `answer` is set but state ≠ DELIVERED —
"answer declared on an unsettled question." Keep it conservative: do **not** cross-check direction
against proof detail — a `command:lean/¬P` counterexample legitimately pairs DELIVERED with `no`, so
only the author knows which proof kind established the direction. Do not auto-roll-up `answer` to
flows; author it if a flow needs one. An optional `prodc answer <id> no` setter (sibling to
`accept`) can come later — hand-authoring works day one.

### 2. A `need` (needref) proof adapter: the question→question DAG

Research questions interconnect as a DAG, not a tree: "A's answer is B's premise," where A and B are
peers and B cannot be posed until A settles. `children` is a tree and cannot express this.

Add a proof adapter kind `need` whose payload is a need id. It resolves by looking up that need's
`NeedResult` and returning DELIVERED iff the referenced need is settled, else passing through
PENDING/HOLE. It rides the existing `proofs` tuple — no new field on `Need`, no new edge type. The
`Resolver` already has cycle detection and memoization, so A→B→A is handled for free; the adapter
needs a back-reference to the resolver (small wiring change — resolve lazily).

Do **not** add a first-class `depends_on` field: "B's proof is A being settled" *is* a proof, and
modelling it as one means `status`, `suggest`, and cycle-detection all work on it unchanged. A
parent→sub-question roll-up stays a flow (`children`); this adapter is only for the peer-DAG case.

An optional **directional** form `need:A@yes` is clean under this design: the adapter has the
`Resolver` back-reference and `Resolver._by_id` maps id→`Need`, so it reads the *authored* `A.answer`
directly — `need:A` resolves on settledness alone, `need:A@yes` on `A settled AND A.answer == yes`.
B does **not** inherit A's answer (B's answer is its own); the dependency only requires A settled,
optionally in a given direction. This is the case where putting `answer` on `ProofResult` looked
advantageous and is not: B delivers directional needrefs off the authored field with zero change to
the resolve path.

### 3. A per-board `profile` switch: swap the need grammar

EARS / solution-verb lint assumes a user-facing outcome and fires soft warnings (never a hard
failure) on "Prove that π is irrational." Nothing breaks — it is just noise on every need.

Add `[prodc].profile = "research"` (default `"product"`). The profile selects which text-lint runs:
product → EARS + solution-verb; research → a claim grammar (or none). EARS already lives behind one
function (`_text_warnings`), so this is a ~10-line config-driven swap, no model change.

A per-need `Need.kind` (`outcome` | `question` | `claim`) is the heavier fallback for a board that
mixes product needs and research questions. Defer it — a maths repo and an ML repo are each wholly
one profile; add `kind` only when a mixed board actually appears.

### 4. An `evalgate` adapter (#75): scored metric vs threshold

A thin sibling of the OutcomeAdapter. OutcomeAdapter reads `{"key": true|false}`; `evalgate` reads
`{"key": {"score": 0.82}}` plus a configured `threshold`. DELIVERED iff `score >= threshold`,
PENDING if recorded below, UNRESOLVED if the key is absent; the score goes in `detail` so the board
shows the margin. Records-only — prodc reads the results file, never runs the eval.

### 5. A `citation` adapter (optional)

A declared-DELIVERED adapter modelled on `PrototypeAdapter` (~15 lines), payload like
`ref@author@year`, carrying the `*` "declared, not checked" marker. Honest that a human cited the
result rather than prodc verifying it. Reuse `accept` at first if this is not worth its own kind.

## Board shapes

**Maths:** need = a proposition ("π is irrational"). A theorem with lemmas = a flow (`children` =
lemmas) or a leaf whose proofs are `need:<lemma-id>` refs (the DAG case). Lean/Coq proof via the
`command` hook; cited result via `accept`/`citation`; formalization-matches-claim via `Attestation`.
"Is the Collatz conjecture false?" answered by a counterexample → DELIVERED with `answer: no`.

**ML ideas:** idea = `draft` need; promote to hypothesis by un-drafting; experiment result = the
proof (`evalgate` for scored, OutcomeAdapter for pass/fail). Disproven hypothesis =
DELIVERED + `answer: no` (a result, counted). Abandoned-untested = `withdrawn` (off-board). The
current model, with only `withdrawn`, would force a disproven hypothesis to be filed dishonestly as
withdrawn — the concrete reason `answer` is necessary, not cosmetic.

## Build order

1. `Answer` StrEnum + `Need.answer` — the settled-vs-achieved pivot, authored on the need (not on
   `ProofResult`/`NeedResult`). Loader validation + `board.need_payload` + #53 splice + the
   conservative honesty warning. Model change; show the diff; patch bump.
2. The `need` (needref) proof adapter — the question→question DAG, cycle-safe for free; reads
   authored `Need.answer` off `Resolver._by_id` for the optional `need:A@yes` directional form.
3. `profile = "research"` config switch — silences EARS noise, swaps the grammar.
4. `evalgate` adapter (#75).
5. `citation` adapter (optional; reuse `accept` at first).

Items 3–5 need almost no model change — they are the "adapters are pluggable proof kinds" promise
paying off. The research board is ~80% reinterpretation plus two genuine additions: `answer` and
the needref edge. The silent goal holds — the agent becomes the researcher, prodc still only records
structure.

---
scope: L · verify: test · area: model · relates: #74 (withdrawn ≠ settled-no), #75 (evalgate), #80 (initiative roll-up), #70 (command hook), #28 (GSN overlay), #13 (attestation), #60 (draft), #25 (OutcomeAdapter)
