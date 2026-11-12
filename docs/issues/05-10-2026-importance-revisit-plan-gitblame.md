---
title: "Importance rubric: plan --revisit, add --importance, git-blame fallback (follow-up to #59)"
status: open
area: cli
owner: null
filed: 2026-10-05
needs:
  - PD-13
scope: S
verify: test
---

## What is done (#59, 0.3.x)

- `[importance].levels = [[n, label, meaning], …]` config scale, validated.
- `Config.resolve_importance` (number or label → level, off-scale rejected) and
  `Config.importance_label`.
- `Need.importance_set_at` (ISO date), parsed by the loader.
- `prodc set <id> importance=<n|label>` validates against the scale and stamps
  `importance_set_at` in the same edit (`writer.set_importance`).
- `prodc show` prints `importance: N (label), set <date>`; `status --json` carries
  `importance_set_at`.
- `prodc lint` flags: importance off the declared scale; importance set with no revisit date;
  importance older than `[lint].importance_revisit_days`.

## What is deferred

1. **`plan --revisit <days>`** — a plan view filtered to needs whose importance is stale or
   undated, so a backlog pass can refresh them. Small; left out of the first slice.
2. **`add --importance <n|label>`** — let `add need` set importance (and stamp the date) at
   creation, not only via a later `set`.
3. **git-blame fallback for `importance_set_at`** — when a need was hand-edited without the
   date, fall back to the file's git blame for that line. Same per-need file-provenance gap as
   the #58 fallback (docs/issues/05-10-2026-evidence-staleness-git-fallback.md); deferred with it.
