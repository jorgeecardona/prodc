---
title: "Evidence staleness: git fallback + brief section (follow-up to #58)"
status: open
area: status
owner: null
filed: 2026-10-05
needs:
  - PD-12
scope: S
verify: test
---

## What is done (#58, 0.3.x)

- `Source.observed_at` (ISO date), parsed by the loader.
- `prodc capture --observed-at` (defaults to today) writes it.
- `status.evidence_age_days` / `last_observed` derive the age from the newest `observed_at`.
- `prodc status --stale DAYS` filters to needs older than DAYS.
- `status --json` / `show --json` always carry `evidence_age` and `last_observed_at`.
- `prodc lint` flags needs older than `[lint].stale_after_days` when set.

## What is deferred

1. **git fallback for needs with no `observed_at`.** The issue asks that a need whose sources
   lack `observed_at` fall back to the file's last git commit date. That needs per-need file
   provenance — the loader does not currently record which file a `Need` came from, and the
   proof adapters deliberately avoid shelling out to the `git` binary (`adapters._git_head`
   reads `.git/HEAD` directly). Wiring file provenance onto `Need` + a best-effort `git log`
   read is a separate, larger change; today a need with no `observed_at` reports age `unknown`.

2. **`brief <client>` "confirm still wanted" section.** List the client's stale needs in the
   pre-meeting agenda. Small, additive to `_cmd_brief`; left out of the first slice.
