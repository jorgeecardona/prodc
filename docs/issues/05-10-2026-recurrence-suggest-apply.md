# recurrence --suggest --apply: auto-create the shared baseline (follow-up to #56)

scope: M
verify: test
area: cli

## What is done (#56, 0.3.x)

- `not_variant_of` field on a Need (mirrors `not_duplicate_of`), parsed by the loader.
- `dedup.variant_suggestions`: union-find grouping of unlinked, cross-client, similar needs.
- `prodc recurrence` prints shared baselines; `prodc recurrence --suggest` prints the unlinked
  candidate groups with scores (read-only).
- `prodc lint` surfaces an unlinked cross-client recurrence group as a hygiene warning,
  suppressible by setting `variant_of` or `not_variant_of` on a member.

## What is deferred

**`recurrence --suggest --apply`.** Create a shared baseline need (no `client`, text from the
highest-importance member or `--text`) and set `variant_of` on every group member, writing the
files so the result shows in the diff. If one member already has no `client`, use it as the
baseline. This writes a *new* file and edits several existing ones in one command — the writer
today edits a single located file per call, so `--apply` needs a multi-file write path. Left out
of the first slice; depends on the same careful write handling as #53.
