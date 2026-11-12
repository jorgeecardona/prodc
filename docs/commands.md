# Commands

Commands take `--config prodc.toml` (default) and `--json`, except: `report` and `sync` have no `--json`; `agent` and `guide` take neither; `portfolio` takes paths instead of `--config`. `prodc -C DIR …` runs as if started in `DIR`. Exit 0 ok · 1 gate failed · 2 config/load error.

## Read

| Command | Does | Example |
|---|---|---|
| `status` | The board: needs vs proofs, per who, with goals/releases/roster/handoffs/recurrence/orphans | `prodc status --only-must` |
| `lint` | CI gate. **Fails** on: a BROKEN proof, a BROKEN principle guard or `implemented_in`, a must-have with no evidence. **Warns** on: dupes, unlinked recurrence, stale evidence, importance off-scale/unrevisited, `who`-name variants, a contradiction left both-live, an orphaned or stale decision, a decision committed before its research settled or decided against it (`awaits`), a BROKEN source locator, a VIOLATED principle, tag hygiene, a must-have DELIVERED on declared proofs only, a `path` start or outcome that is not a view, an untyped view, flow-step shape (out of order, mixed, never reaches the terminal step). `--strict` makes warnings fail. See `[lint]`, `[flows]`, `[principles]` | `prodc lint --strict` |
| `show <id>` | One need as a citable answer (grounds, warrant, sources, proofs), or one decision (what it serves, rejected, rests on, and BLOCKED/READY on the research it `awaits`) | `prodc show N-1` |
| `brief <client>` | Pre-meeting agenda for one client: its opinions and HOLEs, must first | `prodc brief acme` |
| `inbox` | Open decisions only a person can make: must-have opinions with no decision, and warrant reviews that returned `concerns` or `fail`. Each item lists its options as ready commands. It only lists; it never records an answer (#113) | `prodc inbox` |
| `plan` | Ranked backlog: must + state + evidence + recurrence; `importance` refines; `--revisit DAYS` lists only needs whose importance is undated or older than DAYS; `--include-drafts` | `prodc plan --json` |
| `review` | Triage the capture funnel (captured and triaged needs): `--promote ID…` moves each one stage (captured to triaged, triaged to committed), `--promote-all` commits all of them (except any in `--drop`), `--drop ID…` (deletes a staged need, never a committed one); `--dry-run` | `prodc review --promote N-9` |
| `diff <snapshot>` | State changes since a saved `status --json` | `prodc diff last.json` |
| `portfolio <path>…` | Many boards, one scoreboard (+ totals footer); a path is a prodc.toml or a dir to discover boards under (prunes VCS/vendor/hidden dirs, `--max-depth` default 4) | `prodc portfolio projects/` |
| `dupes` | Candidate duplicate need pairs by text similarity; `--threshold` overrides `[lint].duplicate_threshold` | `prodc dupes --threshold 0.7` |
| `issues` | Deprecated: use `prodc issue list`. Prints a notice to stderr, then runs it | `prodc issue list --need N-3` |
| `views` | Each client's views as a tree (children under their parent), with the needs that point at each view (a `views:` proof or a `path` start or outcome) and their state. Flags `unjustified` (no need points at the view or any child, and `needless_ok` is false), `untyped` (`kind` is null) and `orphan` (no inbound link). The `in/out` column counts links; `--json` lists them with their `why`. `--links` prints each view's outgoing links and reasons. `--graph mermaid` prints one Mermaid flowchart per client (`-o PATH` writes it to a file). The last lines give `unreachable from an entry view` (views no entry view leads to (an entry is a view a need's `path.start` names)). `--client web` shows one client; `--json` for tools that draw the graph. See `[proofs.views]` in config.md | `prodc views --client web` |
| `recurrence` | Baselines shared across clients; `--suggest` proposes unlinked cross-client needs that could share one (set `variant_of` or `not_variant_of`); `--suggest --apply --baseline-id ID --file F` creates a shared baseline for the top group and links its members (`--dry-run` to preview); `--threshold` overrides `[lint].duplicate_threshold` | `prodc recurrence --suggest --apply --baseline-id B-1 --file needs/base.yaml` |
| `suggest [id]` | Candidate proof locators for HOLE needs, ranked by text similarity to adapter inventories; `--min-score --top --kind` (with `--kind` naming an `external` or `evalgate` proof, every recorded key is offered, ranked by score and not cut by `--min-score`; an evalgate suggestion is `metric>=current score`, so raise the threshold to the real bar); `--apply` writes the best per need as a proof (`--dry-run` to preview) | `prodc suggest H-1 --min-score 0.4 --apply` |
| `report` | Render the board as a shareable document for a PM to read, share, or print. `--format md` (default) is a readable markdown document; `--format html` is a single self-contained, interactive, read-only viewer (filter by state/client, search, expand a need, regroup by client/goal/release/state, print to PDF) with no external assets. `--format csv` writes one row per need (id, client, who, state, must, importance, goal, release, warrant, source type, proof detail, text) for a spreadsheet; `--format jira` writes Jira wiki markup and `--format confluence` writes Confluence storage format, both ready to paste. `-o PATH` (or `--out PATH`) writes a file. `--client ID`, `--goal ID` and `--only-must` scope the needs. The user signal column adds the source type read from the locator, for example `secondary (ticket)`. Identifiers with `-` or `_` are shown as titles. With `--format md` only: `--title TEXT` replaces the heading, `--hide-empty` drops the explainer and an empty Open questions section, `--only-open` prints just the Open questions brief | `prodc report --format html -o status.html` |
| `sync` | Run the configured lifecycle callbacks (`[callbacks]`) for needs whose state changed since the last sync: resolves the board, diffs it against the state ledger, pipes each changed need + board context to the callback command as JSON on stdin, and writes the ledger forward. First run records a baseline and fires nothing; a failed callback is reported, exits non-zero, and leaves its need un-advanced so the next sync retries. `--dry-run` shows what would fire | `prodc sync` |
| `agent` | Print prodc's agent playbook so a coding agent runs prodc as the project's PM; `--write PATH` writes it into the repo (`--force` to overwrite) | `prodc agent >> AGENTS.md` |
| `guide` | Print prodc's short human CLI onboarding guide; `--write PATH` writes it into the repo | `prodc guide` |

### `status` flags

| Flag | Effect |
|---|---|
| `--wide` | never clip need text |
| `--columns id,state,text,…` | flat table of just those columns (`id state grounds text who role warrant declared must opinion goal release client`) |
| `--only-must` | must-haves only |
| `--include-drafts` | include draft (staged) needs; by default they are hidden and uncounted (#60) |
| `--stale DAYS` | only needs whose newest `observed_at` is older than DAYS (`[lint].stale_after_days` makes it a lint warning) |
| `--client ID` / `--goal ID` / `--tag TAG` | scope board and coverage to one client / goal / tag |
| `--strict` | also exit 1 on any opinion |
| `--min-coverage 0.8` | exit 1 below that delivered/total |
| `--max-dangling N` | tolerate N BROKEN proofs (default 0) |
| `--max-orphans N` | exit 1 above N proofs claimed by no need |

Needs with `product: false` (deprecated) are listed out of scope and not counted.

## Write

Each rewrites one YAML file, re-loads the whole model as validation, reverts on failure, prints the diff. All take `--dry-run` and `--expect-sha SHA256` (refuse if the file changed since you read it).

| Command | Does | Example |
|---|---|---|
| `set <id> key=value` | set one field; `key+=value` appends to a list (`children+=ID@step` adds a stepped edge); `importance=<n\|label>` is checked against the `[importance]` rubric and stamps `importance_set_at` | `prodc set N-2 importance=needed` |
| `capture <id> --kind K` | append a source (`K` = `primary`\|`secondary`\|`assumption`; old `interview`/`artifact`/`proxy`/`internal` still accepted); `--who --date --quote --locator --anchor --observed-at` (observed-at defaults to today, for staleness) | `prodc capture N-3 --kind primary --who Ana --date 2026-10-05 --quote "…"` |
| `accept <id> --who W --date D` | add an `accept:W@D` proof; `--revoke` removes it | `prodc accept N-2 --who jorge --date 2026-10-05` |
| `attest <id> --by X --date D --verdict V` | record a review that the proofs establish the need; `--verdict pass\|concerns\|fail` is required (only pass clears it; anything else warns), `--ai --comment` | `prodc attest N-1 --by claude-fable-5-1 --ai --date 2026-10-05 --verdict pass` |
| `outcome <id> --landed\|--not-landed --by X --date D` | record whether a delivered need moved its goal; `--evidence` says what was observed. `--not-landed` keeps the need DELIVERED but makes its confidence weak and drops it from its goal (#97) | `prodc outcome N-1 --not-landed --by jorge --date 2026-10-24 --evidence "flat for 4 weeks"` |
| `withdraw <id> --reason R` | record a decision against the need: off the board + out of coverage, the record kept; `--kind wont_do\|out_of_scope\|duplicate`, `--of` (the original, required for duplicate), `--principle` (the vision it rests on); `--date` defaults to today | `prodc withdraw N-7 --reason "dup" --kind duplicate --of N-3` |
| `withdraw decision <id> --reason R` / `reinstate decision <id>` | supersede / restore a decision (noun-first; ids are unique per noun) | `prodc withdraw decision D-1 --reason "superseded by D-7"` |
| `reinstate <id>` | remove a need's withdrawal, putting it back on the board (errors if not withdrawn) | `prodc reinstate N-7` |
| `add need <id> --text T --who W --file F` | new need with agent provenance; `--kind assumption\|secondary` (never primary: earned by a real user, not an agent); warns on a possible duplicate, `--strict-dupes` refuses, `--no-dupe-check` skips; `--draft` stages it off the board (promote with `review --promote <id>`, or `set <id> draft=false`) | `prodc add need N-9 --text "…" --who bot --file needs/bot.yaml --draft` |
| `add role <id> --text T --file F` | declare a Role in `F`'s `roles:` list (new file created if needed); duplicate id refused | `prodc add role owner --text "owns the roastery" --file needs/roles.yaml` |
| `add principle <id> --text T --file F` | declare a principle (the vision); `--scope` (must be in `[principles].scopes`, default `product`), `--implemented-in LOCATOR` (the one place the values live), `--proof LOCATOR` (repeatable guard tests → ENFORCED/VIOLATED); `--from-need <id>` promotes a need, copying its text + sources | `prodc add principle P-1 --text "local-first" --file needs/principles.yaml` |
| `revise principle <id> [--text] [--date]` | re-state a principle; re-stamps `revised_at`, which flags decisions taken under the old version for re-review | `prodc revise principle P-1 --text "…"` |
| `add decision <id> --text T --needs IDS --file F` | the solution chosen for a need (OST); `--alternative` (repeatable, the rejected options), `--consequences`, `--principles`, `--date` | `prodc add decision D-1 --text "store as FLAC" --needs N-1 --alternative WAV --file needs/decisions.yaml` |

`set` fields: `text description who role must importance claim goal release variant_of client product draft`; lists: `proofs children contradicts tags`. On a decision, `set D-1 awaits+=Q-1@yes` adds research it waits on and `awaits-=Q-1@yes` drops it.

## Issues

The issue register is `docs/issues/*.md`, one file per issue, graded by the folder's
`config.toml`. All take `--json`. prodc reads the files matched by `[prodc].issues`, or the
register it finds from the project root when that key is not set.

| Command | Does |
|---|---|
| `issue board [--status S] [--area A] [--owner O]` | issues ready to pick up and what the rest waits on; a filter gives a flat list |
| `issue list [--need ID] [--config F]` | each issue, the needs it serves, and each need's state; `--need` keeps one need's issues |
| `issue show <name>` | print one issue (a filename or part of its slug) |
| `issue file --title T --area A --body B [--need ID] [--blocked-by SLUG] [--field K=V]` | file a new issue (`--body -` reads stdin). `--need` (repeatable) names a need it serves; an unknown id is refused (exit 2). With no `--need` it files and warns "issue serves no need" |
| `issue update <name> [--title] [--status] [--area] [--owner NAME] [--blocked-by SLUG \| --clear-blocked-by] [--field K=V]` | change only what you pass. An in-progress issue needs an owner; `--owner none` clears it |
| `issue close <name> --fixed-in SHA` | mark done; the file stays, carrying the sha. Prints each linked need's state and warns "closed but unproven" when one is not DELIVERED (exit 0) |
| `issue check` | grade the folder against its `config.toml`; exit 1 on problems |
| `issue reindex` | rewrite the README index table |

## MCP

| Command | Does |
|---|---|
| `mcp serve` | run the MCP server on stdio (needs `prodc[mcp]`) |
| `mcp install [--client claude\|cursor\|vscode\|codex] [--scope project\|user] [--command CMD] [--dry-run]` | add the `prodc` entry to the client's project config |
| `mcp uninstall [--client ...] [--dry-run]` | remove the `prodc` entry |

See [mcp.md](mcp.md).
