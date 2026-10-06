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

## Also done (0.3.x)

1. **`suggest --apply`** — writes the single best suggestion per HOLE need as a proof (honours
   `--min-score`), printing each need's diff; `--dry-run` validates without writing, `--json`
   lists the writes. Idempotent (re-applying an existing locator is a no-op). Per need it is one
   single-file, reload-validated edit via `writer.add_proof`.

## What is still deferred

2. **More adapter inventories** — pytest (collect node ids), files (glob the script dirs). Pytest
   needs a real collection step; files needs the configured globs. Both are cheap-ish but out of
   this slice.
3. **BROKEN relink** — when a locator no longer resolves (a renamed test), propose the nearest
   inventory entry and let `--apply` relink it. Depends on #1.
