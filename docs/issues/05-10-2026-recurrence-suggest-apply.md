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

## Also done (0.3.x)

**`recurrence --suggest --apply`.** Creates a shared baseline need (no `client`, text from the
group's highest-importance member) and sets `variant_of` on every member, writing the files so the
result shows in the diff. Links the single highest-scoring group per run, taking `--baseline-id`
and `--file`; remaining groups are reported to rerun. `--dry-run` previews.

The multi-file write is transactional (`writer.link_variant_group`): all touched files are
snapshotted up front, the baseline is created first so members' `variant_of` resolves, members are
spliced comment-safe, and the whole model is reloaded once as the gate — any rejection (or
`--dry-run`) restores every file (a newly created file removed, not left empty). Note the earlier
"reuse a client-less member as the baseline" idea does not apply: `variant_suggestions` excludes
client-less needs, so a suggested group is always all-client and a baseline is always created.
