# Model

All nouns live in the files matched by `[prodc].files` (or its older alias `[prodc].needs`). Any file may carry `needs:`, `goals:`, `releases:`, `roles:`, `principles:`, `decisions:`. Cross-references are string ids, checked at load.

## Nouns

prodc has **8 nouns**: the 3 it started with, and 5 added since. A noun is anything with an
id that other records point at and its own slot in the model; everything else is a field.

| Noun | One line | Key |
|---|---|---|
| **Need** | what a named person wants; a flow is a need with `children` | `needs:` |
| **Source** | where it came from; `primary`/`secondary`/`assumption`; no primary/secondary = opinion | `sources:` on a need |
| **Proof** | `<adapter>:<payload>` resolved against the repo | `proofs:` on a need |
| **Goal** | measurable objective needs trace up to; `id`, `text`, `metric`, `description`, `target` | `goals:` |
| **Release** | ship slice; list order = ship order; `id`, `text` | `releases:` |
| **Role** | a named function in the product's world; `who`+`client` is an instance of it (John@Sincerely is the `owner`); `id`, `text` | `roles:` |
| **Principle** | the vision, held as given (not validated); `scope`, `sources`, `revised_at`, guard `proofs` + `implemented_in`; an `out_of_scope` withdrawal cites it, and revising it re-opens decisions taken under it | `principles:` |
| **Decision** | the solution chosen for a need over the `alternatives` rejected (OST), resting on which `principles`; `needs` required (what it *serves*); optional `awaits` (the research it *waits on*) | `decisions:` |

### The nouns and why each exists (#92)

v0.1 was three nouns (Need, Source, Proof). Each added noun had to pass one test:
**a noun exists only if (a) several needs point at it, and (b) it carries its own fields or
its own derived state.** Fail (a) and it is a field on a need; fail (b) and it is a string.

