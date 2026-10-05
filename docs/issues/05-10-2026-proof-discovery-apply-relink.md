# Proof discovery: --apply, more adapter inventories, BROKEN relink (follow-up to #54)

scope: M
verify: test
area: adapters

## What is done (#54, 0.3.x)

- `Inventoried` protocol (weaker than `Enumerable`: just `inventory()`), so an adapter can offer
  suggestions without changing orphan behaviour.
- `inventory()` on GherkinAdapter (already had it), CoverageAdapter and FieldAdapter.
- `status.proof_suggestions`: for every HOLE leaf need, rank each enumerable adapter's units by
  text similarity (reuses the #55 matcher) and return ready-to-paste `<adapter>:<id>` locators.
- `prodc suggest [need-id]` (read-only) with `--min-score`, `--top`, `--kind`, and `--json`.

## What is deferred

1. **`suggest --apply`** — write the top suggestion above a threshold as a proof, in bulk, printing
   what was written per need so the batch shows in the diff. Reuses the `set proofs+=` write path;
   left out so the first slice stays read-only.
2. **More adapter inventories** — pytest (collect node ids), files (glob the script dirs). Pytest
   needs a real collection step; files needs the configured globs. Both are cheap-ish but out of
   this slice.
3. **BROKEN relink** — when a locator no longer resolves (a renamed test), propose the nearest
   inventory entry and let `--apply` relink it. Depends on #1.
