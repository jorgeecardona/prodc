# Model

All nouns live in the files matched by `[prodc].needs`. Any file may carry `needs:`, `goals:`, `releases:`, `argument:`. Cross-references are string ids, checked at load.

## Nouns

| Noun | One line | Key |
|---|---|---|
| **Need** | what a named person wants; a flow is a need with `children` | `needs:` |
| **Source** | where it came from; none = opinion | `sources:` on a need |
| **Proof** | `<adapter>:<payload>` resolved against the repo | `proofs:` on a need |
| **Goal** | measurable objective needs trace up to; `id`, `text`, `metric` | `goals:` |
| **Release** | ship slice; list order = ship order; `id`, `text` | `releases:` |
| **ArgNode** | GSN node: `kind` claim/strategy/evidence/context/assumption/justification, `supported_by`, `in_context_of`, `about` | `argument:` |
| **Attestation** | a review that the proofs establish the need | `attestation:` on a need |

File-level `who`, `label`, `client` default every need in that file.

## Need fields

| Field | Means |
|---|---|
| `id` | unique across all files |
| `text` | the need; EARS shape (`When …, who can …`) is checked softly |
| `who` | persona |
| `label` | free text for `who` |
| `must` | must-have; a must with no proof tops the board |
| `sources` | evidence list (see ladder) |
| `proofs` | locators (leaf needs only; a flow uses `seam`) |
| `children` | sub-need ids; makes this a flow that rolls them up |
| `seam` | end-to-end locators for a flow's between-steps behaviour; flow is DELIVERED only when every child *and* the seam are green |
| `client` | this instance is for one client; absent = shared baseline |
| `variant_of` | baseline id this specialises; variants cannot chain |
| `not_variant_of` | ids confirmed *not* a shared baseline; silences `recurrence --suggest` / lint for that pair |
| `not_duplicate_of` | ids confirmed *not* a duplicate; silences `dupes` / lint for that pair |
| `importance` | positive int, refines `plan` ranking only; must be on the `[importance]` rubric when one is declared |
| `importance_set_at` | ISO date `importance` was last set; `set importance=` stamps it, lint flags it missing or older than `[lint].importance_revisit_days` |
| `draft` | `true` = staged: loads, but hidden and uncounted until promoted (`set <id> draft=false`); `--include-drafts` shows it |
| `claim` | what delivering this would establish |
| `attestation` | `who`, `date`, `kind` human/ai, `verdict`, `comment` |
| `goal` | Goal id; absent = flagged ungoaled |
| `release` | Release id |
| `product` | `false` = infra/NFR, listed but not counted |

## States

| State | Means | Fails? |
|---|---|---|
| DELIVERED | every proof passes (`*` = declared by tag/existence, no results) | no |
| PENDING | proof found, not green | no |
| HOLE | no proof — an honest gap | never |
| BROKEN | a locator resolves to nothing | yes |
| UNRESOLVED | a source could not be read (sibling absent) | no, excluded from coverage |

## Source fields

| Field | Means |
|---|---|
| `kind` | see ladder below |
| `who` | the person (interview needs one) |
| `date` | when it was said/written; missing = warned |
| `quote` | verbatim (interview needs one) |
| `locator` | ticket/doc ref (artifact needs one); `[sources.*]` adapters check it resolves |
| `observed_at` | ISO date the evidence was recorded; `capture` stamps it. Newest across sources = the need's evidence age (`status --stale`, `[lint].stale_after_days`) |

## Ladders

Strongest first.

| Source `kind` | Is |
|---|---|
| `interview` | a named user, a date, a verbatim quote |
| `artifact` | a ticket / doc / email locator |
| `proxy` | the author is a plausible user, guessing as one |
| `internal` | a team member's own assertion |
| *(none)* | opinion |

| Attestation `kind` | Is |
|---|---|
| `human` | a person reviewed the proof link |
| `ai` | a model reviewed it (`who` = model id) |
| *(none)* | DELIVERED but unreviewed — warned |
