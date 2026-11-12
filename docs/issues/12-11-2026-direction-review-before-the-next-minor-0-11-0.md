---
title: Direction review before the next minor (0.11.0)
status: open
area: cross-repo
owner: null
filed: 2026-11-12
scope: M
verify: inspect
---

## Context

Jorge (12-11-2026): "for the next minor I want to review the whole project again and figure out if we are going in the right direction."

Since 0.5 prodc grew an MCP server, the issue register (moved from cabildo), catalog packs (ux, visual), release-aware plan and `issue next`. Goals G-1 and G-2 and releases R-1, R-2 were declared on 12-11-2026.

## What to review

- Each noun and command against G-1 and G-2: keep, merge, or cut.
- What consumer boards (crm, timbre, tyko, paas, lingua, accounting) actually use, and what no one uses.
- Whether R-1 and R-2 are the right next releases.
- Open issues and draft needs: still wanted?

## Done when

A written verdict (keep / change / cut, with reasons) is agreed with Jorge, and the board (goals, releases, needs, issues) is updated to match before 0.11.0 ships.
## Internal usage (12-11-2026, Fable review)

Counted on 22 boards with a `prodc.toml` (6 commercial repos, 8 oss libs, 8 ml research boards).

Used:

- Need, Source, Proof: 22 boards, 706 needs, 530 with proofs.
- Goal (11 boards), Release (10), Principle (7, with 32 guard proofs), Decision (7), Role (3).
- `draft` (5 boards), `variant_of`/`client` (accounting, crm), `path` + `views` (2 boards).
- Research fields `claim`, `answer`, `need:` proofs, `evalgate`, `citation`: the 8 ml boards.
- Proof kinds: pytest (441 on 14 boards), gherkin (187), vitest (23), external (10), storybook (6).
- Commands in consumer CI: only `prodc lint`. Consumer docs mention 13 commands. `suggest` and
  `diff` are used.

Not used anywhere: `outcome`, `accept`, `brief`, `recurrence --suggest`, `dupes`, `guide`,
`sync`/`[callbacks]`, the gitlab source adapter, `tags`, `importance`, `contradicts`,
`glossary`/`terms`, `expects`, `stage`, flows (`children`: 1, `seam`: 0), proof kinds `coverage`,
`field` and `prototype`, report csv/jira/confluence, the MCP server, `prodc issues`.

Findings:

- Every consumer pins `prodc==0.7.x`. Nothing after 0.7 runs outside prodc.
- prodc's own board is 1 of 16 DELIVERED.
- Lint noise: crm 719 warnings, paas 169. Mostly "issue serves no need" and "belongs to no flow".
- Only 6 of 15 pytest adapters set `results`, so most DELIVERED means "the test exists".
- Red on current prodc: the 8 ml boards (unknown key `profile`), lingua (2 errors), cabildo
  (1 BROKEN proof).

Proposed 0.11.0: a consolidation release with no new noun or command. Doc drift fixes, a warning
diet, `lint --baseline`, an official CI job, proofs on prodc's own board, deprecate the unused
surface (removed in 0.12), then move every consumer to 0.11.0.

Open questions for Jorge: research boards first-class; prodc as the issue tracker for all
projects; PD-17 and catalog packs in prodc or not; withdraw PD-9, PD-10, PD-11 and cut the gitlab
adapter; freeze MCP; outside PyPI users; flows; a release with no new feature.
