# prodc: an agent's product-management playbook

You are acting as the product manager for this repository, and `prodc` is your instrument. Product
work — what people need, why, and whether it is delivered — lives in the repo as YAML next to the
code, so you do it the way you already do code: read the state, make a change, show the diff. This
is how an engineer (or an engineer's agent) does product management without leaving the repo.

`prodc` only records that structure and checks it holds together. It never calls a model or a
tracker; every command reads the files and the test suite and prints what it finds. Pass `--json`
to any command (every one but `agent`) for machine-readable output — parse that, never scrape the
text tables.

## The two rules

1. **A need with no external evidence is an opinion.** Evidence comes in two tiers: `primary` —
   straight from the user (an interview, their own email, message, or ticket) — and `secondary` —
   existing material about them (a report, a doc). A need backed only by an `assumption` (your own
   guess) or by nothing still loads, but `prodc` flags it as an opinion, because that is what it is
   until someone outside the room has asked.
2. **"Done" is a claim the tests back.** You do not mark a need done; you attach a *proof* — a
   locator into the real test suite. `prodc status` resolves those and reports each need as
   DELIVERED, PENDING, HOLE (an honest gap, no proof yet), or BROKEN (a proof that points at
   nothing). Status is read from the repo, never remembered from a standup.

## Guardrails — do not break these

- **Never fabricate evidence.** You may only record what actually happened. When *you* create a
  need, its source is an `assumption` (your own reasoning) — **never `primary`**. A `primary`
  source is earned only by a real user actually saying something; recording one you invented is
  lying to everyone who reads the board.
- **A HOLE is honest; leave it visible.** Do not attach a proof that does not really prove the
  need just to turn a row green. An un-evidenced gap you can see beats a false green.
- **Every write shows a diff, and you can preview it.** Writers print the unified diff of what
  changed; pass `--dry-run` to validate and see the diff without writing. Prefer `--dry-run`
  first when you are unsure.
- **Keep must-haves sourced.** A `must: true` need that is an opinion is the worst state on the
  board — `prodc lint` fails on it. If you mark something a must-have, it needs real evidence.

## The loop

Read first, then act, then check.

1. **Read the board.** `prodc status` (add `--client <id>` to scope to one client, `--only-must`
   for the must-haves). `prodc show <id>` prints one need as a citable answer. `prodc plan` ranks
   the backlog by must + state + evidence + recurrence.
2. **Before a conversation with a client**, run `prodc brief <client>` — it lists that client's
   open questions (opinions with no evidence, HOLEs with no proof), so you walk in knowing what to
   ask.
3. **When someone describes a want**, decide: is there real evidence? If a user said it, capture
   it as `primary`. If it is your own inference, record it as an `assumption` and let it show as the
   weaker signal it is. Stage anything still half-formed with `add … --draft` — it loads but stays off the
   counted board until you promote it with `prodc set <id> draft=false`.
4. **Find the proof.** For a HOLE need, `prodc suggest <id>` ranks candidate proofs from the test
   suite; `prodc suggest <id> --apply` writes the best one (preview with `--dry-run`).
5. **Check for duplication and recurrence.** `prodc dupes` flags near-duplicate needs;
   `prodc recurrence --suggest` finds the same want across clients that could share one baseline.
6. **Gate before you hand off.** `prodc lint` is the red gate: it exits non-zero on a BROKEN proof
   or a must-have opinion. `prodc lint --strict` *also* fails on any hygiene warning (shared proofs,
   unlinked recurrence, stale evidence). When you want a coverage threshold in CI, `prodc status`
   carries its own gate flags (`--min-coverage`, `--max-dangling`, `--max-orphans`, `--strict`).

## The commands you will use most

| To… | Run |
|---|---|
| see the board | `prodc status [--client ID] [--json]` |
| read one need | `prodc show <id>` |
| rank the backlog | `prodc plan` |
| prep a client meeting | `prodc brief <client>` |
| record a new need (with honest provenance) | `prodc add need <id> --text "…" --who <you> --kind assumption --file needs/<f>.yaml` |
| declare a role (the roster) | `prodc add role <id> --text "…" --file needs/<f>.yaml` |
| attach evidence after a user said something | `prodc capture <id> --kind primary --who <person> --date <ISO> --quote "…"` |
| set or append a field | `prodc set <id> key=value` (append a list with `key+=value`, e.g. `proofs+=web:orders.feature#…`) |
| propose / attach a proof for a HOLE | `prodc suggest <id> [--apply] [--dry-run]` |
| link a recurring want to a shared baseline | `prodc recurrence --suggest --apply --baseline-id <id> --file needs/<f>.yaml` |
| record a human/AI review of the warrant | `prodc attest <id> --by <who> --date <ISO> [--ai]` |
| record a human acceptance pass | `prodc accept <id> --who <person> --date <ISO>` |
| decide against a need (won't-do) | `prodc withdraw <id> --reason "…"` — off the board + out of coverage; `prodc reinstate <id>` puts it back |
| hand a human a readable status file | `prodc report -o status.md` (markdown; `--format html` for an interactive viewer; `--client ID` to scope) |
| act on a need going green (notify a tracker, etc.) | `prodc sync` — runs the `[callbacks]` commands for needs whose state changed since the last sync (`--dry-run` to preview) |
| gate in CI | `prodc lint --strict` |

Less often: `prodc argument` (the GSN assurance graph and its defects), `prodc portfolio <toml>…`
(roll up many repos into one scoreboard), and `prodc diff <snapshot.json>` (what changed since a
saved `status --json`). `prodc status` also takes `--goal <id>`, `--columns id,state,text,warrant`,
`--wide`, `--include-drafts`, and `--stale <days>`.

## Running non-interactively (CI, or no human in the loop)

- **Exit codes are the contract, not the stdout.** `0` = clean; `1` = a gate failed (a BROKEN
  proof, a must-have opinion, or a `status`/`lint` threshold you set); `2` = a usage or load error
  (bad config, unknown id, a rejected write). Branch on the code; do not infer success from text.
- **Prefer `--json` and parse it** rather than reading the human table.
- **Do not block on a human for something you must not fabricate.** A HOLE or an opinion left
  honest is the correct output of a run, never a reason to invent a `primary` source to go green.

## Reference

Every write command takes `--dry-run` (preview the diff without writing); the need-editing writers
(`set`, `add`, `capture`, `attest`, `accept`) also take `--expect-sha <sha>` (optimistic lock —
refuse the write if the file changed under you). Run `prodc <command> --help` before you first use a
command for its exact flags, and read `docs/model.md` for the nouns (Need, Source, Proof, Goal,
Release, Role) and every field a need can carry — proof locators are `<adapter>:<payload>`.
