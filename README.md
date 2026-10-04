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

## What it's for

prodc does not replace the human conversation with a client — it is scaffolding around it.
Going in, the board already shows what is still unknown for that client: needs with no
evidence (opinions) and needs with no proof (HOLEs), so the meeting is spent closing real
gaps instead of re-deriving them. Coming out, what was learned is captured as evidence on
the need, so the next decision is planned from the repo rather than from memory. The board
answers "where are we" and "what's blocking" between meetings, without a standup.

## Prior art

prodc draws on, and tries to credit, several existing lines of work:

- **Continuous discovery / opportunity framing** — Teresa Torres (opportunity = need; the
  interview > artifact > internal evidence ladder; "solutions in disguise").
- **The argument/assurance model** — Toulmin (claim · grounds · warrant) and the safety-case
  / GSN tradition it informs.
- **Spec-driven development** — product/requirements modelled as plain JSON/YAML in git
  (the ThoughtWorks / Fowler SDD writing).
- **Structured requirements** — EARS (Easy Approach to Requirements Syntax), the NASA
  requirement-writing guidance, and the SysML lineage.
- **Requirements-as-code tooling** — Doorstop and StrictDoc (plain-text, git-tracked, linked
  IDs), which prodc follows in form but points at product artifacts rather than "shall"
  statements.

> Status: v0.3, on PyPI (`pip install prodc`). The model (Need · Source · Proof) with a
> baseline/variant scope per client, the proof and source adapters, and the
> `status` / `show` / `brief` / `plan` / `diff` / `portfolio` commands are in; see
> `docs/issues/` for what's still open.

## Commands

- `prodc status` — the board: needs vs what the suite proves, with gaps and coverage.
- `prodc show <id>` — one need as a citable answer (grounds, warrant, sources, proofs).
- `prodc brief <client>` — a pre-meeting agenda for one client: its applicable needs that
  are opinions (no evidence) or HOLEs (no proof), must-haves first.
- `prodc plan` — a ranked backlog from recorded inputs only (must + state + evidence kind,
  refined by an optional `importance` ordinal); ordering, not a fabricated score.
- `prodc diff <snapshot>` — what changed since a saved `status --json`.
- `prodc portfolio <toml>…` — many repos rolled into one scoreboard.

A need can be a shared **baseline** or a per-client **variant** (`variant_of` + `client`);
the board counts cross-client **recurrence**, and a DELIVERED proof link carries a human
**attestation** (who/date) so an unreviewed warrant is visible rather than trusted blindly.

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
