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

> Status: v0.3, on PyPI (`pip install prodc`). The model grows from three nouns
> (Need · Source · Proof) to Goal, Release and a GSN argument graph; with the proof/source
> adapters and the `status` / `show` / `brief` / `plan` / `argument` / `diff` / `portfolio`
> commands in. See `docs/issues/` for what's still open.

## Commands

`prodc -C DIR <command>` runs as if started in `DIR` (like `terraform -chdir`), so you can
point any command at another project without passing `--config` paths.


- `prodc status` — the board: needs vs what the suite proves, with gaps, coverage, and
  per-goal / per-release / cross-client roll-ups. `--wide` never truncates the need text;
  non-product needs (`product: false`) are listed out-of-scope, not counted in coverage.
- `prodc show <id>` — one need as a citable answer (grounds, warrant, sources, proofs).
- `prodc brief <client>` — a pre-meeting agenda for one client: its applicable needs that
  are opinions (no evidence) or HOLEs (no proof), must-haves first.
- `prodc plan` — a ranked backlog from recorded inputs only (must + state + evidence kind,
  refined by an optional `importance` ordinal); ordering, not a fabricated score.
- `prodc argument` — the GSN assurance graph and its defects (unsupported claim, dangling
  assumption); `--strict` exits 1 on any defect.
- `prodc diff <snapshot>` — what changed since a saved `status --json`.
- `prodc portfolio <toml>…` — many repos rolled into one scoreboard.

Write-back (the agent records decisions, not just reads them) — each validates the whole
model via the loader before keeping the change, shows the diff, and supports `--dry-run`:

- `prodc set <id> key=value` (or `key+=value` for proofs/children) — edit one field.
- `prodc capture <id> --kind … [--who --date --quote --locator]` — append a source (evidence).
- `prodc accept <id> --who … --date … [--revoke]` — record a human acceptance pass.
- `prodc add need <id> --text … --who … --file …` — create a need with agent provenance.

## Model

Everything loads into one `Model` from the prodc files (`[prodc].needs` glob; any file may
carry a `needs:`, `goals:`, `releases:` or `argument:` list). The nouns:

- **Need** — what a named person wants. A shared **baseline** or a per-client **variant**
  (`variant_of` + `client`); the board counts cross-client **recurrence**. Carries an
  optional **claim** and a human **attestation** (who/date), so a DELIVERED proof whose
  warrant no one reviewed is flagged rather than trusted blindly.
- **Source** — provenance (interview > artifact > proxy > internal); no source = opinion.
- **Proof** — a locator resolved by an adapter to DELIVERED / PENDING / BROKEN / UNRESOLVED.
- **Goal** — a measurable objective needs trace up to; a need with none is flagged.
- **Release** — an ordered, releasable slice (`releases:` order = ship order).
- **Argument** — a GSN graph (claim / strategy / evidence / context / assumption /
  justification) that cites the nouns above by id, for a checkable assurance case.

Cross-references (`variant_of`, `children`, `goal`, `release`, argument links) are string
ids validated at load.

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
