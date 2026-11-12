---
title: "Proof discovery: --apply, more adapter inventories, BROKEN relink (follow-up to #54)"
status: open
area: adapters
owner: null
filed: 2026-10-05
needs:
  - PD-14
scope: M
verify: test
---

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
   this slice. (Still deferred — demand-driven.)

## Also done (0.3.x)

3. ✅ **BROKEN relink** — `prodc suggest --relink` proposes, for each BROKEN leaf need, the nearest
   live inventory entry to replace each broken locator (`status.relink_suggestions` +
   `RelinkSuggestion`). Scores each candidate by the similarity of its matchable part to the broken
   id's (a renamed test: old title → new title), falling back to the need text; proposes only
   within the *same* adapter (the kind is stable, the id drifted), and skips a locator whose
   adapter is absent entirely (no inventory to match against). `--relink --apply` writes the best
   per broken locator via a new `writer.relink_proof` (swap-in-place + de-dupe, one reload-gated
   single-file splice); `--dry-run`/`--json`/`--min-score`/`--top`/`--kind` all carry over.
