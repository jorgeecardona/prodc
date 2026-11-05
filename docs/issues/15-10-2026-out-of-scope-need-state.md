---
title: "Out-of-scope: a real need, accepted but declined as not-my-product"
status: done
fixed_in: c0f34a5
scope: "M"
verify: test
area: model
---

## Context

Raised while building #52's `Source.role`. A client can have a need that is *real and evidenced*
(a `primary` source, understood and accepted) that the founder nonetheless will not build, because
it is not the product they want to build. This is different from the two decisions prodc already
models:

- **HOLE** — wanted, evidenced, not yet built. Still on the board, counts as a gap.
- **withdrawn (#74)** — a decision *against* a need: off the board, out of coverage, with a
  `reason`+`date` record. Its docstring frames it as "won't-do".
- **nonproduct (`product: false`, #48)** — infra / NFR / internal, excluded from product coverage.
  Not this: an out-of-scope client need is a genuine *product* want, just not *this* product's.

Today the out-of-scope case is recorded as `withdraw --reason "out of product scope"`. That works
— the evidence stays attached, the need goes off-board — but "out of scope" and plain "won't-do"
collapse into one state, distinguished only by free-text `reason`. So the board cannot answer
"how many real, validated needs did we decline because they were off-strategy?" separately from
"how many did we kill as not-real / not-worth-it".

## The question to settle first

Is the distinction worth a first-class state, or is `withdrawn` + a structured `reason` enough?
Two honest options:

1. **A `reason` taxonomy on `Withdrawal`** — add an optional `kind` to the existing withdrawal
   (`out_of_scope` | `wont_do` | `duplicate` | …), validated like `SourceKind`. Smallest change;
   no new board state, just a facet on the existing off-board decision. `status`/`report` could
   then count declined-but-valid separately. Probably the right first slice.
2. **A distinct `out_of_scope` need state** — heavier: it touches `board_needs`, the coverage math,
   every renderer and the JSON. Only justified if out-of-scope needs should behave differently from
   withdrawn ones on the board (e.g. surfaced in a "declined backlog" view, or handed to a
   portfolio/other-product board rather than dropped).

Lean toward option 1 unless a concrete behaviour (not just a count) needs option 2. A validated
`Withdrawal.kind` keeps the evidence + decision record intact and adds the one axis the founder
actually asked for: *why* it is off the board, as data rather than prose.

## Done (0.3.x) — option 1

✅ `WithdrawalKind` StrEnum (`wont_do` default / `out_of_scope` / `duplicate`) + `Withdrawal.kind`,
parsed and validated by the loader (same `Enum(name) except ValueError` pattern as `SourceKind`).
`prodc withdraw --kind <k>` writes it (only when non-default, to keep files clean). Surfaced:
`status` breaks the withdrawn count down by kind ("withdrawn: N (decided against) — 1 out_of_scope"),
`show` tags a non-default kind (`withdrawn [out_of_scope]: …`), and both board payloads carry
`withdrawn.kind`. Behaviour is unchanged — all kinds are equally off the board and out of coverage;
the kind is provenance for the decision, not a new board state.

Option 2 (a distinct board state) remains unbuilt and is only justified if out-of-scope needs
should *behave* differently (e.g. a "declined but valid" view, or handoff to another board).

## Related

#74 (withdrawn), #48 (product/nonproduct), #52 (role — the vision need is often `kind: assumption`
authored by the founder's own role).

---
scope: M · verify: test · area: model · relates: #74, #48, #52
