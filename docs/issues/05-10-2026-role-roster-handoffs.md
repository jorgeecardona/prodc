# Role: roster grouping, orphan report, handoffs, write-back (follow-up to #52)

scope: M
verify: test
area: cli

## What is done (#52, 0.3.x)

- `Role(id, text)` noun — a role; client-agnostic. Declared in a top-level `roles:` list,
  loaded into `Model.roles` like goals/releases.
- `Need.role` — the role id this need's `who` plays. `who` stays the person's free-text name,
  `client` the org; the (who, client) pair is the instance, `role` the archetype.
- `role` refs are hard-validated at load (unconditionally, like `goal`/`release`).
- Surfaced: `show` prints `who: john — owner`; `status --json` lists `roles` and carries
  `role` per need; `set <id> role=<id>` writes it.

## Also done (#52, roster + handoffs pass)

1. **Roster grouping by role** — `status` (and `status --client`, which scopes the needs first)
   now prints a `roles:` section: per-role coverage like goals/releases, a declared role with
   zero needs shown as an orphan-role line, and a `⚠` for any need whose `who` plays no declared
   role. `status --json` carries `roles[].coverage/orphan` and `unroled`. `role` is a `--columns`
   column. (`status.role_report`)
2. **Derived handoffs** — `status` prints a `handoffs:` section (and `status --json` a `handoffs`
   list) derived from each flow's ordered `children`: consecutive steps whose `role` differs.
   The noise the earlier note feared is avoided by keying on `role`, not `who`: `role` is set
   deliberately per need and is never inherited from a file-level default, so a shared file-level
   `who` no longer fabricates handoffs. No new edge type — the `children` order is the sequence.
   (`status.handoffs`)

3. **`add role` / dedicated write-back** — done: `prodc add role <id> --text <desc> --file <path>`
   declares a Role in that file's top-level `roles:` list (new file created if needed),
   duplicate id refused, `--dry-run`/`--json`/`--expect-sha` like the other writers.
   (`writer.add_role`; a dry-run or rejected first-write now leaves no empty file behind.)

## What is still deferred

4. **`Need.label` deprecation** — once roles carry the role description, the per-need `label`
   (hoisted onto the roster today) is redundant. Deprecate separately.
