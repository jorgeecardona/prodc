---
title: "Draft needs: review command, age gate, portfolio exclusion (follow-up to #60)"
status: open
scope: "M"
verify: test
area: cli
---

## What is done (#60, 0.3.x)

- `Need.draft` (bool), parsed by the loader.
- `prodc add --draft` stages a need; `[add].default_draft = true` makes every `add` a draft.
- Drafts are excluded from the counted board, coverage, recurrence and orphans in `status`, and
  from the `plan` backlog, unless `--include-drafts` is passed.
- `status` prints a `drafts: N staged` count line; `show` marks a draft; `status --json` carries
  `draft` per need.
- Promote a draft with `prodc set <id> draft=false` (and `set <id> draft=true` to re-stage);
  drop one by deleting it from the file.

## Also done (0.3.x)

1. ✅ **`prodc review`** — lists draft needs with who/client, sources and the nearest-need
   duplicate score (reuses `dedup.matches_for`), plus `--promote <id>…` / `--promote-all` /
   `--drop <id>…` and `--dry-run`/`--json`. `--promote-all` promotes every draft except any named
   in `--drop`; a target must be a staged draft (a real need is withdrawn, not dropped). Sequential
   and independent like `suggest --apply` (each a reload-gated single-file edit, abort on first
   reject). `--drop` is backed by a new general **`writer.delete_need`** — a comment-safe excise
   (the #53 splice, reversed) made referentially safe by the reload gate: deleting a need still
   pointed at by `children`/`variant_of`/a `need:` proof is rejected and reverted.

   Also shipped the **`draft_added`** prerequisite for the age gate below: `Need.draft_added` (ISO
   date), parsed by the loader, stamped by `add --draft`. The field exists and round-trips; the
   lint gate that reads it is still deferred.

2. ✅ **`lint` draft age gate (`[lint].draft_max_age_days`)** — `Config.draft_max_age_days`
   (validated positive int), and `_annotate_draft_age_warnings` in `cmd_lint` (mirrors the
   `importance_revisit_days` check): a dated draft past the limit warns with its age, an undated
   draft warns it has no staged date (not silently exempt). A warning, never a hard error — only
   runs when the knob is set.
3. ✅ **`portfolio` draft exclusion** — `_repo_row` now gathers through
   `board_needs(…, include_drafts=False)`, so a repo's portfolio line counts the same board as
   `status`/`plan` (drafts and withdrawn off). (This also fixed withdrawn needs being counted in
   the roll-up, since the row previously resolved the raw need list.)

Issue complete.
