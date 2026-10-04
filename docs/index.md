# prodc

**Product management as code**: personas, flows, and features traced to evidence,
so a product's state is read from the repo instead of chased in meetings.

prodc models three nouns — **Need**, **Source**, **Proof** — and derives live status
from the project's own tests. Two rules give it teeth:

- **No source = opinion.** A need with no evidence link is flagged as an unsupported opinion.
- **Status comes from the repo.** A proof is a locator into a test suite; `prodc status`
  reports what is delivered, pending, broken, or an honest gap — without a standup.

## Install

```bash
uv sync          # dependencies
make check       # lint + typecheck + test
```

## The board

Point `prodc.toml` at your needs and your test suite, then:

```bash
uv run prodc status
```

```text
prodc status — quickstart
gaps: 2 HOLE  ·  1 opinion    coverage 1/3 (33%)
     id        GROUNDS         need                                              WARRANT

jordan (design partner)    1 DELIVERED  ·  2 HOLE
  !! N-1       DELIVERED* 1/1   see which orders are past due at a glance         interview:Jordan
     N-2       HOLE             export the day's delivery run sheet               artifact
     N-3       HOLE             implement a settings page                         opinion
```

Two columns carry the [Toulmin](https://en.wikipedia.org/wiki/Stephen_Toulmin) split:
**GROUNDS** (does a test prove it?) and **WARRANT** (is there a user signal it matters?).
A `HOLE` is an honest gap and never fails the build; a `BROKEN` locator does. `--strict`
also fails on opinions, and `--min-coverage` / `--max-dangling` turn the board into a gate.

## Concepts

- **Need** — what a named person wants. A flow is a need with children; a persona is the `who`.
- **Source** — provenance: an interview, an artifact, or an internal assertion. No source = opinion.
- **Proof** — a `<adapter>:<payload>` locator resolved against existing tests (Gherkin scenarios
  or pytest node ids), so a repo keeps its own test format.
