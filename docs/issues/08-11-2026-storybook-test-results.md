---
title: "storybook proofs: read story test results, so a story can be really DELIVERED"
status: open
area: adapters
owner: null
filed: 2026-11-08
needs:
  - PD-15
scope: M
verify: test
---

## Problem

A `storybook` proof is declared only: a story in `index.json` shows the component renders in the
catalogue, not that it works. `[proofs.<name>].results` is reserved but not read.

## Why it waits

- No consumer runs stories as tests yet. tyko and crm (Storybook 10) have neither
  `@storybook/addon-vitest` nor `@storybook/test-runner`.
- The junit shape is not documented. With the Vitest addon, a test name is the story's export
  name and the file is the stories file. The story id is not in the report.
- Writing a matcher from memory against an undocumented format would make proofs look green when
  they are not (the same class of bug as #122 and #123).

## Plan

1. A consumer (crm first) adds `@storybook/addon-vitest` and writes a junit report.
2. Capture that report as a test fixture.
3. Match a case when its file ends with the story's `importPath` (without `./`) and its name is
   the story's `exportName` or `name`.
4. States: passed is DELIVERED; failed is PENDING (not declared, so a guard reads VIOLATED);
   skipped stays declared; a story absent from the report is PENDING ("not in report").
5. Document `parameters.a11y.test = 'error'`: an a11y violation then fails the story test, so a
   design principle guarded by stories reads VIOLATED with no a11y-specific reader.

## Done when

On crm, a story whose test fails turns its need PENDING in `prodc status`, from a real report.
