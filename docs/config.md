# Config

Everything lives in `prodc.toml`. Only `[prodc].needs` is required.

```toml
[prodc]
needs = ["needs/*.yaml"]

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

Any adapter takes `repo = "../sibling"` to resolve against a sibling checkout; absent sibling → UNRESOLVED, not BROKEN. `results` (cucumber-json or junit XML) turns declared states into real ones.

## `[sources.<name>]`

| `kind` | checks | keys |
|---|---|---|
| `frontmatter` | a source `locator` of `file.md#heading` exists | `paths` |

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
