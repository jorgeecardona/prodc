# Draft needs: review command, age gate, portfolio exclusion (follow-up to #60)

scope: M
verify: test
area: cli

## What is done (#60, 0.3.x)

- `Need.draft` (bool), parsed by the loader.
- `prodc add --draft` stages a need; `[add].default_draft = true` makes every `add` a draft.
- Drafts are excluded from the counted board, coverage, recurrence and orphans in `status`, and
  from the `plan` backlog, unless `--include-drafts` is passed.
- `status` prints a `drafts: N staged` count line; `show` marks a draft; `status --json` carries
  `draft` per need.
- Promote a draft with `prodc set <id> draft=false` (and `set <id> draft=true` to re-stage);
  drop one by deleting it from the file.

## What is deferred

1. **`prodc review`** — list draft needs with text, client, sources and the duplicate-detection
   score (reuse dedup.py), plus `--promote <id>…` / `--promote-all` / `--drop <id>…`. Sugar over
   `set draft=false` and file deletion; `--drop` needs a delete-need write path the writer does
   not have yet.
2. **`lint` draft age gate (`[lint].draft_max_age_days`)** — fail on drafts older than N days so a
   batch cannot be forgotten. Needs a `draft_added` date stamped at `add --draft` time (drafts
   carry no timestamp today).
3. **`portfolio` draft exclusion** — apply the same filter when rolling up repos.
