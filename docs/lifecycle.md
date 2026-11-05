# Lifecycle

A need moves through states as evidence arrives. Two things anchor this page:

- **It is machine-checked.** `tests/test_models.py` builds a [musil](https://pypi.org/project/musil/)
  model of the lifecycle and explores every reachable state, asserting prodc's invariants hold in
  all of them. The model never re-implements a rule: each invariant calls the real resolver, so
  the model and the code cannot drift.
- **It is grounded.** Each transition names its source in Teresa Torres, *Continuous Discovery
  Habits* (see [Grounding (Torres)](grounding-torres.md)). Transitions with no PM-literature source
  are flagged as prodc's own: they track delivery integrity, which a discovery-only model omits.

## Capture stages

A need has a capture `stage` (#77). Only `committed` needs count toward coverage.

| Stage | Meaning | Shown by `status` |
|---|---|---|
| `captured` | a raw idea, same as `draft: true` | hidden, shown with `--include-drafts` |
| `triaged` | reviewed, not committed | listed apart, not counted |
| `committed` | accepted as work, the default with no `stage` and no `draft` | on the board, counted |

Move a need with `prodc review`:

- `--promote ID` moves it one stage: `captured` to `triaged`, or `triaged` to `committed`.
- `--promote-all` moves every staged need to `committed`, except any named in `--drop`.
- `--drop ID` deletes it.

The stages are separate from the leaf states below, which are resolved from sources and proofs.

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

A `DELIVERED` need also shows a **confidence**: `weak`, `medium` or `strong` (#97). It is derived
from recorded facts, first match wins:

| Rule | Confidence |
|---|---|
| `outcome.landed: false` | weak |
| attestation verdict `fail` | weak |
| declared proof (tag or existence, no results file) | weak |
| opinion (no primary or secondary source) | weak |
| human `pass`, strongest source `primary` | strong |
| anything else | medium |

A missing attestation is medium, not weak: #13 already warns on it. Evidence age is not an input,
so the confidence changes only when a recorded fact changes. A declared proof cannot regress (there
is nothing to re-run), so it holds the confidence at weak. A flow takes the lowest confidence of
its steps. `tests/test_models.py` model-checks these properties against the real resolver.

When the proofs pass but the feature did not move the goal, record it:

```bash
prodc outcome R-1 --not-landed --by jorge --date 2026-10-24 --evidence "starts flat for 4 weeks"
```

The need stays `DELIVERED` (its proofs are green) and still counts toward board coverage. Its
confidence becomes weak, it gets a warning, and its goal no longer counts it as delivered. Coverage
answers "is it built"; the goal answers "did it move". `--landed` records the result and changes
nothing else.

What prodc deliberately does **not** model (Torres's discovery loop, out of prodc's scope): the
opportunity solution tree and its weekly restructuring, parallel testing of competing solutions,
and the two-way-door reversal of a target opportunity. prodc records needs and the evidence under
them; it is not an OST editor. A `DELIVERED` need whose outcome did not land is not re-opened: it
stays delivered, and its goal stops counting it (see above).