| Noun | Why it is not a need field | In use (2026-10) |
|---|---|---|
| Goal | many needs roll up to one goal with its own `metric`/`target` and a derived state; as a string on each need the metric would be copied and the roll-up lost. Also covers "initiative" (#80). | crm, tyko |
| Release | the list *order* is the ship order; a string on a need has no order. The weakest keeper. | crm, tyko |
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
shipped with no consumer yet (`answer`, `claim`, `need:` proofs, `withdrawn`, `tags`) and
should earn their keep before more are added.

File-level `who`, `client` default every need in that file.

## Research a decision waits on (#93)

A decision can wait on evidence that does not exist yet: an interview, a fake-door test, a
spike, a dataset. Each research item is an ordinary need, not a new noun:

```yaml
needs:
  - id: Q-ledger-wanted
    text: Roasters want balances derived from movements, not a stock column they edit
    claim: A roaster who sees a derived balance does not ask for a "set stock" field
    product: false            # research, not product coverage
    tags: [research, interview]
    proofs:
      - accept:jordan@2026-10-27   # added after the interview; until then no proof = HOLE (planned)
  - id: Q-ledger-cost
    text: A transaction roll-up stays under 50 ms at 1M rows
    claim: Deriving every balance is affordable at our scale
    product: false
    tags: [research, spike]
    proofs:
      - evalgate:rollup_ms<=50
    answer: yes               # authored once it settles

decisions:
  - id: D-ledger
    text: Model inventory as a double-entry ledger
    draft: true
    needs: [US-1403]          # what it serves
    awaits:                   # what it waits on
      - Q-ledger-wanted@yes   # only if the roaster confirms
      - Q-ledger-cost         # settled either way is enough
```

The research need's state is its status: HOLE = planned, PENDING = in progress, DELIVERED =
done (and `answer` gives the direction). The decision is **BLOCKED** until every awaited need is
settled (in the named direction, when one is given), then **READY**. `show D-ledger` lists each
awaited need with its state; `status` tags the decision; `lint` warns when a decision is
committed (`draft: false`) while blocked, decided against its own research, or waits on a
withdrawn or product need. No need state changes: BLOCKED belongs to the decision.

## Glossary

The same word can mean different things in different places. A `glossary:` list (in any prodc
file) says what a term means, globally or for one client.

```yaml
glossary:
  - term: risk
    text: the chance a roast batch is lost
  - term: risk
    text: the chance an order ships late
    scope: client:acme          # absent or "global" = every need
needs:
  - id: N-1
    text: When a roaster plans a day, they can see the risk
    client: acme
    terms: [risk]               # the terms this need uses
```

- A need lists the terms it uses in `terms`. prodc never looks for terms in need text.
- A term has one entry per scope. Two entries for the same term and scope fail to load.
- For a need of client `acme`, the `client:acme` entry is its meaning; otherwise the global one.
- `lint` errors when a need lists a term that has no definition for it.
- `lint` warns when a term has a global meaning and a different one for a client. Spelling and
  spacing differences do not count.
- `report` has a Glossary section, and marks a client meaning that differs from the global one.
- Scopes are `global` and `client:<id>` only.

## Issues

An issue is engineering work. prodc holds product needs and principles; an issue is a markdown file
with YAML front matter (the format cabildo's issue tools write and check). Set
`[prodc].issues = ["docs/issues/*.md"]` and prodc reads them. It never writes one.

```yaml
---
title: "Export the run sheet as CSV"
status: in-progress          # open, in-progress, blocked, done, closed, resolved
needs: [US-1201]             # the needs this issue serves
sources: ["gitlab:#123"]     # pointers into other systems
---
```

| Key | Means |
|---|---|
| `needs` | need ids the issue serves. None means the issue has no want behind it |
| `sources` | `<source adapter>:<payload>` pointers, checked by the adapter you configured under `[sources.<name>]` |
| `status` | as the file says. `done`, `closed` and `resolved` mean finished; anything else is open |

`prodc lint` reads the issues against the board:

| Finding | Level |
|---|---|
| `needs` names an id that is not a need | error |
| the issue serves no need | warning |
| closed, but a need it serves is not DELIVERED | warning (closed but unproven) |
| open, but every need it serves is DELIVERED | warning (proven but open) |
| a `sources` pointer does not resolve | warning |
| a file in the glob has no front matter | one warning for the folder |

`prodc issues` lists them, and `prodc show <need>` lists the issues that serve it. A ticket's state
never makes a need DELIVERED: only a proof does.

## Where things go

Decide where a thing goes before you write it.

| It is | It goes | Example |
|---|---|---|
| something a person wants | a need, with a source | `When an invited user opens the invite link, they can set a password` |
| a rule that decides between wants | a principle | `We do not build per-client forks` |
| engineering work or a bug | an issue in your tracker, not prodc | `the view generator drops links from shared components` |

- prodc never calls a tracker. Engineering work and bugs are issues there.
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

## Need fields

| Field | Means |
|---|---|
| `id` | unique across all files |
| `text` | the need; EARS shape (`When …, who can …`) is checked softly |
| `description` | optional free-form markdown detail (edge cases, rationale, a worked scenario); **not** EARS-checked, keeps the one-line `text` scannable (#73) |
| `who` | the person (free text, e.g. John, Jacob) |
| `role` | Role id: the role `who` plays; checked against declared `roles:` |
| `must` | must-have; a must with no proof tops the board |
| `contradicts` | need ids this one opposes (symmetric); `lint` flags a pair left both-live |
| `sources` | evidence list (see ladder) |
| `proofs` | locators (leaf needs only; a flow uses `seam`) |
| `children` | flow edges: a bare need id, or `{id, step}` naming the step it plays (`[flows].steps`); makes this a flow that rolls them up |
| `seam` | end-to-end locators for a flow's between-steps behaviour; flow is DELIVERED only when every child *and* the seam are green |
| `path` | `{start, outcome, max_clicks, proof}`: where the role begins, what means done, the click budget, and the locator of the test that counts the clicks. `lint` warns on a budget with no proof or a proof that does not pass; `show` and `report` print it (#99) |
| `outcome` | `{landed, date, who, evidence}`: whether the delivery moved the goal. `landed: false` makes confidence weak and drops the need from its goal's count, not from coverage. Refused on a research need with `answer` (#97) |
| `client` | this instance is for one client; absent = shared baseline |
| `variant_of` | baseline id this specialises; variants cannot chain |
| `not_variant_of` | ids confirmed *not* a shared baseline; silences `recurrence --suggest` / lint for that pair |
| `not_duplicate_of` | ids confirmed *not* a duplicate; silences `dupes` / lint for that pair |
| `importance` | positive int, refines `plan` ranking only; must be on the `[importance]` rubric when one is declared |
| `importance_set_at` | ISO date `importance` was last set; `set importance=` stamps it, lint flags it missing or older than `[lint].importance_revisit_days` |
| `draft` | `true` = staged: loads, but hidden and uncounted until promoted (`set <id> draft=false`); `--include-drafts` shows it. Same as `stage: captured` |
| `stage` | The capture funnel: `captured` (a raw idea, hidden), `triaged` (reviewed, listed under `status`, not counted), `committed` (counted). No `stage` and no `draft` means `committed`, so an existing board does not change. `draft: true` next to `stage: triaged` or `committed` is an error |
| `claim` | what delivering this would establish |
| `attestation` | `who`, `date`, `kind` human/ai, `verdict`, `comment` |
| `terms` | glossary terms this need uses (see Glossary). Each must be defined for the need's client |
| `tags` | flat filter labels (`status --tag X`); `lint` flags singletons, near-duplicate spellings, and a tag that names a goal/role/release/client |
| `goal` | Goal id; absent = flagged ungoaled |
| `release` | Release id |
| `expects` | The proof kind this need waits for: `test` (gherkin, pytest, vitest), `eval` (evalgate), `observed` (external), `accept` or `prototype`. Advisory: a HOLE shows `awaiting an eval`, `suggest` looks only in that kind of inventory, and `lint` warns when the wired proofs are of another kind. It never changes how a proof resolves |
| `product` | `false` = infra/NFR, listed but not counted |
| `withdrawn` | `reason`, `date`; a decision against the need (won't-do): always off the active board and out of coverage, with the record as its trace; set with `withdraw`, cleared with `reinstate` (#74) |
| `answer` | `yes`/`no`/`inconclusive`: which way a settled need resolved. DELIVERED = settled; `answer` is the direction. A settled-NO (a disproven hypothesis, a failed A/B test, a refuted conjecture) is DELIVERED and still counts (a result, not a gap, not `withdrawn`). Universal: a product bet and a research question use it the same way. Authored, never computed; unset = open-ended. Flagged if set while not DELIVERED |

## States

| State | Means | Fails? |
|---|---|---|
| DELIVERED | every proof passes (`*` = declared by tag/existence, no results) | no |
| PENDING | proof found, not green | no |
| HOLE | no proof (an honest gap) | never |
| BROKEN | a locator resolves to nothing | yes |
| UNRESOLVED | a source could not be read (sibling absent) | no, excluded from coverage |

## Principle states

A principle with guard `proofs` (and an optional `implemented_in` locator) gets a state of its
own (#89); it never enters coverage.

| State | Means | Fails `lint`? |
|---|---|---|
| ENFORCED | every guard test passes | no |
| STATED | no active guard: no proofs, or only declared-pending ones | no |
| VIOLATED | a guard ran and failed: the code contradicts the stance | warns |
| BROKEN | a guard or `implemented_in` locator points at nothing | yes |
| UNRESOLVED | a guard could not be read (sibling repo absent) | no |

## Source fields

| Field | Means |
|---|---|
| `kind` | see ladder below |
| `who` | the person (a primary source needs one) |
| `date` | when it was said/written; missing = warned |
| `quote` | verbatim (a primary source wants a quote or a locator) |
| `locator` | ticket/doc ref (a secondary source needs one); `[sources.*]` adapters check it resolves |
| `anchor` | An exact place inside `locator`: a line range `L120-L134` for a local file, a page `p.7`, a time `00:14:32`. `show` prints `locator#anchor`. For a local file with a `quote`, `status` and `lint` warn when the quote is no longer inside the lines (`source anchor drifted`). Other anchors are not checked |
| `observed_at` | ISO date the evidence was recorded; `capture` stamps it. Newest across sources = the need's evidence age (`status --stale`, `[lint].stale_after_days`) |

## Ladders

Strongest first. The academic primary/secondary split, plus the floor.

| Source `kind` | Is |
|---|---|
| `primary` | straight from the user: an interview, their own email / message / ticket |
| `secondary` | existing/mediated material about them: a report, a third-party or internal doc |
| `assumption` | our own stated guess; no external evidence yet (the floor every need has at least) |

A need with **no `primary` or `secondary` source** (only an assumption, or nothing) is an
**opinion**: nothing from the user or the world yet. Old kind names still load, mapped on:
`interview`→`primary`, `artifact`→`secondary`, `proxy`/`internal`→`assumption`.

| Attestation `kind` | Is |
|---|---|
| `human` | a person reviewed the proof link |
| `ai` | a model reviewed it (`who` = model id) |
| *(none)* | DELIVERED but unreviewed; warned |
