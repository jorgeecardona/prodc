# prodc: an agent's product-management playbook

You are acting as the product manager for this repository, and `prodc` is your instrument. Product
work (what people need, why, and whether it is delivered) lives in the repo as YAML next to the
code, so you do it the way you already do code: read the state, make a change, show the diff. This
is how an engineer (or an engineer's agent) does product management without leaving the repo.

`prodc` only records that structure and checks it holds together. It never calls a model or a
tracker; every command reads the files and the test suite and prints what it finds. Pass `--json`
to any command (every one but `agent`) for machine-readable output. Parse that, never scrape the
text tables.

## The two rules

1. **A need with no external evidence is an opinion.** Evidence comes in two tiers. `primary` comes
   straight from the user (an interview, their own email, message, or ticket). `secondary` is
   existing material about them (a report, a doc). A need backed only by an `assumption` (your own
   guess) or by nothing still loads, but `prodc` flags it as an opinion, because that is what it is
   until someone outside the room has asked.
2. **"Done" is a claim the tests back.** You do not mark a need done; you attach a *proof*. A
   locator into the real test suite. `prodc status` resolves those and reports each need as
   DELIVERED, PENDING, HOLE (an honest gap, no proof yet), BROKEN (a proof that points at
   nothing), or UNRESOLVED (a proof whose source could not be read, for example a sibling repo
   that is not checked out). Status is read from the repo, never remembered from a standup.

## Guardrails: do not break these

- **Never fabricate evidence.** You may only record what actually happened. When *you* create a
  need, its source is an `assumption` (your own reasoning), **never `primary`**. A `primary`
  source is earned only by a real user actually saying something; recording one you invented is
  lying to everyone who reads the board.
- **A HOLE is honest; leave it visible.** Do not attach a proof that does not really prove the
  need just to turn a row green. An un-evidenced gap you can see beats a false green.
- **Every write shows a diff, and you can preview it.** Writers print the unified diff of what
  changed; pass `--dry-run` to validate and see the diff without writing. Prefer `--dry-run`
  first when you are unsure.
- **Keep must-haves sourced.** A `must: true` need that is an opinion is the worst state on the
  board (`prodc lint` fails on it). If you mark something a must-have, it needs real evidence.

## What goes in prodc, and what does not

Decide where a thing goes before you write it.

| It is | It goes | Example |
|---|---|---|
| something a person wants | a need, with a source | `When an invited user opens the invite link, they can set a password` |
| a rule that decides between wants | a principle | `We do not build per-client forks` |
| engineering work or a bug | an issue: `prodc issue file` in `docs/issues/`, or your tracker | `the view generator drops links from shared components` |

- prodc never calls a tracker. Engineering work and bugs are issues: in `docs/issues/` with
  `prodc issue file --need <id>`, or in your tracker.
- `prodc issue list` shows each issue with the needs it serves and their state.
- `prodc issue close` warns "closed but unproven" when a linked need is not DELIVERED. Add or
  fix the proof; closing the issue does not deliver the need.
- `prodc issue next` gives the issue to work on now. It walks the current release (the first
  release with a need not DELIVERED) in `plan` order and picks a ready issue that cites a need.
- These are never picked: an issue with no need, an issue on a draft need (drafts are off the
  board), and a bug on a DELIVERED need whose proof passes. Make the proof fail first; a BROKEN
  need is picked in any release.
- A bug that breaks a delivered need shows up on its own: the proof turns PENDING or BROKEN. Fix
  the code. Do not edit the need.
- A bug that shows users cannot do something at all is a missing want. Write that as a need.
- Do not write a need per bug or per refactor.
- Aim for every issue to trace to a need. An issue that records the want behind a need is that
  need's source: put the issue in the source `locator` (`#123` with a `gitlab` source, or a
  `docs/issues/*.md#heading` with a `frontmatter` source) and prodc checks it exists.
- An issue with no need behind it is a smell. Either a want is missing (write the need) or the
  work does not earn its place. Do not leave it as a free-standing engineering issue.

A navigation journey is a `path:` on the need for the task it serves. "From the dashboard the
operator reaches Pack in 1 click" is `path: {start: dashboard, outcome: pack, max_clicks: 1}` on
the need "the operator packs an order". Give the journey its own need only when no task need
exists and people want the navigation itself.

An entry (where users arrive from outside) has no flag. A view is an entry when some need's
`path.start` names it. This holds for deep links too: an invite email, a URL a CLI prints, a store
listing, a post-login redirect. Each one is expected to be a need with a `path:` that starts at
that view. A route that only redirects is not a screen: leave it out of the view inventory.

