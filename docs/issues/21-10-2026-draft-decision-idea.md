---
title: "An idea with no need yet: a draft decision with empty `needs[]`"
status: open
area: model
owner: null
filed: 2026-10-21
needs:
  - PD-16
scope: S
verify: test
---

## Context

Raised by the PM: "an idea that would be cool to explore in the product, but we don't know if it
will be useful, or we don't explore it today, and it is not easy to see how it impacts the product."
The PM named it as an engineering-brain habit: the solution comes first, the need is unknown.

In Torres terms this is a *brainstormed* solution that does not yet hang from an opportunity
(`docs/grounding-torres.md`). prodc has no honest place for it today:

- A **draft need** (#60) is off the board, but a need must state a problem. The idea has none yet.
- A **decision** is the right shape (a solution), but `needs: []` is required and is a hard load
  error (#decision-noun). That rule is on purpose: engineering with no product reason is refused.

## Proposal

Reuse the decision noun, no new noun. "Idea" is the user word; the data is a decision.

- **Load rule.** A decision with `draft: true` may have an empty `needs: []`. The loader still
  refuses an empty `needs` on a non-draft decision. The refusal stays where it matters (a
  committed solution with no product reason).
- **Create.** `add decision --draft` may omit `--needs` (only with `--draft`); `add_decision`
  then writes `needs: []`. Today `add decision` hard-refuses a missing `--needs`.
- **Age.** Add `draft_added` (ISO date) to `Decision`, the same field `Need` has (stamped by
  `add --draft`). `add decision --draft` stamps it, and the draft-age lint (needs only today)
  gets a decision counterpart.
- **Promote.** Generalise `set_decision_awaits` into a decision setter: `needs+=REF`,
  `needs-=REF`, `draft=false`. `cmd_set` must route these keys to it (today only `awaits` is
  routed; every other key on a decision id fails with "no need 'D-n'"). `draft=false` while
  `needs` is still empty is refused by the reload gate.
- **Status.** `render_decisions` lists every non-withdrawn decision, drafts included. Move
  `draft and not needs` decisions into their own "ideas (no need yet)" block. `--json decisions`
  gets a separate `ideas:` key. The report (`active_decisions`, drafts excluded) stays as is:
  ideas are not reported.
- **Triage.** `review` stays needs-only for now; ideas are triaged through `status`.

## Ripple

Text that asserts `needs` is always non-empty must change: `model.py` Decision docstring, loader
error text and the `_check_decisions` "already guaranteed non-empty" comment, `add_decision`
docstring, `src/prodc/agent.md` ("`--needs` is required"), and
`docs/issues/15-10-2026-decision-noun.md`. `orphaned_decisions` already skips drafts (via
`active_decisions`), so a need-less draft is not flagged orphan.

## Rejected

- A separate `idea` noun: cleaner to read, but one more noun to ripple through loader, status,
  lint, writer, docs, and the playbook, for a thing that is a decision in a draft state.
- A draft need with an `assumption` source: it forces a fake problem statement. (The
  solution-verb lint would not catch it if `claim` is set, so the rejection rests on the fake
  problem, not on the lint.)

## Open

- Should `prodc agent` (playbook) tell the agent to capture "would be cool" ideas this way?
- Age threshold for a stale idea: reuse the need draft-age setting, or its own?

## Proof

- loader: draft decision with `needs: []` loads; non-draft with `needs: []` is still an error.
- add: `add decision --draft` without `--needs` writes, reloads, and stamps `draft_added`;
  without `--draft` it is still refused.
- set: `set D-n needs+=N-x` then `set D-n draft=false` promotes; `draft=false` with empty
  `needs` is refused; `needs-=` removes.
- lint: an old need-less draft decision fires the draft-age lint; no orphan warning for it.
- status: need-less drafts render in the ideas block, not in `decisions:`; `--json` has
  `ideas:`; `show D-n` renders with empty `serves`.
