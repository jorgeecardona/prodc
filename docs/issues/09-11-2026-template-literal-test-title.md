---
title: "Lint does not explain a proof locator that misses a template-literal test title"
status: done
fixed_in: 47313c2
scope: "S"
verify: test
area: adapters
---

## Context

crm's Miller guard named its tests with template literals:

```ts
it(`desktop page cap is at most ${DESKTOP_LIMIT} rows`, ...)
```

The vitest adapter reads test titles from source as static text, so it sees
`${DESKTOP_LIMIT}`, not `50`. The locator `> desktop page cap is at most 50 rows` matched
nothing, and the principle went BROKEN in CI with no hint why (crm 7115c3a3).

## Decision needed

When a locator matches nothing and the file has a title with `${`, lint says so: "test titles
with `${}` are not resolved; use a plain string". Same for the catalog recipes' docs.

## Test

A vitest file with a template-literal title and a locator for its rendered text: lint reports
BROKEN with the template-literal hint.

## Outcome

Done by matching, not by a hint: a locator segment now also matches a template-literal title with
each `${...}` filled in (`_template_titles` in `adapters.py`), for the vitest and Playwright kinds.
