---
title: "Source: a `role` field — which role confirmed the evidence (follow-up to the source-kind redesign)"
status: open
scope: "S"
verify: test
area: model
---

## Context

The source kinds were reworked to `primary > secondary > assumption` (the academic primary/
secondary split, plus the floor), with `opinion` as the derived "no external evidence" state. A
Source already carries `who` and `date`, so the lifecycle "assumed on date X → confirmed by Jordan
on date Y" is visible as the source list getting stronger over time.

One piece was deferred from that discussion: **who, by role, confirmed it.** "The owner confirmed
this" carries more weight than "a junior packer mentioned it," and now that Role is a first-class
noun (#52), a Source could name the role of the person it came from.

## Proposal

- Add an optional `role` field on `Source`, validated against declared `roles:` (like `Need.role`).
- Surface it where sources show (`show`, `status --json`), e.g. `primary:Jordan (owner)`.
- Keep it orthogonal to `kind`: the kind is the evidence tier; `role` is who vouched for it. It
  does not change ranking — it is provenance detail, not a new strength axis.

## Why

The evidence tier says how direct the signal is; the role says whose signal it is. Together they
let the board answer "is this confirmed, and by someone who would know?" without inventing a second
strength ladder. Small, additive, and backwards-compatible (the field is optional).

## Done (0.3.x)

✅ `Source.role` (optional), parsed by the loader and validated against declared `roles:` at load
(`_check_source_roles`, unconditional like `need.role`). Written by `prodc capture --role <id>`
(the reload gate rejects a dangling role). Surfaced: the warrant headline shows it on a primary
source (`primary:Jordan (owner)`), `show` lists it per source (`role=owner`), and it rides the
`sources[]` payload in `show --json` and the HTML viewer. Orthogonal to `kind` — provenance, not a
strength axis, so ranking is unchanged. Issue complete.

---
scope: S · verify: test · area: model · relates: source-kind redesign (primary/secondary/assumption), #52
