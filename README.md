# prodc

Product management as code: personas, flows, and features traced to evidence, so a
product's state is read from the repo instead of chased in meetings.

prodc treats product thinking the way requirements-as-code tools (Doorstop, StrictDoc)
treat requirements — plain text, in git, with IDs that link to each other — but for the
artifacts a product person actually works with: **Persona → Flow → Feature → Assumption**,
each tied to **evidence**. Two rules give it teeth:

- **No evidence link = flagged as opinion.** Every "why" must trace to a user signal
  (feedback, ticket, interview), or it is marked unsupported.
- **Status comes from the repo, not from a standup.** "Flow UF-004: 3 of 5 scenarios
  passing", "Feature F-012: blocked, assumption A-003 has no data" — the report answers
  "where are we" and "what's blocking" without a meeting.

The lineage is Toulmin's argument model (claim + grounds + warrant): a feature is a claim,
its evidence is the grounds, its assumptions are the warrant. The same shape safety
engineering uses for a "safety case", pointed at product decisions.

> Status: v0, early. The data model and the first cross-repo adapter are still being shaped
> (see `docs/issues/`). Not yet on PyPI.

## Install

```bash
uv sync          # dependencies
make install-hooks
make check       # lint + typecheck + test
```

## Why not just Doorstop / StrictDoc?

Those track "the system shall…" requirements for auditors in regulated industries. prodc
tracks personas, flows and features for product decisions, and derives live status from the
project's own tests. It reads a repo it is pointed at — including existing Gherkin/BDD and
whatever ID scheme already lives there — rather than asking you to re-author everything in a
new grammar.

## Layout

- `src/prodc/` — the package (typed; `py.typed`).
- `docs/issues/` — follow-ups, as a plain-markdown issue register.
- `Makefile` — `format` / `lint` / `typecheck` / `test` / `check` / `build` / `docs`.
- `AGENTS.md` — build/test/style/gotchas for coding agents.
