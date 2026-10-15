# Product principles and the contradiction edge — the vision as the logic's principles

scope: L
verify: test
area: model

## Context

Raised in the same thread as the out-of-scope decision (#74 follow-up,
docs/issues/15-10-2026-out-of-scope-need-state.md). Clients come from different points of view and
may want to solve problems in *opposite* ways. What decides between them is not more client
evidence — it is the founder's own **product vision**. The PM's framing: the vision is a set of
**principles**, in the logic-system sense prodc already leans on (need = proposition, proof =
answer-with-evidence, `assumption` = "a conjecture taken on faith", from the research-board issue).

Three properties the PM named, which the model must respect:

1. **A principle is not an assumption.** An `assumption` is a *bet pending validation* (`is_opinion` —
   you hope to confirm or refute it against the user/world). A principle is a *chosen frame held as
   given* — you do not validate it away, you commit to it. prodc today has the conjecture
   (`assumption`); it has no principle. The difference is intent: provisional vs foundational.

2. **Principles ripple.** Changing a principle "changes the way we do logic" — it re-derives what is in
   scope. It is not a local edit: a need that was `out_of_scope` *because of* a principle should come
   back up for review when that principle changes, and a need that was in scope might fall out. So an
   principle is load-bearing for other needs' lifecycle, the way a baseline is for its variants.

3. **Principles are discovered on the go.** The PM feels they are discovering the product they want to
   build as they go, and **clients help discover the principles**. So a principle is not fixed up front:
   it can start life as an `assumption` surfaced by client work and get *promoted* to a principle once
   the PM commits to it — a lifecycle, like a draft being promoted or importance being revisited.

## The two gaps

### A. The principle as a first-class need stance

A need (or a free-standing statement) that the PM holds as a founding commitment, not as evidence.
It never counts as a desirability bet (`is_opinion` should not apply / should not nag for a
primary source), and it is the thing an `out_of_scope` decision can *cite* as its reason.

Open question — is a principle a `Need` with a marker, or its own noun?
- **Marker on Need** (`kind: principle`, or `principle: true`): cheapest; rides the existing loader/writer/
  splice. But a principle is not really "what a named person wants" (the Need definition) — it is a
  product stance, so the fit is loose.
- **A new noun** (`principles:` top-level list, like `roles:`/`goals:`): cleaner semantically, matches
  how #52 added `Role`. Heavier: a new loader path, writer, and references.

~~Lean: start with the marker~~ — **Decided (15-10-2026): own noun.** A principle is a stance, not
what a person wants, so a Need marker would make `Need` mean two things and force every Need path
(coverage, plan, brief, suggest, the opinion check) to special-case it — a principle never gets a
proof, so as a Need it would be a permanent HOLE. As a noun (like `Role`) no Need path changes.
Shape: `principles: [{id, text, revised_at, sources}]`; `sources` keeps the signals that surfaced it.

### B. The contradiction edge

Two needs that oppose each other have no edge today — the only need→need edges are `children`
(flow tree), `variant_of` (recurrence), and `need:` (the dependency DAG). Add a `contradicts`
need→need relation (symmetric), so the board can *show* that N-1 and N-2 are in tension and that an
principle (A) resolves it: A ⇒ N-1 in scope, N-2 `out_of_scope`. This is the structural home for
"clients want opposite things; the vision decides."

Cycle/consistency note: unlike `need:` (acyclic, memoized by the Resolver), `contradicts` is a
plain symmetric annotation, not a proof — it does not resolve to a state, it just records tension.
A lint check could flag two needs that `contradict` yet are *both* live on the board (an
unresolved contradiction the vision has not yet decided).

## The rippling mechanism (property 2, made concrete)

Tie the `out_of_scope` withdrawal (just shipped) to the principle that caused it: let an
`out_of_scope` withdrawal name the principle id it rests on (`withdrawn: {kind: out_of_scope, principle: P-3}`).
Then changing or retiring P-3 surfaces every need withdrawn under it as "decided against a now-changed
principle — re-review" (a lint warning, the same shape as the staleness/revisit nudges). This is the
smallest honest version of "principles ripple" — records-only, no recomputation prodc isn't entitled to
make, the agent/PM re-decides.

## Discovery lifecycle (property 3)

An `assumption`-sourced need the PM commits to becomes a principle: a promote step
(`prodc promote-principle <id>` or `set <id> kind=principle`), sibling to draft-promotion. The provenance
stays — the source list still shows the client signals that *led* to the principle — but the stance
changes from "bet to validate" to "frame we build on". This keeps the honest history: the principle was
discovered, not decreed.

## Build order (proposed — settle A's shape first)

1. Decide marker-vs-noun for the principle (A). Smallest slice: a stance that exempts a need from the
   opinion nag and can be cited.
2. `out_of_scope` withdrawal cites its principle; lint re-review when the principle changes (the ripple).
3. The `contradicts` edge + the "both-live contradiction" lint.
4. The discovery/promote lifecycle (assumption → principle), once the shape is fixed.

Keep the silent goal: the agent is the PM discovering the product; prodc records the structure of
that discovery (the principles, the contradictions, the scope decisions) — it never decides them.

## Naming (15-10-2026)

Shipped as the noun **`principle`**, not `axiom`. The logic-system reading above (need = proposition,
`assumption` = conjecture, the founding frame = "axiom") is the right *intuition*, but "axiom" reads
as math jargon a working PM flinches at — it does not fit the usual PM vocabulary (closest standard
terms: "product principles", or Amazon's "tenets"). The concept is unchanged: a frame held as given,
not validated, that decides between clients who want opposite things, and that ripples when revised.

## Progress (15-10-2026) — steps 1+2 DONE, committed

Shipped (steps 1+2 of the build order):
- `model.Principle(id, text, revised_at, sources)`, `Model.principles`, `Withdrawal.principle`.
- Loader: `principles:` list parsed (`_principle`), ids unique, a withdrawal's `principle` checked
  against declared principles (`_check_ref`), source roles validated on principle sources too.
- `status.PrincipleReport` + `principle_report(needs, principles)`: per principle, the needs
  withdrawn citing it (`declined`) and those decided before its `revised_at` (`stale` — the ripple).
- `board.ResolvedBoard.principles` (over the whole `model.needs`); `need_payload` carries `principle`.
- Writer: `_block_span(lines, key, id)` / `_render_item_edit` generalise the comment-safe splice to
  any top-level list; `withdraw(principle=…)`, `add_principle(…, revised_at)`, `revise_principle(…)`.
- CLI: `prodc add principle <id> --text …`, `prodc revise principle <id> [--text] [--date]`,
  `prodc withdraw … --principle <id>`; `status` text + `--json` carry a `principles:` section;
  `show` names the principle on the withdrawn line; `lint` warns the ripple (stale decision);
  `tests/test_principles.py`; agent playbook rows.

Next: step 3 (the `contradicts` need→need edge + both-live-contradiction lint), step 4 (the
discovery lifecycle — an `assumption` surfaced by clients promoted to a principle).

---
scope: L · verify: test · area: model · relates: out-of-scope (#74 follow-up), #52 (role noun), research-board profile (logic-system framing), #56 (variant_of as a need→need edge precedent)
