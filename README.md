# prodc

[![PyPI](https://img.shields.io/pypi/v/prodc)](https://pypi.org/project/prodc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://gitlab.com/cardona-oss/prodc/-/blob/main/LICENSE)

Product management as code: the *needs* your product exists to meet, each traced to the evidence a real user gave for it and the test that proves it is delivered. For teams that keep product work in the repo, next to the code, and want a tool to check it holds together.

prodc reads plain YAML files and your test suite and shows you the gaps. It does not call a model, host a UI, or replace your tracker. Two rules carry it:

1. **A need with no evidence is an opinion.** Write down who asked — an interview quote, a ticket, an email — or prodc flags the need as an opinion, because that is what it is until someone outside the room has asked.
2. **"Done" is a claim your tests back.** You never mark a need delivered. You attach a *proof* (a locator into your test suite), and `prodc status` resolves it: DELIVERED, PENDING, HOLE (an honest gap), or BROKEN (points at nothing). The state is read from the repo, not remembered from a standup.

## Install

```bash
pip install prodc          # or: uv add prodc
```

Python 3.12+. The only runtime dependency is PyYAML.

## Quickstart

Three files. The first tells prodc where to look, the second holds what people need, the third is a test you have probably already written.

`prodc.toml`

```toml
[prodc]
needs = ["needs/*.yaml"]

[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]
```

`needs/jordan.yaml`

```yaml
who: jordan
needs:
  - id: N-1
    text: "see which orders are past due at a glance"
    must: true
    sources:
      - kind: primary
        who: Jordan
        date: 2026-09-20
        quote: "I lose the past-due ones in the list"
    proofs:
      - "web:orders.feature#Past due orders are highlighted"

  - id: N-2
    text: "export the day's delivery run sheet"
    sources:
      - kind: secondary
        locator: issues.md#N-2
        date: 2026-09-21

  - id: N-3
    text: "implement a settings page"
```

`features/orders.feature`

```gherkin
Feature: Orders board

  @implemented
  Scenario: Past due orders are highlighted
    Given an order whose due date has passed
    When I open the orders board
    Then the order is highlighted as past due
```

Run the board (output trimmed; the real one also carries a legend and phrasing hints):

```text
$ prodc status
gaps: 2 HOLE  ·  1 opinion    coverage 1/3 (33%)

jordan    1 DELIVERED   2 HOLE
    provenance: 1 primary  ·  1 secondary  ·  0 assumption  ·  1 opinion

      N-2  HOLE            export the day's delivery run sheet          secondary
      N-3  HOLE            implement a settings page                    opinion
       ⚠ text may be a solution in disguise (starts with 'implement')
  !!  N-1  DELIVERED* 1/1  see which orders are past due at a glance    primary:Jordan
       ⚠ DELIVERED on an unattested proof link — warrant not reviewed
```

N-1 is DELIVERED because a tagged scenario proves it (the `*` means declared by tag, no test results loaded yet). N-2 has evidence but no proof: a HOLE. N-3 has neither: an opinion.

Now close the loop from the command line. Each write command rewrites one YAML file, re-validates the whole model, and prints the diff.

```bash
# trace the opinion to evidence
prodc capture N-3 --kind primary --who Jordan --date 2026-10-01 \
    --quote "I keep changing the printer in three places"

# write the test (tag it @pending until it is green), then point the need at it
prodc set N-2 proofs+="web:orders.feature#Export the run sheet"

prodc status      # gaps: 1 PENDING · 1 HOLE   — no opinions left
prodc lint        # CI gate: exit 1 on a BROKEN proof or a must-have with no evidence
```

Change a scenario title without updating the need and the proof turns BROKEN; `prodc lint` exits 1. That is the whole idea: the board cannot drift from the code.

## Why prodc

**Versus Jira, Linear, and other trackers.** A tracker records work items and a status someone set by hand. prodc records *needs* and computes their status from the tests. It has no assignees, sprints, comments, or notifications, and it is not trying to. Keep the tracker for the work; keep prodc for the question "did a real user ask for this, and does a test prove it?" The two connect at the edges: a need's source can be a ticket locator (checked read-only against GitLab with `[sources.<name>] kind = "gitlab"`), a proof can be resolved by any script you point at a tracker (`kind = "command"`), and `prodc sync` fires a hook when a need changes state.

**Versus a PRD in Notion or a wiki.** A document says what should be true; nothing checks it later. prodc's files are validated on every load (ids, cross-references, source hygiene), linted in CI, and reviewed in merge requests like code. "Is this done?" is answered by `prodc show N-1`, not by finding the right page.

**Versus plain YAML in the repo.** You could keep this structure by hand. prodc adds the schema, the proof resolution against real test suites, the evidence ladder, the lint, and the write-back commands that keep the files consistent.

**What it does not do.** It does not run your tests, call an LLM, or ping a tracker on its own. It does not model the full discovery loop (opportunity-solution-tree restructuring, parallel solution testing); it records needs, the evidence under them, and the decisions taken on them.

## Key features

- **Evidence ladder.** A source is `primary` (the user's own words), `secondary` (a report, a
  ticket, an internal doc), or `assumption` (a guess). With neither primary nor secondary, the need
  is an opinion: `lint` fails a must-have opinion, `status --strict` fails on any.
- **Proofs resolve against the repo.** Adapters for Gherkin scenarios and tags, pytest node ids,
  file existence, human sign-off, prototypes, citations, eval metric gates, external results files,
  and a generic `command` hook. Feed it cucumber-json or junit XML and declared states become real.
- **Five states, honest semantics.** DELIVERED, PENDING, HOLE, BROKEN, UNRESOLVED. A HOLE is never
  a failure; BROKEN always is; a proof in an absent sibling repo is UNRESOLVED, not BROKEN.
- **Flows.** A need with `children` rolls them up, with `seam` proofs for the behaviour between
  steps. Any BROKEN child breaks the flow; a flow is DELIVERED only when every child and seam is
  green.
- **The roll-up is machine-checked.** `tests/test_models.py` builds a
  [musil](https://pypi.org/project/musil/) model of the lifecycle and explores every reachable
  state against the real resolver, so the documented invariants cannot drift from the code.
- **Write-back that respects your files.** `set`, `capture`, `accept`, `attest`, `withdraw`, `add`
  splice one need's block back into the original YAML, keeping other comments. All take `--dry-run`
  and `--expect-sha`.
- **Boards for humans.** `status`, `show`, `brief`, `plan`, `report --format html` (a self-contained
  interactive viewer), `portfolio`, and `diff` against a snapshot. The read commands (`status`,
  `lint`, `show`, `brief`, `plan`, `diff`, `portfolio`, `dupes`, `recurrence`, `suggest`, `review`)
  take `--json`; exit codes are fixed (0 ok, 1 gate failed, 2 config or load error).

prodc also models goals, releases, roles, principles, decisions, attestations, withdrawals and
settled answers, and ships hygiene commands (`dupes`, `recurrence`, `suggest`); the
[docs](https://cardona-oss.gitlab.io/prodc/) have the full surface.

## Use it with a coding agent

prodc ships a playbook that teaches an agent to act as the project's product manager: read the board, capture evidence with honest provenance, find proofs, gate before a handoff. An agent may record `assumption` or `secondary` sources; `primary` is reserved for a real user's own words.

```bash
prodc agent >> AGENTS.md     # or: prodc agent --write AGENTS.md
prodc guide                  # the short human onboarding guide
```

## Links

- Repository: <https://gitlab.com/cardona-oss/prodc>
- PyPI: <https://pypi.org/project/prodc/>
- Docs: <https://cardona-oss.gitlab.io/prodc/> — [Quickstart](https://cardona-oss.gitlab.io/prodc/quickstart/), [Commands](https://cardona-oss.gitlab.io/prodc/commands/), [Model](https://cardona-oss.gitlab.io/prodc/model/), [Config](https://cardona-oss.gitlab.io/prodc/config/), [Lifecycle](https://cardona-oss.gitlab.io/prodc/lifecycle/)
- Changelog: [CHANGELOG.md](https://gitlab.com/cardona-oss/prodc/-/blob/main/CHANGELOG.md)

`AGENTS.md` holds build and test instructions for coding agents working on prodc itself.

## License

MIT. See [LICENSE](https://gitlab.com/cardona-oss/prodc/-/blob/main/LICENSE).
