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

## What is deferred

1. **Roster grouping by role** — group the board / `brief <client>` by client → role, and
   show a declared role with zero needs (an orphan-role line, like orphan goals).
2. **Derived handoffs** — a report over an ordered cross-role flow's `children` (consecutive
   steps whose `who`/`role` differ). Noisy as-is because children inherit a file-level `who`;
   needs its own design. No new edge type.
3. **`add role` / dedicated write-back** — today a role is hand-authored or `set` on a need.
4. **`Need.label` deprecation** — once roles carry the role description, the per-need `label`
   (hoisted onto the roster today) is redundant. Deprecate separately.
