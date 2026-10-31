# Config

Everything lives in `prodc.toml`. Only `[prodc].files` is required (`[prodc].needs` is the older alias;
the two are merged). Every matched file may carry any noun list (`needs:`, `roles:`, `principles:`,
`decisions:`, …), so decisions can live in their own folder.

The EARS / solution-verb text lint fires only on a need that has not stated its `claim` (the
warrant, what delivering it would establish). State the claim and the lint goes quiet: one board
serves a product PM and a research lab head with no mode, because "When a roaster opens the queue,
she can see today's orders" and "Prove that π is irrational" are the same claim under uncertainty.
Source-hygiene warnings (about evidence, not phrasing) always run.

```toml
[prodc]
files = ["needs/*.yaml"]

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

[principles]
scopes = ["product", "design", "engineering"]

[flows]
steps = ["trigger", "act", "conclude"]
```

## `[proofs.<name>]`

A proof is `<name>:<payload>`.

| `kind` | payload | DELIVERED when | extra keys |
|---|---|---|---|
| `gherkin` | `file.feature#Scenario title` or `tag:@X` | results report passes, else a `delivered` tag | `paths`, `delivered`, `pending`, `results` |
| `pytest` | `tests/test_x.py::test_y` | junit passes, else the test exists (declared) | `root`, `results` |
| `vitest` | `src/x.test.ts#test title` (or the `describe > it` path) | `vitest --reporter=junit` report passes, else the file and title exist (declared); a failing test is PENDING *not* declared, so a principle it guards reads VIOLATED; skipped/todo stays declared | `root` (the vitest root), `results` |
| `files` | `path/to/script` | file exists (declared) | `root` |
| `accept` | `who@date` | always (a human sign-off, declared) | (none) |
| `prototype` | `ref@who@date` | always (validated with a user, declared) | (none) |
| `citation` | `ref@author@year` | always (a cited published result, declared); records *what settles it*, vs `accept`'s *who signed off* | (none) |
| `coverage` | category | category is in `catalog` | `catalog` |
| `field` | field name | field is `surfaced` in `schema` | `schema` |
| `external` | observable-outcome key | key recorded passing in `results` (a JSON `{key: bool}`); implementation-independent | `results` |
| `evalgate` | `metric>=threshold` (`>=`/`<=`/`>`/`<`) | the recorded score meets the gate; score in `results` as `{metric: {score: N}}` or `{metric: N}` | `results` |
| `command` | anything your hook understands | your hook prints `{"state": "delivered"}` | `command`, `timeout` |
| `views` | `client:id`, for example `web:/roast/sessions/$planId#batches` or `ios:RoastSession` | the view is in an inventory file (declared); a concrete URL such as `web:/roast/sessions/42` claims the `$param` view it fits | `files` |
| `need` | `other-need-id` or `other-need-id@yes\|no\|inconclusive` | the referenced need is settled (DELIVERED); the `@answer` form also requires its authored `answer` to match | (built in; not configured) |

Any adapter takes `repo = "../sibling"` to resolve against a sibling checkout; absent sibling → UNRESOLVED, not BROKEN. `results` (cucumber-json or junit XML) turns declared states into real ones.

`need` is a need→need edge for the question→question DAG ("B can't be posed until A settles"): a proof whose payload is another need id. It is resolved by prodc itself, not a configured adapter, so it needs no `[proofs.need]` block (one would be shadowed). Cycles (A→B→A) resolve to BROKEN, not an infinite loop. B does not inherit A's answer. The dependency only requires A settled, optionally in a given direction.

### `command`: the generic hook

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

`state` is `delivered` / `pending` / `broken` / `unresolved`; `detail` is optional. The command comes only from this config (trusted); the locator is passed as data, never executed. A non-zero exit, a timeout, unparseable output, or an unknown `state` resolves to UNRESOLVED ("could not read"), never a false DELIVERED. The hook inherits the environment and owns any network/secrets itself.

### `views`: the view inventory

Each client generates one JSON file listing its views. prodc reads the files and never reads app
code. The web app writes it from its router, a mobile app from its navigator.

```toml
[proofs.views]
kind = "views"
files = ["product/views/web.json", "product/views/ios.json"]
```

```json
{
  "schema": 1,
  "client": "web",
  "generated_from": "apps/website/src/router.tsx@<sha>",
  "views": [
    {"id": "/roast/sessions/$planId", "kind": "page", "parent": null, "section": "roast",
     "needless_ok": false},
    {"id": "/roast/sessions/$planId#batches", "kind": "section", "parent": "/roast/sessions/$planId"}
  ],
  "links": [
    {"from": "/roast/sessions", "to": "/roast/sessions/$planId",
     "why": "A roaster opens the session to see its batches."}
  ]
}
```

- `id`: the view. `:id` and `{id}` path params are read as `$id`.
- `kind`: free text (page, screen, section, dialog, window). Null means untyped.
- `parent`: the view that contains this one. `links` are navigation. They are separate relations.
- `orphan_ok` was removed, and a file that still has it fails to load. There is no flag that
  excuses an orphan. A view is an entry (a place users start) when a need's `path.start` names it.
