# Lifecycle

A need moves through states as evidence arrives. Two things anchor this page:

- **It is machine-checked.** `tests/test_models.py` builds a [musil](https://pypi.org/project/musil/)
  model of the lifecycle and explores every reachable state, asserting prodc's invariants hold in
  all of them. The model never re-implements a rule: each invariant calls the real resolver, so
  the model and the code cannot drift.
- **It is grounded.** Each transition names its source in Teresa Torres, *Continuous Discovery
  Habits* (see [Grounding (Torres)](grounding-torres.md)). Transitions with no PM-literature source
  are flagged as prodc's own: they track delivery integrity, which a discovery-only model omits.

## Leaf states

A leaf need (no children) is resolved from its proofs.

| State | Meaning |
|---|---|
| *opinion* | no `primary` or `secondary` source (only an assumption, or none): an unvalidated desirability assumption |
| `HOLE` | sourced, but no proof at all (an honest gap, never a failure) |
| `PENDING` | a proof is declared/planned, not yet green |
| `DELIVERED` | every proof is green |
| `BROKEN` | a proof locator points at nothing |
| `UNRESOLVED` | a proof's source could not be read (e.g. a sibling repo is absent) |

## Transitions

| Event | Move | Grounding |
|---|---|---|
| `source` | opinion → sourced | **Torres Ch. 2.** An opportunity must come from a specific customer story, not a company want. prodc grades the source `primary` > `secondary` > `assumption` (the academic primary/secondary split, plus the floor), and warns on a primary source with no named person or no quote/locator (behaviour over stated intent). |
| `declare-proof` | → `PENDING` | **Torres Ch. 9.** Name the assumption that must be true and make it testable ("articulated"). A declared proof is the test the need is waiting on. |
| `proof-passes` | `PENDING` → `DELIVERED` | **Torres Ch. 10**, *with a caveat* (see the gap below). The test meets its success criteria; the assumption is "more known". |
| `attest` | `DELIVERED` + human sign-off | **Torres Ch. 10.** "Our goal is not to seek truth but to mitigate risk." A human judges that the green proof actually establishes *this* need (the warrant). Only a `DELIVERED` leaf can be attested (enforced as a guard). |
| `proof-relink` | `BROKEN` → `PENDING` | **Loosely Torres Ch. 10** (redesign a test). Mostly a prodc hygiene move. |
| `proof-breaks` | → `BROKEN` | **prodc's own (no Torres source).** A locator stopped resolving. This is delivery-integrity, not discovery. |
| `proof-unresolved` | → `UNRESOLVED` | **prodc's own (no Torres source).** A proof's source could not be read. Delivery-integrity, not discovery. |

## Flow roll-up

A flow (a need with `children`) aggregates its children plus its own `seam` proofs (the behaviour
*between* steps). The model proves the roll-up rules exactly:

- **`broken-propagates`**: any `BROKEN` child or seam makes the flow `BROKEN`. A break is never
  hidden under a green parent.
- **`delivered-iff-all-green`**: a flow is `DELIVERED` exactly when it has children, all are
  `DELIVERED`, and every seam proof is green (no seam = vacuously green).
- **`unresolved-below-broken`**: with nothing broken, any `UNRESOLVED` child or seam makes the
  flow `UNRESOLVED` (it cannot be judged yet).

## Invariants proven

For the leaf lifecycle, across all reachable states:

- **`no-green-without-proof`**: `DELIVERED` only when the need has proofs and every one is green.
- **`hole-iff-no-proof`**: `HOLE` is exactly "no proof at all", never caused by a failing proof.
- **`broken-surfaces`**: a broken locator dominates; it is never hidden under pending/delivered.

## The honest gap: "proven" vs. "sufficiently known"

prodc models evidence as a discrete ladder (`HOLE → PENDING → DELIVERED`). Torres rejects that
framing for discovery:

> "We are not validating or invalidating anything... our research findings are not truths — they
> are merely confirming or disconfirming evidence... Our goal is not to seek truth but to mitigate
> risk." (Ch. 10)

For her, evidence is a **gradient** (importance × evidence), moving incrementally; an assumption is
never "proven", only "sufficiently known". prodc approximates that gradient with three softeners
rather than pretending `DELIVERED` means *true*:

- **source kind** ranks how strong the backing is (`primary` beats `assumption`);
- **`importance`** carries the author's ordinal, revisited over time;
- **`attestation`** records a human warrant; prodc warns on a `DELIVERED` leaf whose warrant no
  human has reviewed.

What prodc deliberately does **not** model (Torres's discovery loop, out of prodc's scope): the
opportunity solution tree and its weekly restructuring, parallel testing of competing solutions,
and the two-way-door reversal of a target opportunity. prodc records needs and the evidence under
them; it is not an OST editor. The one reversal worth considering later is re-opening a
`DELIVERED` need when its outcome does not land.
