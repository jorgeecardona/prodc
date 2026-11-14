# prodc

[![pipeline status](https://gitlab.com/cardona-oss/prodc/badges/main/pipeline.svg)](https://gitlab.com/cardona-oss/prodc/-/pipelines)
[![PyPI version](https://img.shields.io/pypi/v/prodc.svg)](https://pypi.org/project/prodc/)
[![Python versions](https://img.shields.io/pypi/pyversions/prodc.svg)](https://pypi.org/project/prodc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://gitlab.com/cardona-oss/prodc/-/blob/main/LICENSE)

Product management as code. You write user needs in YAML, in the repo. Each need lists its
evidence (who asked for it) and its proof (a test). `prodc status` reads the YAML and your test
suite and computes the state of each need. Nobody sets a status by hand.

```text
$ prodc status
gaps: 2 HOLE  ·  1 opinion    coverage 1/3 (33%)

      N-2  HOLE                   export the day's delivery run sheet                 secondary
      N-3  HOLE                   implement a settings page                           opinion
  !!  N-1  DELIVERED* (weak) 1/1  see which orders are past due at a glance           primary:Jordan
```

(output trimmed: header, legend and warnings removed)

Two rules:

1. A need with no evidence is an opinion. Record who asked: an interview quote, a ticket, an
   email.
2. A need is done when its proof points to a test. The states are DELIVERED, PENDING, HOLE and
   BROKEN. `prodc lint` exits 1 on a BROKEN proof, so CI can block the merge.

prodc also keeps the issue register: engineering work and bugs as markdown files in `docs/issues/`
(`prodc issue file`, `prodc issue next`).

## Install

```bash
pip install prodc          # or: uv add prodc
```

Python 3.12+. The only runtime dependency is PyYAML.

## Quickstart

You need three files: the config, the needs, and a test.

`prodc.toml`

```toml
[prodc]
files = ["needs/*.yaml"]

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

Run `prodc status` (output trimmed: header and legend removed):

```text
$ prodc status
gaps: 2 HOLE  ·  1 opinion    coverage 1/3 (33%)

jordan    1 DELIVERED   2 HOLE
    provenance: 1 primary  ·  1 secondary  ·  0 assumption  ·  1 opinion

      N-2  HOLE                   export the day's delivery run sheet                 secondary
       ⚠ EARS: no observable outcome. Try 'When <trigger>, <who> can <outcome>'
      N-3  HOLE                   implement a settings page                           opinion
       ⚠ text may be a solution in disguise (starts with 'implement')
  !!  N-1  DELIVERED* (weak) 1/1  see which orders are past due at a glance           primary:Jordan
       ⚠ EARS: no observable outcome. Try 'When <trigger>, <who> can <outcome>'
       ⚠ DELIVERED on an unattested proof link (warrant not reviewed) (#13)
       ⚠ must-have DELIVERED on declared proofs only: add a results-backed proof (#103)
```

N-1 is DELIVERED because a tagged scenario proves it. The `*` means the state comes from the tag,
because no test results were loaded. `(weak)` means a must-have rests only on such declared
proofs. N-2 has evidence but no proof, so it is a HOLE. N-3 has
neither, so it is an opinion.

You fix these from the command line. Each write command changes one YAML file, validates the
whole model again, and prints the diff.

```bash
# trace the opinion to evidence
prodc capture N-3 --kind primary --who Jordan --date 2026-10-01 \
    --quote "I keep changing the printer in three places"

# add the scenario to your suite, tagged @pending until it is green:
#     @pending
#     Scenario: Export the run sheet
# then point the need at it:
prodc set N-2 proofs+="web:orders.feature#Export the run sheet"

prodc status      # gaps: 1 PENDING · 1 HOLE   (N-2 is PENDING: the scenario exists)
                  # (skip writing the scenario and the proof points at nothing: BROKEN, lint exits 1)
prodc lint        # CI gate: exit 1 on a BROKEN proof or a must-have with no evidence
```

If you rename a scenario and do not update the need, the proof becomes BROKEN and `prodc lint`
exits 1.

## Compared to other tools

- Jira, Linear and other trackers store work items with a status that someone sets by hand.
  prodc stores needs and computes their status from tests. It has no assignees, sprints, or
  notifications. You can use both: a source can point to a GitLab ticket (`kind = "gitlab"`,
  read-only), a proof can be any script (`kind = "command"`), and `prodc sync` runs a hook when a
  need changes state.
- A PRD in Notion or a wiki is not checked after it is written. prodc files are validated on
  every load, linted in CI, and reviewed in merge requests.
- You could keep the same YAML by hand. prodc adds the schema, proof checks against real test
  suites, the source kinds, the lint, and write commands that keep the files consistent.

prodc does not run your tests, call an LLM, or contact a tracker by itself. It does not model the
full discovery process (opportunity-solution trees, testing several solutions in parallel). It
records needs, their evidence, and the decisions made about them.

If your team already has an external tracker, keep it: prodc does not replace it, and a source
can point at its tickets. prodc does not call a model or run a UI.

## Python

The Python modules are not a public API. Use the CLI, `--json` and the YAML files.

## Features

- Source kinds: `primary` (the user's own words), `secondary` (a report, a ticket, an internal
  doc), or `assumption` (a guess). A need with no primary or secondary source is an opinion.
  `lint` fails on a must-have opinion; `status --strict` fails on any opinion.
- Proof adapters: Gherkin scenarios and tags, pytest node ids, file existence, human sign-off,
  prototypes, citations, eval metric gates, external result files, and a generic `command`. Give
  it cucumber-json or JUnit XML to use real test results instead of tags.
- Five states: DELIVERED, PENDING, HOLE, BROKEN, UNRESOLVED. A HOLE does not fail the gate; BROKEN
  always does. A proof in a sibling repo that is not checked out is UNRESOLVED, not BROKEN.
- Flows: a need with `children` rolls up its children, with `seam` proofs for the steps between
  them. One BROKEN child breaks the flow. The flow is DELIVERED only when every child and seam is.
- `tests/test_models.py` builds a [musil](https://pypi.org/project/musil/) model of the
  lifecycle and checks every reachable state against the real resolver.
- Write commands: `set`, `capture`, `accept`, `attest`, `withdraw`, `add`. They change only the
  edited need's block and keep the comments in the rest of the file. All take `--dry-run` and
  `--expect-sha`.
- Read commands: `status`, `show`, `brief`, `plan`, `report --format html` (one self-contained
  HTML file), `portfolio`, and `diff` against a snapshot. They take `--json`. Exit codes: 0 ok, 1
  gate failed, 2 config or load error.
- `prodc agent >> AGENTS.md` adds instructions for a coding agent to act as the project's product
  manager. An agent may record `assumption` or `secondary` sources; `primary` is only for a real
  user's own words.
- `prodc mcp install` registers prodc as an MCP server, so an agent in Claude Code, Cursor, or VS
  Code uses it through tools. Install with `pip install 'prodc[mcp]'`. See
  [MCP server](https://cardona-oss.gitlab.io/prodc/mcp/).

prodc also has goals, releases, roles, principles, and decisions
([model docs](https://cardona-oss.gitlab.io/prodc/model/)), and the commands `dupes`,
`recurrence`, and `suggest`. See the [docs](https://cardona-oss.gitlab.io/prodc/) for all of it.

## Links

- **Repository:** https://gitlab.com/cardona-oss/prodc
- **PyPI:** https://pypi.org/project/prodc/
- **Changelog:** [CHANGELOG.md](https://gitlab.com/cardona-oss/prodc/-/blob/main/CHANGELOG.md)
- **Documentation:** <https://cardona-oss.gitlab.io/prodc/> ([Quickstart](https://cardona-oss.gitlab.io/prodc/quickstart/), [Commands](https://cardona-oss.gitlab.io/prodc/commands/), [Model](https://cardona-oss.gitlab.io/prodc/model/), [Config](https://cardona-oss.gitlab.io/prodc/config/), [CI job](https://cardona-oss.gitlab.io/prodc/ci/), [Lifecycle](https://cardona-oss.gitlab.io/prodc/lifecycle/))

## Contributing

Toolchain, CI, and the release process live in [CONTRIBUTING.md](https://gitlab.com/cardona-oss/prodc/-/blob/main/CONTRIBUTING.md); build and test
instructions for coding agents are in [AGENTS.md](https://gitlab.com/cardona-oss/prodc/-/blob/main/AGENTS.md). In short: `make setup`
then `make check` (lint + typecheck + test); `moon run :ci` is what CI runs.

## License

MIT © Jorge Cardona. See [LICENSE](https://gitlab.com/cardona-oss/prodc/-/blob/main/LICENSE).
