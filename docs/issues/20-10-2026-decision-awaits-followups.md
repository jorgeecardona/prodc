# Decision awaits: deferred follow-ups (#93)

scope: S
verify: test
area: cli

## Context

#93 shipped `Decision.awaits` (0.4.10–0.4.11): a decision names the research needs it waits on,
and is BLOCKED until they settle. Reviewed with Fable; these were left out on purpose.

## Deferred

- **A setter** — `prodc await <decision> <need>[@answer]` (or `set D-1 awaits+=Q-1`). The writer's
  one-block splice is need-shaped; decisions are hand-edited until it learns decision blocks.
- **A status summary line** — "N decisions blocked". Only if boards grow enough decisions to
  need it; the per-decision tag is enough today.

## Never

- A research-kind enum (interview / fake-door / smoke / survey / spike / dataset). The proof
  adapter and a tag already say what kind of research it is.
- A hand-set `status:` on an awaited item. State comes from the need's proofs, or the board drifts.