- `needless_ok`: no need is expected for this view (redirect, auth, public page).
- link `why`: the reason a user takes the link. Optional. A link may also carry `need`, a need id.

Link checks run only for a client whose file has at least one link:

- Orphan view: a top-level view with no inbound link that no need's `path.start` names. `lint` warns, and
  `prodc views` shows `[orphan]`. A child view is reached through its parent, so it is never an
  orphan. Fix it with a link, or with a need whose `path` starts there.
- Dangling link: a `from` or `to` that is not a view of the same client. `lint` fails.
- Walkable path: a need's `path.start` and `path.outcome` on the same client must be joined by
  links. A link costs one click. Containment costs none for a child that is not a `page` (a
  section, dialog or tab). A page under a page costs what its links cost. `status` and `lint`
  warn when there is no route, or when the route is longer than `max_clicks`.

A view that exists is a declared DELIVERED (`*`): it proves the view is there, not that the need
works. A child view and its parent are graded separately. Views appear in `prodc orphans`, and
`prodc suggest` leaves them out unless you pass `--kind views`. A missing or malformed file
resolves to UNRESOLVED.

## `[sources.<name>]`

| `kind` | checks | keys |
|---|---|---|
| `frontmatter` | a source `locator` of `file.md#heading` exists | `paths` |
| `gitlab` | a source `locator` of `#123` (or `group/project#123`) is a real GitLab issue (read-only, token from `token_env`; missing token/offline → unverified, 404 → broken) | `base_url`, `project`, `token_env` |
| `command` | a source `locator` your hook resolves; prints `{"exists": true, "who": ..., "date": ..., "quote": ...}` | `command`, `timeout` |

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
| `draft_max_age_days` | lint warns when a staged draft's `draft_added` is older than this, so a batch is not forgotten (triage with `prodc review`) | off |
| `unjustified_views` | `"warn"` or `"error"`: lint reports a view no need points at | off |
| `link_without_why` | `"warn"` or `"error"`: lint reports a view link with no `why` | off |

## `[add]`

| Key | Means | Default |
|---|---|---|
| `default_draft` | `add need` stages as `draft: true` unless told otherwise | `false` |

## `[principles]`

| Key | Means | Default |
|---|---|---|
| `scopes` | the allowed principle scopes: a principle's `scope` (and `add principle --scope`) must be one of these, or the load fails; lets product, design, visual and engineering principles share one board | `["product"]` |

## `[flows]`

| Key | Means | Default |
|---|---|---|
| `steps` | ordered step vocabulary for flow edges (`children: [{id, step}]`); the **last** entry is the terminal step that ends a journey | none (step is free text) |

A flow is a need with `children`; each edge can name the `step` it plays in the journey (a use
case = flow + role + per-edge step). Declaring `steps` turns that free text into a checked axis:

- An edge whose `step` is not in the list is a **hard load error** (a typo like `conlcude` is
  refused at load, and because the writer re-loads and reverts, refused at write time too).
- `lint` then grades each journey's shape (warnings, keyed by flow id; `--strict` makes them fail):
  a flow whose stepped edges never reach the terminal step, steps that run **out of order**, or a
  flow that **mixes** stepped and bare edges. A flow with no stepped edges is exempt. It is a
  plain flow, not a use case.

Order is the journey and must not repeat a step. Leaving `[flows].steps` unset keeps the old
behaviour: any step (or none) passes, and the lint is silent.

## `[callbacks]`: lifecycle callbacks (#71)

`prodc sync` runs a command when a need's state changes (e.g. a proof turns green). Same trust model as the command hook: the command is from this config, never from need data; the changed need + board context are piped to it as JSON on **stdin**, never executed.

```toml
[callbacks]
state_file = ".prodc/state.json"   # the state ledger (default); gitignore it (it is local state)

[[callbacks.hooks]]
on = "state_change"                # the only event today (capture/report/pre_gate are follow-ups)
to = ["delivered"]                 # fire only on transitions INTO these states (optional; empty = any)
from = ["pending", "hole"]         # fire only on transitions OUT OF these states (optional; empty = any)
command = ["./hooks/notify.sh"]    # argv (no shell); receives the JSON payload on stdin
timeout = 30                       # seconds (optional, default 30)
```

The stdin payload is `{"event", "from", "to", "need": {id, text, state, who, client, must, goal, release, warrant}, "board": {coverage_pct, delivered, total}}`. A need is DELIVERED-green when `to == "delivered"`; use that to update the external tracker, notify the owner, or append to a changelog.

`sync` resolves the board, compares it to the ledger, fires the matching callbacks, and writes the ledger forward. The **first run** records a baseline and fires nothing (everything would look new). A callback that fails (non-zero exit, timeout, or spawn failure) is reported, makes `sync` exit non-zero, and its need is left un-advanced in the ledger so the next `sync` retries it. `--dry-run` shows which transitions would fire without running anything or writing the ledger.
