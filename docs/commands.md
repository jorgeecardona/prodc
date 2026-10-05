# Commands

Every command takes `--config prodc.toml` (default) and `--json`. `prodc -C DIR …` runs as if started in `DIR`. Exit 0 ok · 1 gate failed · 2 config/load error.

## Read

| Command | Does | Example |
|---|---|---|
| `status` | The board: needs vs proofs, per persona, with goals/releases/recurrence/orphans | `prodc status --only-must` |
| `lint` | CI gate: exit 1 on BROKEN proof or a must-have with no evidence; lists warnings | `prodc lint --strict` |
| `show <id>` | One need as a citable answer: grounds, warrant, sources, proofs | `prodc show N-1` |
| `brief <client>` | Pre-meeting agenda for one client: its opinions and HOLEs, must first | `prodc brief acme` |
| `plan` | Ranked backlog: must + state + evidence + recurrence; `importance` refines | `prodc plan --json` |
| `argument` | The GSN graph and its defects (unsupported claim, dangling context) | `prodc argument --strict` |
| `diff <snapshot>` | State changes since a saved `status --json` | `prodc diff last.json` |
| `portfolio <toml>…` | Many repos, one scoreboard | `prodc portfolio a/prodc.toml b/prodc.toml` |
| `dupes` | Candidate duplicate need pairs by text similarity; `--threshold` overrides `[lint].duplicate_threshold` | `prodc dupes --threshold 0.7` |
| `recurrence` | Baselines shared across clients; `--suggest` proposes unlinked cross-client needs that could share one (set `variant_of` or `not_variant_of`) | `prodc recurrence --suggest` |

### `status` flags

| Flag | Effect |
|---|---|
| `--wide` | never clip need text |
| `--columns id,state,text,…` | flat table of just those columns (`id state grounds text who warrant declared must opinion goal release client`) |
| `--only-must` | must-haves only |
| `--include-drafts` | include draft (staged) needs; by default they are hidden and uncounted (#60) |
| `--stale DAYS` | only needs whose newest `observed_at` is older than DAYS (`[lint].stale_after_days` makes it a lint warning) |
| `--client ID` / `--goal ID` | scope board and coverage to one client / goal |
| `--strict` | also exit 1 on any opinion |
| `--min-coverage 0.8` | exit 1 below that delivered/total |
| `--max-dangling N` | tolerate N BROKEN proofs (default 0) |
| `--max-orphans N` | exit 1 above N proofs claimed by no need |

Needs with `product: false` are listed out of scope and not counted.

## Write

Each rewrites one YAML file, re-loads the whole model as validation, reverts on failure, prints the diff. All take `--dry-run` and `--expect-sha SHA256` (refuse if the file changed since you read it).

| Command | Does | Example |
|---|---|---|
| `set <id> key=value` | set one field; `key+=value` appends to `proofs`/`children`; `importance=<n\|label>` is checked against the `[importance]` rubric and stamps `importance_set_at` | `prodc set N-2 importance=needed` |
| `capture <id> --kind K` | append a source; `--who --date --quote --locator --observed-at` (observed-at defaults to today, for staleness) | `prodc capture N-3 --kind interview --who Ana --date 2026-10-05 --quote "…"` |
| `accept <id> --who W --date D` | add an `accept:W@D` proof; `--revoke` removes it | `prodc accept N-2 --who jorge --date 2026-10-05` |
| `attest <id> --by X --date D` | record a review that the proofs establish the need; `--ai --verdict --comment` | `prodc attest N-1 --by claude-fable-5-1 --ai --date 2026-10-05 --verdict pass` |
| `add need <id> --text T --who W --file F` | new need with agent provenance; `--kind internal\|proxy` (never interview); warns on a possible duplicate, `--strict-dupes` refuses, `--no-dupe-check` skips; `--draft` stages it off the board (promote later with `set <id> draft=false`) | `prodc add need N-9 --text "…" --who bot --file needs/bot.yaml --draft` |

`set` fields: `text who label must importance claim goal release variant_of client product`; lists: `proofs children`.
