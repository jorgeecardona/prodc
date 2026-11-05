---
title: "The decision noun — how a need gets built (the OST chosen-solution)"
status: open
scope: "M"
verify: test
area: model
---

## Context

Raised the same evening as product principles. The PM hit a corner: wanting prodc to also hold the
*how to build* axis, not only the what/why — and naming the risk themselves ("my engineering brain
thinking engineering is product"). First instinct was a classic ADR (context → decision →
consequences). A Fable design review reframed it, and the PM agreed.

## Decision (15-10-2026): the OST node, not an ADR

An ADR is an engineer's artifact; a PM does not write ADRs. The product-management shape of "how"
is the **Opportunity-Solution-Tree** node (Torres): a need is the opportunity, and a decision is
*the solution chosen for it, over the alternatives considered*. prodc already pushes solutions out
of `Need` (the solution-verb lint), so this is their only honest home.

Shape (`decisions:` top-level list, like `principles:`):
- `id`, `text` (the chosen solution).
- `needs: []` — **required, ≥1, validated at load** (hard error). A decision with no need it serves
  is engineering with no product reason — refused, not nagged. Unfakeable, unlike a soft lint.
- `alternatives: []` — the options rejected. Without them a decision is a memo, not a choice.
- `consequences` (optional) — what it costs / rules out.
- `principles: []` — the principle(s) it rests on (validated). Revising one after `decided_at`
  flags the decision stale — the same ripple a withdrawal gets.
- `decided_at` — the ripple comparand (consistent with `revised_at`/`observed_at`).
- Lifecycle reuses the Need verbs, no status enum: `draft` = proposed, `withdrawn` = superseded
  (keeps the record). Chosen over a `DecisionStatus` enum per Fable (a 2-value enum with no
  terminal state can only be deleted, violating "keep the record").

Never enters coverage, the plan, or the opinion check (like `Principle`).

## Shipped

- `model.Decision`, `Model.decisions`.
- loader: `_decision` (needs required non-empty), `_check_decisions` (needs + principles + a
  superseded decision's `withdrawn.principle` all validated against known ids), unique ids.
- status: `active_decisions`, `decisions_for(need_id)`, `stale_decisions` (cites a principle
  revised after `decided_at`), `orphaned_decisions` (serves only withdrawn/non-product needs).
- writer: `add_decision` (whole-file re-dump, reload-gated, empty optionals omitted).
- cli: `prodc add decision <id> --text … --needs … [--alternative … --consequences … --principles
  … --date … --draft]`; `show <need>` lists the decisions serving it; `status` text + `--json`
  carry a `decisions:` section; `lint` warns orphaned + stale decisions (both soft).
- `tests/test_decisions.py`; agent playbook row.

## Deferred / follow-ups (from the same Fable review)

- `prodc withdraw <decision-id>` to supersede a decision from the CLI — today `withdraw` targets a
  need; a decision's `withdrawn` is set via YAML or a future verb. (Lifecycle logic already honors
  it: `active_decisions`/`decisions_for` exclude withdrawn + draft.)
- **Cut the GSN `argument` graph** (soft-deprecate): no writer, one test, its job absorbed by
  `Need.claim` + proofs + attestation; `ArgKind.context/justification/assumption` overlap Principle.
- `Attestation.verdict` is free text and `verdict: fail` currently silences the warrant warning —
  make it a `Verdict` enum (pass|concerns|fail) and warn on anything but `pass` (a false green).
- `WithdrawalKind.DUPLICATE` carries no target — add `Withdrawal.of: str | None` (validated need id,
  required when kind is `duplicate`).

---
scope: M · verify: test · area: model · relates: product-principles (same thread), #52 (role noun as the add-noun precedent), the GSN argument graph (#28, proposed cut)
