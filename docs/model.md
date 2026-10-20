# Model

All nouns live in the files matched by `[prodc].files` (or its older alias `[prodc].needs`). Any file may carry `needs:`, `goals:`, `releases:`, `roles:`, `principles:`, `decisions:`. Cross-references are string ids, checked at load.

## Nouns

prodc has **8 nouns**: the 3 it started with, and 5 added since. A noun is anything with an
id that other records point at and its own slot in the model; everything else is a field.

| Noun | One line | Key |
|---|---|---|
| **Need** | what a named person wants; a flow is a need with `children` | `needs:` |
| **Source** | where it came from; `primary`/`secondary`/`assumption` — no primary/secondary = opinion | `sources:` on a need |
| **Proof** | `<adapter>:<payload>` resolved against the repo | `proofs:` on a need |
| **Goal** | measurable objective needs trace up to; `id`, `text`, `metric`, `description`, `target` | `goals:` |
| **Release** | ship slice; list order = ship order; `id`, `text` | `releases:` |
| **Role** | a named function in the product's world; `who`+`client` is an instance of it (John@Sincerely is the `owner`); `id`, `text` | `roles:` |
| **Principle** | the vision, held as given (not validated); `scope`, `sources`, `revised_at`, guard `proofs` + `implemented_in`; an `out_of_scope` withdrawal cites it, and revising it re-opens decisions taken under it | `principles:` |
| **Decision** | the solution chosen for a need over the `alternatives` rejected (OST), resting on which `principles`; `needs` required | `decisions:` |

### The nouns and why each exists (#92)

v0.1 was three nouns (Need, Source, Proof). Each added noun had to pass one test:
**a noun exists only if (a) several needs point at it, and (b) it carries its own fields or
its own derived state.** Fail (a) and it is a field on a need; fail (b) and it is a string.

| Noun | Why it is not a need field | In use (2026-10) |
|---|---|---|
| Goal | many needs roll up to one goal with its own `metric`/`target` and a derived state; as a string on each need the metric would be copied and the roll-up lost. Also covers "initiative" (#80). | crm, tyko |
| Release | the list *order* is the ship order — a string on a need has no order. The weakest keeper. | crm, tyko |
| Role | a declared vocabulary: the loader checks `role` against it (free-text `who` is never checked), and `status` groups by it. | tyko |
| Principle | never counted in coverage; has its own sources, revision ripple and guard state (ENFORCED/STATED/VIOLATED/BROKEN). As a need it would be counted and would need a `who`. | crm, timbre |
| Decision | many-to-many: one decision serves several needs, so it cannot live on one need. | crm |

**Not nouns** (no id of their own): a *question* is a need with `claim` and `answer`; a
*review* is the `draft` lifecycle plus an `attestation`. These value objects live on a need:

| Value object | On | Means |
|---|---|---|
| `attestation` | need | a review that the proofs establish the need; `verdict` pass/concerns/fail (only pass clears it) |
| `withdrawn` | need, decision | a decision against it (won't-do / superseded); the record stays as its trace |
| `children` edge | need | a flow step: `{id, step}`, or a bare id |

The surface that grew most is not the noun count but `Need` itself (27 fields). Several are
shipped with no consumer yet — `answer`, `claim`, `need:` proofs, `withdrawn`, `tags` — and
should earn their keep before more are added.

File-level `who`, `client` default every need in that file.

## Need fields

| Field | Means |
|---|---|
| `id` | unique across all files |
| `text` | the need; EARS shape (`When …, who can …`) is checked softly |
| `description` | optional free-form markdown detail (edge cases, rationale, a worked scenario); **not** EARS-checked — keeps the one-line `text` scannable (#73) |
| `who` | the person (free text — John, Jacob) |
| `role` | Role id — the role `who` plays; checked against declared `roles:` |
| `must` | must-have; a must with no proof tops the board |
| `contradicts` | need ids this one opposes (symmetric); `lint` flags a pair left both-live |
| `sources` | evidence list (see ladder) |
| `proofs` | locators (leaf needs only; a flow uses `seam`) |
| `children` | flow edges — a bare need id, or `{id, step}` naming the step it plays (`[flows].steps`); makes this a flow that rolls them up |
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
| `tags` | flat filter labels (`status --tag X`); `lint` flags singletons, near-duplicate spellings, and a tag that names a goal/role/release/client |
| `goal` | Goal id; absent = flagged ungoaled |
| `release` | Release id |
| `product` | `false` = infra/NFR, listed but not counted |
| `withdrawn` | `reason`, `date` — a decision against the need (won't-do): always off the active board and out of coverage, with the record as its trace; set with `withdraw`, cleared with `reinstate` (#74) |
| `answer` | `yes`/`no`/`inconclusive` — which way a settled need resolved. DELIVERED = settled; `answer` is the direction. A settled-NO (a disproven hypothesis, a failed A/B test, a refuted conjecture) is DELIVERED and still counts — a result, not a gap, and not `withdrawn`. Universal: a product bet and a research question use it the same way. Authored, never computed; unset = open-ended. Flagged if set while not DELIVERED |

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
| `who` | the person (a primary source needs one) |
| `date` | when it was said/written; missing = warned |
| `quote` | verbatim (a primary source wants a quote or a locator) |
| `locator` | ticket/doc ref (a secondary source needs one); `[sources.*]` adapters check it resolves |
| `observed_at` | ISO date the evidence was recorded; `capture` stamps it. Newest across sources = the need's evidence age (`status --stale`, `[lint].stale_after_days`) |

## Ladders

Strongest first — the academic primary/secondary split, plus the floor.

| Source `kind` | Is |
|---|---|
| `primary` | straight from the user: an interview, their own email / message / ticket |
| `secondary` | existing/mediated material about them: a report, a third-party or internal doc |
| `assumption` | our own stated guess — no external evidence yet (the floor every need has at least) |

A need with **no `primary` or `secondary` source** — only an assumption, or nothing — is an
**opinion** (nothing from the user or the world yet). Old kind names still load, mapped on:
`interview`→`primary`, `artifact`→`secondary`, `proxy`/`internal`→`assumption`.

| Attestation `kind` | Is |
|---|---|
| `human` | a person reviewed the proof link |
| `ai` | a model reviewed it (`who` = model id) |
| *(none)* | DELIVERED but unreviewed — warned |
