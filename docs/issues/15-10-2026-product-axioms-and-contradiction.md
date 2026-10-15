# Product axioms and the contradiction edge — the vision as the logic's axioms

scope: L
verify: test
area: model

## Context

Raised in the same thread as the out-of-scope decision (#74 follow-up,
docs/issues/15-10-2026-out-of-scope-need-state.md). Clients come from different points of view and
may want to solve problems in *opposite* ways. What decides between them is not more client
evidence — it is the founder's own **product vision**. The PM's framing: the vision is a set of
**axioms**, in the logic-system sense prodc already leans on (need = proposition, proof =
answer-with-evidence, `assumption` = "a conjecture taken on faith", from the research-board issue).

Three properties the PM named, which the model must respect:

1. **An axiom is not an assumption.** An `assumption` is a *bet pending validation* (`is_opinion` —
   you hope to confirm or refute it against the user/world). An axiom is a *chosen frame held as
   given* — you do not validate it away, you commit to it. prodc today has the conjecture
   (`assumption`); it has no axiom. The difference is intent: provisional vs foundational.

2. **Axioms ripple.** Changing an axiom "changes the way we do logic" — it re-derives what is in
   scope. It is not a local edit: a need that was `out_of_scope` *because of* an axiom should come
   back up for review when that axiom changes, and a need that was in scope might fall out. So an
   axiom is load-bearing for other needs' lifecycle, the way a baseline is for its variants.

3. **Axioms are discovered on the go.** The PM feels they are discovering the product they want to
   build as they go, and **clients help discover the axioms**. So an axiom is not fixed up front:
   it can start life as an `assumption` surfaced by client work and get *promoted* to an axiom once
   the PM commits to it — a lifecycle, like a draft being promoted or importance being revisited.

## The two gaps

### A. The axiom as a first-class need stance

A need (or a free-standing statement) that the PM holds as a founding commitment, not as evidence.
It never counts as a desirability bet (`is_opinion` should not apply / should not nag for a
primary source), and it is the thing an `out_of_scope` decision can *cite* as its reason.

Open question — is an axiom a `Need` with a marker, or its own noun?
- **Marker on Need** (`kind: axiom`, or `axiom: true`): cheapest; rides the existing loader/writer/
  splice. But an axiom is not really "what a named person wants" (the Need definition) — it is a
  product stance, so the fit is loose.
- **A new noun** (`axioms:` top-level list, like `roles:`/`goals:`): cleaner semantically, matches
  how #52 added `Role`. Heavier: a new loader path, writer, and references.

Lean: start with the marker if the only job is "cite it from an out_of_scope decision and exempt it
from the opinion nag"; promote to a noun if axioms need their own coverage/roster view.

### B. The contradiction edge

Two needs that oppose each other have no edge today — the only need→need edges are `children`
(flow tree), `variant_of` (recurrence), and `need:` (the dependency DAG). Add a `contradicts`
need→need relation (symmetric), so the board can *show* that N-1 and N-2 are in tension and that an
axiom (A) resolves it: A ⇒ N-1 in scope, N-2 `out_of_scope`. This is the structural home for
"clients want opposite things; the vision decides."

Cycle/consistency note: unlike `need:` (acyclic, memoized by the Resolver), `contradicts` is a
plain symmetric annotation, not a proof — it does not resolve to a state, it just records tension.
A lint check could flag two needs that `contradict` yet are *both* live on the board (an
unresolved contradiction the vision has not yet decided).

## The rippling mechanism (property 2, made concrete)

Tie the `out_of_scope` withdrawal (just shipped) to the axiom that caused it: let an
`out_of_scope` withdrawal name the axiom id it rests on (`withdrawn: {kind: out_of_scope, axiom: A-3}`).
Then changing or retiring A-3 surfaces every need withdrawn under it as "decided against a now-changed
axiom — re-review" (a lint warning, the same shape as the staleness/revisit nudges). This is the
smallest honest version of "axioms ripple" — records-only, no recomputation prodc isn't entitled to
make, the agent/PM re-decides.

## Discovery lifecycle (property 3)

An `assumption`-sourced need the PM commits to becomes an axiom: a promote step
(`prodc promote-axiom <id>` or `set <id> kind=axiom`), sibling to draft-promotion. The provenance
stays — the source list still shows the client signals that *led* to the axiom — but the stance
changes from "bet to validate" to "frame we build on". This keeps the honest history: the axiom was
discovered, not decreed.

## Build order (proposed — settle A's shape first)

1. Decide marker-vs-noun for the axiom (A). Smallest slice: a stance that exempts a need from the
   opinion nag and can be cited.
2. `out_of_scope` withdrawal cites its axiom; lint re-review when the axiom changes (the ripple).
3. The `contradicts` edge + the "both-live contradiction" lint.
4. The discovery/promote lifecycle (assumption → axiom), once the shape is fixed.

Keep the silent goal: the agent is the PM discovering the product; prodc records the structure of
that discovery (the axioms, the contradictions, the scope decisions) — it never decides them.

---
scope: L · verify: test · area: model · relates: out-of-scope (#74 follow-up), #52 (role noun), research-board profile (logic-system framing), #56 (variant_of as a need→need edge precedent)
