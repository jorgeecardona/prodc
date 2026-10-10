# Config

Everything lives in `prodc.toml`. Only `[prodc].needs` is required.

`[prodc].profile` (default `"product"`) chooses which need grammar the text lint speaks. A
`"product"` board lints need text for EARS shape and solution-verbs (a need is a user-facing
outcome). A `"research"` board's needs are posed questions or claims ("Prove that π is
irrational"), which are not outcomes, so that grammar is skipped and the board stays quiet;
source-hygiene warnings (about evidence, not phrasing) still run. The profile changes no state or
coverage — only which hygiene warnings apply.

```toml
[prodc]
needs = ["needs/*.yaml"]
profile = "research"   # or "product" (default)

[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]

[sources.issues]
kind = "frontmatter"
paths = ["docs/issues/*.md"]

[importance]
levels = [[3, "critical", "blocks launch"], [2, "needed", "first quarter"], [1, "nice", "someday"]]

[lint]
duplicate_threshold = 0.8
stale_after_days = 90
importance_revisit_days = 60

[add]
default_draft = false
```

## `[proofs.<name>]`

A proof is `<name>:<payload>`.

| `kind` | payload | DELIVERED when | extra keys |
|---|---|---|---|
| `gherkin` | `file.feature#Scenario title` or `tag:@X` | results report passes, else a `delivered` tag | `paths`, `delivered`, `pending`, `results` |
| `pytest` | `tests/test_x.py::test_y` | junit passes, else the test exists (declared) | `root`, `results` |
| `files` | `path/to/script` | file exists (declared) | `root` |
| `accept` | `who@date` | always (a human sign-off, declared) | — |
| `prototype` | `ref@who@date` | always (validated with a user, declared) | — |
| `coverage` | category | category is in `catalog` | `catalog` |
| `field` | field name | field is `surfaced` in `schema` | `schema` |
| `external` | observable-outcome key | key recorded passing in `results` (a JSON `{key: bool}`); implementation-independent | `results` |
| `command` | anything your hook understands | your hook prints `{"state": "delivered"}` | `command`, `timeout` |
| `need` | `other-need-id` or `other-need-id@yes\|no\|inconclusive` | the referenced need is settled (DELIVERED); the `@answer` form also requires its authored `answer` to match | — (built in; not configured) |

Any adapter takes `repo = "../sibling"` to resolve against a sibling checkout; absent sibling → UNRESOLVED, not BROKEN. `results` (cucumber-json or junit XML) turns declared states into real ones.

`need` is a need→need edge for the question→question DAG ("B can't be posed until A settles"): a proof whose payload is another need id. It is resolved by prodc itself, not a configured adapter, so it needs no `[proofs.need]` block (one would be shadowed). Cycles (A→B→A) resolve to BROKEN, not an infinite loop. B does not inherit A's answer — the dependency only requires A settled, optionally in a given direction.

### `command` — the generic hook

Resolve a proof against any system with a script, with no per-provider code in prodc. `command` is an argv list (no shell); the need's locator is substituted for every `{locator}` in it, or appended as the final argument when there is none. The hook prints a JSON object to stdout:

```toml
[proofs.jira]
kind = "command"
command = ["./hooks/jira-proof.sh"]   # invoked as: ./hooks/jira-proof.sh <locator>
timeout = 10                           # seconds, optional (default 10)
```

```json
{"state": "delivered", "detail": "PROJ-7 closed"}
```

`state` is `delivered` / `pending` / `broken` / `unresolved`; `detail` is optional. The command comes only from this config (trusted); the locator is passed as data, never executed. A non-zero exit, a timeout, unparseable output, or an unknown `state` resolves to UNRESOLVED ("could not read") — never a false DELIVERED. The hook inherits the environment and owns any network/secrets itself.

## `[sources.<name>]`

| `kind` | checks | keys |
|---|---|---|
| `frontmatter` | a source `locator` of `file.md#heading` exists | `paths` |
| `gitlab` | a source `locator` of `#123` (or `group/project#123`) is a real GitLab issue — read-only, token from `token_env`; missing token/offline → unverified, 404 → broken | `base_url`, `project`, `token_env` |
| `command` | a source `locator` your hook resolves — prints `{"exists": true, "who": ..., "date": ..., "quote": ...}` | `command`, `timeout` |

`command` works the same as the proof hook (argv, `{locator}` or appended, trusted config). `exists: true` resolves the source; `exists: false` flags it BROKEN; a non-zero exit, a timeout, unparseable output, or a missing `exists` → unverified (never a false BROKEN).

## `[importance]`

| Key | Means | Default |
|---|---|---|
| `levels` | rubric: list of `[n, "label", "meaning"]`. Declared → `importance` must be one of these `n`; `set importance=` accepts `n` or the label; lint flags off-scale values | none (any int accepted) |

## `[lint]`

| Key | Means | Default |
|---|---|---|
| `duplicate_threshold` | text similarity in `(0, 1]` that flags a pair in `dupes`, `add`, `recurrence --suggest` and lint | `0.8` |
| `stale_after_days` | lint warns when a need's newest `observed_at` is older than this | off |
| `importance_revisit_days` | lint warns when `importance_set_at` is older than this | off |

## `[add]`

| Key | Means | Default |
|---|---|---|
| `default_draft` | `add need` stages as `draft: true` unless told otherwise | `false` |

## `[callbacks]` — lifecycle callbacks (#71)

`prodc sync` runs a command when a need's state changes (e.g. a proof turns green). Same trust model as the command hook: the command is from this config, never from need data; the changed need + board context are piped to it as JSON on **stdin**, never executed.

```toml
[callbacks]
state_file = ".prodc/state.json"   # the state ledger (default); gitignore it — it is local state

[[callbacks.hooks]]
on = "state_change"                # the only event today (capture/report/pre_gate are follow-ups)
to = ["delivered"]                 # fire only on transitions INTO these states (optional; empty = any)
from = ["pending", "hole"]         # fire only on transitions OUT OF these states (optional; empty = any)
command = ["./hooks/notify.sh"]    # argv (no shell); receives the JSON payload on stdin
timeout = 30                       # seconds (optional, default 30)
```

The stdin payload is `{"event", "from", "to", "need": {id, text, state, who, client, must, goal, release, warrant}, "board": {coverage_pct, delivered, total}}`. A need is DELIVERED-green when `to == "delivered"`; use that to update the external tracker, notify the owner, or append to a changelog.

`sync` resolves the board, compares it to the ledger, fires the matching callbacks, and writes the ledger forward. The **first run** records a baseline and fires nothing (everything would look new). A callback that fails (non-zero exit, timeout, or spawn failure) is reported, makes `sync` exit non-zero, and its need is left un-advanced in the ledger so the next `sync` retries it. `--dry-run` shows which transitions would fire without running anything or writing the ledger.