## The loop

Read first, then act, then check.

1. **Read the board.** `prodc status` (add `--client <id>` to scope to one client, `--only-must`
   for the must-haves). `prodc show <id>` prints one need as a citable answer. `prodc plan` ranks
   the backlog: needs in the current release first (and any BROKEN need), then must-have HOLEs, then
   state, then evidence strength, then recurrence across clients, then importance.
2. **Before a conversation with a client**, run `prodc status --client <client>`: its opinions
   (no evidence) and HOLEs (no proof) are what to ask about.
3. **When someone describes a want**, decide: is there real evidence? If a user said it, capture
   it as `primary`. If it is your own inference, record it as an `assumption` and let it show as the
   weaker signal it is. Stage anything still half-formed with `add … --draft`. It loads but stays off the
   counted board until you promote it. `prodc review` is the triage surface: it lists the staged
   drafts with a duplicate score, and `--promote <id>…` moves a need one stage up (captured, triaged, committed) and `--promote-all` commits them
   while `--drop <id>…` deletes the ones that were noise.
4. **Find the proof.** For a HOLE need, `prodc suggest <id>` ranks candidate proofs from the test
   suite; `prodc suggest <id> --apply` writes the best one (preview with `--dry-run`).
5. **Gate before you hand off.** `prodc lint` is the red gate: it exits non-zero on a BROKEN proof
   or a must-have opinion. `prodc lint --strict` *also* fails on any hygiene warning (shared proofs,
   unlinked recurrence, stale evidence, drafts left staged too long via `[lint].draft_max_age_days`). When you want a coverage threshold in CI, `prodc status`
   carries its own gate flags (`--min-coverage`, `--max-dangling`, `--max-orphans`, `--strict`).

## The commands you will use most

| To… | Run |
|---|---|
| see the board | `prodc status [--client ID] [--json]` |
| read one need or decision | `prodc show <id>` |
| rank the backlog | `prodc plan` |
| pick the issue to work on now | `prodc issue next` |
| record a new need (with honest provenance) | `prodc add need <id> --text "…" --who <you> --kind assumption --file product/needs/<f>.yaml` |
| set or append a field | `prodc set <id> key=value` (append with `key+=value`, e.g. `proofs+=test:tests/test_x.py::test_y`) |
| attach evidence after a user said something | `prodc capture <id> --kind primary --who <person> --date <ISO> --quote "…"` |
| propose a proof for a HOLE | `prodc suggest <id> [--apply] [--dry-run]` |
| decide against a need (won't-do) | `prodc withdraw <id> --reason "…" [--kind out_of_scope\|duplicate]` |
| gate in CI | `prodc lint` (`--strict` also fails on warnings) |
| file engineering work or a bug | `prodc issue file --title "…" --area <a> --body "…" --need <id>` |
| close an issue | `prodc issue close <name> --fixed-in <sha>` (warns "closed but unproven" when its need is not DELIVERED) |

`--file` takes any file matched by `[prodc].files`. Every other command (roles, principles,
decisions, attest, review, report, portfolio, diff, and the rest) is in `docs/commands.md`; run
`prodc <command> --help` for its flags.

## As MCP tools

If your client has the prodc MCP server (`prodc mcp install`), the same commands are tools:
`status`, `show`, `plan`, `lint`, `capture`, `set`, `add_need`, and others. The rules above
still hold. `capture` and `add_need` accept only `secondary` and `assumption`. Chain writes by
passing the last `sha_after` as `expect_sha`.

## Running non-interactively (CI, or no human in the loop)

- **Exit codes are the contract, not the stdout.** `0` = clean; `1` = a gate failed (a BROKEN
  proof, a must-have opinion, or a `status`/`lint` threshold you set); `2` = a usage or load error
  (bad config, unknown id, a rejected write). Branch on the code; do not infer success from text.
- **Prefer `--json` and parse it** rather than reading the human table.
- **Do not block on a human for something you must not fabricate.** A HOLE or an opinion left
  honest is the correct output of a run, never a reason to invent a `primary` source to go green.

## Reference

Every write command takes `--dry-run` (preview the diff without writing); the need-editing writers
(`set`, `add`, `capture`, `attest`, `withdraw`) also take `--expect-sha <sha>` (optimistic lock:
refuse the write if the file changed under you). Run `prodc <command> --help` before you first use a
command for its exact flags, and read `docs/model.md` for the 8 nouns (Need, Source, Proof, Goal,
Release, Role, Principle, Decision) and every field a need can carry. Proof locators are `<adapter>:<payload>`.
