# Changelog

All notable changes are documented here. Versioning is [SemVer](https://semver.org/).

## [Unreleased]

## [0.11.0] - 2026-11-14

A consolidation release: no new noun and no new proof kind.

### Added

- `prodc lint --write-baseline FILE` saves the current warnings. `prodc lint --baseline FILE` then
  shows only the warnings that are not in the file (PD-3).
- `docs/ci.md`: the official GitLab CI job, with a pinned version and junit results (PD-6).

### Changed

- `prodc lint` prints a warning that repeats over several ids as one line with a count.
  `--all-warnings` lists each id.
- `prodc lint` warns "issue serves no need" only for open issues.
- `prodc lint` no longer warns "belongs to no flow".
- The README says prodc keeps the issue register (`docs/issues`). It does not replace a team's
  external tracker.
- `prodc agent` lists the 12 commands an agent needs. The rest are in `docs/commands.md`.

### Fixed

- A research board with `[prodc] profile = "research"` passes `prodc lint` again. The key is
  ignored and reported as a deprecation warning.

### Removed

- `prodc issues`: use `prodc issue list`. The MCP tool `issues` is gone too: use `issue_list`.
- `prodc guide`.

### Deprecated (removed in 0.12)

Each still works in 0.11. A run prints one line per deprecated thing:
`deprecated, removed in 0.12: <thing>; <what to use instead>`. `prodc lint` lists them as
warnings.

- `prodc sync` and `[callbacks]`: run your own script on `prodc status --json`.
- The gitlab source adapter (`[sources.X] kind = "gitlab"`): cite the ticket URL as a `secondary`
  source locator.
- `prodc outcome`: edit the need's `outcome:` field. The field itself stays.
- `prodc accept`: use `prodc set <id> proofs+=accept:<who>@<date>`.
- `prodc brief`: use `prodc status --client <id>`.
- `prodc recurrence --suggest` and `--apply`: link a variant by hand with `variant_of`.
- `prodc dupes`: `prodc add` and `prodc review` already check for duplicates.
- Need fields `tags`, `importance` (with `[importance]`, `[lint].importance_revisit_days` and
  `prodc plan --revisit`), `contradicts`, `terms`, `expects`, and the top-level `glossary:`.
- Flows: need fields `children` and `seam`, and `[flows].steps`.
- Proof kinds `coverage`, `field` and `prototype`.
- `prodc report --format csv`, `jira` and `confluence`: use `md` or `html`.
- `[prodc].profile`: delete it.

### Migration

1. Run `prodc lint` and read the `deprecated` lines. Each one says what to use instead.
2. Delete `profile = "research"` from `prodc.toml`.
3. Replace `prodc issues` with `prodc issue list` in scripts and CI.
4. Move CI to the job in `docs/ci.md` with `prodc==0.11.0`.
5. To adopt lint on a noisy board, run `prodc lint --write-baseline lint-baseline.txt` once and
   commit the file. Then run `prodc lint --baseline lint-baseline.txt` in CI.

## [0.10.6] - 2026-11-12

### Added

- `prodc issue next [--limit N] [--owner H]` gives the ready issue to work on now, from the
  current release. With no pick it says why (`skip`). MCP tool `issue_next`.
- `prodc plan` ranks the current release first: the first release in `releases:` with a need not
  DELIVERED. A BROKEN need ranks there too. Without `releases:` the order is unchanged.
- `prodc plan --json` rows carry `goal`, `release`, `now` and `issues`; the top level carries
  `current_release`.
- `prodc lint` warns on a need with no release when releases are declared, on a must need in a
  release after the current one, and on a release no need names.
- `prodc issue update --clear-needs` removes every need an issue serves.

### Fixed

- `prodc issue update --field needs=` now clears the list. It wrote `needs: [""]` before. Any
  `--field KEY=` with no value clears that field.

## [0.10.0] - 2026-11-12

### Added

- `prodc issue file --need ID` links an issue to the needs it serves. An unknown need is refused.
  With no need, the issue is filed with the warning "issue serves no need".
- `prodc issue close` prints the state of each linked need and warns "closed but unproven" when
  one is not DELIVERED.
- `prodc issue update --owner NAME` sets who is doing the work (`--owner none` clears it).
- `prodc issue list [--need ID]` lists each issue with its needs and their state. MCP tool
  `issue_list`; `issue_file` takes `needs`, `issue_update` takes `owner`.
- `PRODC_ISSUES_DIR` names the issue folder. `CABILDO_ISSUES_DIR` is still read.

### Changed

- `prodc issues` and the MCP tool `issues` are deprecated: use `prodc issue list`.
- `status`, `lint` and `prodc issue list` read issues with the same parser as `prodc issue`.
  Without `[prodc].issues`, prodc uses the `docs/issues/` register it finds.
- A status of `closed` or `resolved` is reported by `check` and `lint`: use `done` with
  `fixed_in`.
- The README index marker now names `prodc issue reindex`. The old cabildo marker is still read.

### Fixed

- Titles and values with quotes, backslashes, `yes`/`no` or leading-zero numbers are written so
  any YAML reader reads the same string back.

## [0.9.0] - 2026-11-12

### Added

- `prodc issue board|show|file|update|close|check|reindex` reads and writes the issue register
  (`docs/issues/*.md`). The store moved here from cabildo, same file format.
- MCP tools `issue_board`, `issue_show`, `issue_check`, `issue_file`, `issue_update`,
  `issue_close`.

## [0.8.0] - 2026-11-11

### Added

- `prodc mcp serve`: prodc as an MCP server, with the optional extra `pip install 'prodc[mcp]'`.
  10 read tools and 5 write tools. `capture` and `add_need` refuse `primary`. `accept`,
  `outcome`, `attest`, `withdraw` and `sync` are not exposed. See [docs/mcp.md](docs/mcp.md).
- `prodc mcp install` writes the server into `.mcp.json` (or `--client cursor|vscode`). It changes
  only the `prodc` entry and refuses a file it cannot parse. `prodc mcp uninstall` removes it.
- A write's `--json` output has `sha_before` and `sha_after`, to pass as `--expect-sha`.

## [0.7.4] - 2026-11-11

### Added

- A `visual` catalog pack: `[principles].packs = ["visual"]`. Four entries ship a vitest guard
  (text contrast, UI contrast, status not shown by colour alone, no colour literal outside the
  token files). `visual-palette-chosen` is signed off by a person with an `accept:` proof. See
  [docs/visual.md](docs/visual.md).
- `prodc lint` reports an unknown name in `[principles].packs` (lint exits 1).

### Changed

- `prodc add principle --from-catalog` stops with a clear message when the entry's scope is not in
  `[principles].scopes`.

## [0.7.2] - 2026-11-09

### Fixed

- A vitest or Playwright proof now finds a test whose title is a template literal: the locator
  `at most 50 rows` matches ``it(`at most ${LIMIT} rows`)``. Before, the proof was BROKEN.

## [0.7.1] - 2026-11-09

### Changed

- `ux-miller` recipe: replaced placeholder with a source-scanning vitest guard that tests
  a named page-size constant against the agreed threshold (derived from crm
  `apps/website/src/design/millerLaw.guard.test.ts`).
- `ux-jakob` recipe: replaced placeholder playwright test with a source-scanning vitest guard
  that checks every dialog/modal for the shared Escape hook and verifies the logo link in
  Nav.tsx (derived from crm `apps/website/src/design/jakobLaw.guard.test.ts`).

## [0.7.0] - 2026-11-09

### Added

- A `storybook` proof kind: a need can point at the Storybook stories that show it. prodc
  reads the build's `index.json`; a story there is a declared proof.
- `[lint].unjustified_stories` reports Storybook components that no need points at.
- With `url` set on a `storybook` table, `show`, `report` and the HTML report link each story.
- `prodc inbox` lists the decisions only you can make on a board, each with the commands to
  answer it: must-have opinions and warrant reviews with concerns. It never writes (#113).
- `[prodc].name` sets the board name that `status`, `portfolio` and `report` show. The default is
  still the directory name (#125).
- `docs/principles.md` documents how to adopt a UX law as a design principle: concrete rule as
  `text`, the law page as a `secondary` source, and a guard test as the proof.
- `prodc.catalog.ux` ships 30 UX laws from lawsofux.com as catalog entries (`UX_CATALOG`).
  Five are checkable (ux-fitts, ux-hick, ux-von-restorff, ux-miller, ux-jakob) and carry a
  `Recipe` with a snippet for the guard test. `docs/ux-laws.md` lists all 30.
  The ux-fitts, ux-hick, and ux-von-restorff recipes now carry real guard code extracted from
  crm (source-file scanning approach); ux-miller and ux-jakob keep placeholder snippets.
- `Principle` now supports `withdrawn: {reason, date[, kind]}`, reusing the existing `Withdrawal`
  type. A withdrawn principle is not evaluated by lint. `prodc withdraw principle <id>` and
  `prodc reinstate principle <id>` write the field.
- `prodc add principle --from-catalog <id>` seeds a principle from the UX catalog: sets the id,
  scope=design, text from the entry's template, and a secondary source; prints the recipe snippet.
  `--decline <reason>` additionally marks it withdrawn out_of_scope (a deliberate skip, on record).
- `[principles].packs = ["ux"]` lists catalog packs the board opts into.
- `[lint].missing_catalog_principles = "warn"|"error"|"off"` (default `warn`) reports checkable
  entries in the declared packs that have not been added or declined.
- `lint` warns when a principle's text still contains a `{slot}` from the template.

### Fixed

- `capture`, `set`, `accept` and `attest` no longer move a quote line that starts with `#` out of
  its source as a stray line.
- `status` no longer crashes when a results report is empty or not valid JSON/XML, for example
  while the test run is still writing it. The proof detail names the problem (#121).
- pytest proofs no longer take the result of a same-named test in another file, and a
  parametrised test is read from the report: all its cases must pass (#122).
- A pytest proof whose test is missing from the junit report is PENDING ("not in report"), not
  delivered. Proofs on boards with a partial report may turn PENDING (#123).
- `root` now works in every proof table: `gherkin`, `coverage`, `field`, `external`, `evalgate`
  and `views` used to ignore it (#124).

## [0.5.1] - 2026-11-05

The rest of the 0.5 cleanup. It has breaking changes, so read the migrate steps. 0.5.0 was
published before this work was finished. Use 0.5.1.

### Breaking

- `lint` exits 1 on a key `prodc.toml` does not use, such as `profile`. The board still loads.
- `lint` exits 1 on the old source kinds `interview`, `artifact`, `proxy` and `internal`. They still
  load. `add --kind` and `capture --kind` no longer accept them.
- `lint` exits 1 on `product: false`, which is deprecated. It still works, and is removed in 0.6.
- `lint` no longer warns when a decision awaits a need that has no `product: false`.
- `kind = "playwright-ct"` is removed. Use `kind = "playwright"`.
- `Need.draft` in Python is now read-only, derived from `Need.stage`. In YAML, `draft: true` still
  means the captured stage.
- The Python modules are not a public API. Use the CLI, `--json` and the YAML files.

### Migrate

1. For `profile` in `prodc.toml`, delete the line.
2. For old source kinds, run this on your need files:

   ```bash
   sed -i 's/kind: artifact/kind: secondary/; s/kind: interview/kind: primary/; s/kind: \(proxy\|internal\)/kind: assumption/' product/needs/*.yaml
   ```

3. For `note:` or `comment:` on a source, move the text into `quote`, or delete the key.
4. For `product: false`, move engineering work to an issue file listed in `[prodc].issues`.

### Fixed

- `suggest` no longer stops on a test file that is not UTF-8, and does not read `.venv` or
  `node_modules`.

### Added

- `python -m prodc.cli` runs the CLI.

## [0.5.0] - 2026-11-05

### Breaking

- `lint` now exits 1 on any key prodc does not know, in any need, source, decision or other noun.
  Before, most unknown keys were dropped with no message. The board still loads and writes still
  work; `status` prints the same message. A close match gets a hint: `unknown key 'proof' is
  ignored (did you mean 'proofs'?)`.
- `label:` and `argument:` no longer have their own messages. They are now reported as unknown keys.

### Migrate

1. Run `prodc lint` and read each `unknown key` line.
2. Fix a typo, or delete the key. Its value was never read, so deleting it changes nothing.
3. For `label:`, declare a role with `prodc add role <id> --text "<label>" --file <file>`, then set
   `role: <id>`.
4. For `argument:`, state the warrant as `claim:` on the need, and review it with `prodc attest`.

### Added

- An active `decision` that serves a must-have now passes the lint gate when the need has no
  evidence. A draft or withdrawn decision does not. The need still reads WEAK (#86).
- `suggest` and `suggest --relink` now find `pytest` and `vitest` tests. Set `paths` on the proof
  to change which files are read.

## [0.4.x]

Patch releases on the 0.4 line. Highlights, newest first:

- New proof kind `playwright` (alias `playwright-ct`) for Playwright component and visual tests. The
  locator is `file#test title`; `[mobile] title` pins one project. With a junit report, a test
  that fails in any project is PENDING and the detail names the project. It counts as a `test`
  for `expects` and `suggest` (#112).
- A `glossary:` says what a term means, globally or for one client (`scope: client:acme`). A need
  lists the terms it uses in `terms:`. `lint` errors on a term with no definition for that need,
  and warns when a client meaning differs from the global one. `report` renders the glossary (#72).
- A need has a capture `stage`: `captured`, `triaged` or `committed` (#77). `draft: true` is the
  captured stage, and a need with neither is committed, so existing boards do not change. Only
  committed needs count toward coverage. `status` lists the triaged ones apart. **Behaviour
  change:** `review --promote` now moves a need one stage (captured to triaged, triaged to
  committed). Use `review --promote-all` to commit everything at once.
- `prodc attest` now requires `--verdict` (pass, concerns or fail), so a review with no conclusion
  cannot be recorded. `[lint].ai_attestation = "counts"` stops warning that an AI review is not a
  human one, for boards where a model is the reviewer. `lint` groups the unattested-proof warnings
  into one line; `--all-warnings` or `--strict` lists each need (#87).
- `max_clicks` is now checked against the view links when a proof adapter has the same name as the
  view client (`web` and `web:/pack`). Before, the outcome was read as a test locator and the
  check was skipped. A `max_clicks` the links measured no longer warns "has no proof" (#108).
- prodc reads issue files (#36). Set `[prodc].issues = ["docs/issues/*.md"]`. An issue's front
  matter `needs:` ties it to the needs it serves, and `sources:` points at the same issue in
  another system. `lint` flags an unknown need (error), an issue that serves no need, a closed
  issue on an unproven need, an open issue whose needs are all delivered, and a broken source.
  `prodc issues` lists them and `prodc show` lists the issues serving a need.
- The agent playbook (`prodc agent`) and `docs/model.md` now say where things go: a product need,
  a principle, or an issue in your own tracker for engineering work and bugs. They also say a
  navigation journey is a `path:` on the task's need, and that an entry, deep links included, is a
  view some need's `path.start` names (#111).
- A need can declare `expects: test|eval|observed|accept|prototype`, the proof kind it waits for
  (#78). A HOLE then reads `awaiting an eval`, `suggest` looks only in that kind of inventory (an
  eval or observed inventory is offered whole), and `lint` warns when the wired proofs are another
  kind. Set it with `prodc set N-1 expects=eval`.
- `suggest` reads the keys of `external` (observable outcome) and `evalgate` proofs. Name one with
  `--kind` and it offers every recorded key, ranked by text score and not cut by `--min-score`,
  because an outcome or metric name rarely shares words with a need (#75, #76).
- `report` takes `--goal ID` and `--only-must` to scope the needs, and `--out` as another name for
  `--output` (#64).
- `report --format csv`, `--format jira` and `--format confluence` render the board for product
  tooling: one CSV row per need, Jira wiki markup, and Confluence storage format (#65).
- A source can carry an `anchor`, an exact place inside its locator (`capture --anchor L120-L134`).
  For a local file with a quote, `status` and `lint` warn when the quote is no longer inside those
  lines (#57). `show` prints `locator#anchor`.
- The markdown `report` names the concrete source behind a need: `secondary (ticket)`, `(merge
  request)`, `(message)`, `(email)` or `(post)`, read from the source locator. It also shows an
  identifier such as `safety-analyst` as `Safety analyst` in headings and the roster (#68).
- `dupes` and variant suggestions skip pairs that cannot reach the threshold (prefix filter), so
  they are about 4x faster on 3000 needs. The results are the same (#62).
- `lint` warns when a client's view inventory has links but no entry view (#110). The `must-have
  is an opinion` error now says whether the need has no source or only an assumption, and how to
  fix it (#86).
- `report --format md` takes `--title`, `--hide-empty` and `--only-open` (#67). `--only-open`
  prints just the Open questions brief, for a pre-meeting agenda.
- `orphan_ok` is removed from the view inventory, and a file that still has it fails to load.
  A view nobody links to is an orphan unless a need's `path.start` names it: an entry point is
  derived from a need, not flagged on the view. The `unreachable from an entry view` line uses the
  same entries.
- A page nested under another page no longer counts as 0 clicks away. Only a section, dialog or
  tab is free inside its parent, so a path between sibling pages needs a link (#109).
- View links are checked. `lint` warns on an orphan view and fails on a link to a view that is
  not in the inventory (#105, #106). `status` and `lint` warn when a need's `path` has no route
  from start to outcome, or needs more clicks than `max_clicks` (#105, #108). `prodc views`
  shows inbound and outbound links per view (#107), and `[lint].unjustified_views` makes an
  unjustified view a warning or an error (#108).
- A view link can carry a `why`, and `prodc views --graph mermaid` draws the links as a
  flowchart per client (#104). `[lint].link_without_why` flags a link with no reason.
- `status` now shows every per-need warning that `lint` shows (duplicates, unlinked recurrence,
  stale evidence, `who` variants, importance, draft age, declared-only proofs). Both commands
  call one function, so the two cannot drift (#81). `lint` still adds the warnings that are not
  about one need: principles, decisions, tags and flow steps.
- `prodc views` lists each client's views as a tree, with the needs that point at each view and
  their state (#102). It flags views no need justifies and views with no `kind`; `lint --strict`
  fails on an untyped view.
- With a `views` adapter configured, a need's `path.start` and `path.outcome` must be views:
  `status` and `lint` warn on one that is not (#101). Write `client:id`; a bare id means the
  only client.
- A `views` proof kind reads the view inventory files your clients generate (#100). A proof
  `views:web:/roast/sessions/$planId` is DELIVERED (declared) when the view exists, and
  views no need points at show up in `prodc orphans`.
- `prodc lint` warns when a must-have is DELIVERED only by declared proofs (`files`, `accept`,
  `prototype`, `citation`), so `lint --strict` fails until it has one results-backed proof (#103).
- `prodc outcome <id> --not-landed` records that a green need did not move its goal (#97).
  The need stays DELIVERED and in coverage, but its confidence becomes weak and its goal no
  longer counts it.
- A DELIVERED need now shows a confidence: weak, medium or strong (#97). It is derived from
  recorded facts only: a `fail` verdict, a declared proof or an opinion make it weak; a human
  `pass` on a primary source with a results-backed proof makes it strong. `show` says which
  rule matched. A flow takes the lowest confidence of its steps.
- A need can carry a `path:` (start, outcome, `max_clicks`, and the `proof` test that
  counts the clicks). `lint` warns on a click budget with no proof, `show` prints the path,
  and `report` lists them in a Paths section (#99).
- `attest`, `capture`, `set` and the other in-place writes now change only the keys they
  edit. Quoting, folded `>` quotes, list indentation and comments inside the edited need
  stay as written (#98).
- A 0.3 `label:` (or `argument:`) no longer blocks every command. It is ignored with a
  notice that shows the role YAML to write, `lint` exits 1 on it, and writes such as
  `prodc add role` work again (#96). A file can set `role:` once for all its needs.
- **Decisions wait on research** (#93) — `awaits: [Q-1@yes, Q-2]` on a decision names the
  research needs (`product: false`, a `claim`) it waits on. Readiness is derived from their
  proofs: `show`/`status` mark the decision BLOCKED or READY, and `lint` warns on a decision
  committed before its research settled, decided against its own result, or waiting on a
  withdrawn or product need. No new noun; `NeedState` is unchanged.
- **The nouns, audited** (#92) — 8 nouns (Need, Source, Proof + Goal, Release, Role,
  Principle, Decision), each with the reason it is not a field; see docs/model.md.
- **vitest proof adapter** (#91) — `file.test.ts#title`, upgraded by a junit report, so a
  failing frontend guard makes its principle VIOLATED.
- **`[prodc].files`** (#95) — the neutral key for the prodc files (`needs` stays as an alias);
  `prodc show D-1` prints a decision.
- **Flow step vocabulary** — `[flows].steps`; an undeclared step is a load error, and lint
  grades each journey (never reaches the terminal step, out of order, mixed).
- **Tags** (#80) — `tags:` on a need, `status --tag X`, and tag hygiene lint.
- **Enforced principles** (#89) and **principle scope** (#88) — guard `proofs` +
  `implemented_in` give a principle a state (ENFORCED / STATED / VIOLATED / BROKEN); `scope`
  puts product, design, visual and engineering principles on one board.
- **Goals absorb initiatives** (#80) — `description`, `target`, and a derived group state.

### Changed (breaking for the Python API)

- `Need.children` is `tuple[Child, ...]` (`Child(id, step)`), not `tuple[str, ...]` (#90). YAML
  is unaffected: a bare id still loads.

## [0.4.0] - 2026-10-16

The OST is whole, and the board cannot lie.

0.4 finishes the Opportunity-Solution Tree — a need now carries the solution
chosen for it and the vision that solution rests on — and closes the gaps that
let a board read greener than the evidence warranted.

### Added

- **Product principles** (`principles:`) — the product vision as a cited, rippling noun.
  `add principle`, `revise principle`, and `add principle --from-need` (promote a need,
  keeping its text and sources). An `out_of_scope` withdrawal must cite the principle it
  rests on (`withdraw --principle`); revising a principle re-opens decisions taken under it.
- **Decision noun** (`decisions:`) — the solution chosen for a need over the alternatives
  rejected (OST, not an ADR). `add decision --needs … --alternative … --consequences …
  --principles …`; `withdraw decision <id>` / `reinstate decision <id>` supersede and restore.
  Lint flags an orphan decision (built on no need) and a stale one (its principle moved under it).
- **`contradicts`** — a symmetric need↔need edge for two needs in tension; `lint` flags a pair
  left both-live, because the vision has to decide between them.
- **`prodc guide`** — a short human CLI onboarding guide, sibling to `prodc agent`;
  `--write PATH` drops it into the repo.
- **`report` renders Principles and Decisions** — both the markdown document and the
  interactive HTML viewer now carry the two new sections.
- **`status` shows unresolved contradictions** on the text board.

### Changed (breaking)

- **`Need.label` removed** (#52). Express it with a declared `role` + `client`:
  John@Sincerely playing the `owner` role, not a free-text label. A board still carrying
  `label:` fails to load with a message naming the replacement.
  *Migration:* declare the role in `roles:`, set `role:` and `client:` on the need, drop `label:`.
- **The GSN `argument` graph is cut.** Its job is absorbed by `claim` + `proofs` +
  attestation: state the warrant as `need.claim`, prove it with proofs, review it with
  `prodc attest`. A board carrying an `argument:` key fails to load with that guidance.
  *Migration:* move each argument node's warrant onto the need's `claim`; delete `argument:`.
- **Attestation `verdict` is an enum** — `pass` / `concerns` / `fail`. Only `pass` clears a
  need; `concerns`, `fail`, or no verdict at all now warns, for a human and an AI reviewer
  alike. This was the false-green bug: a recorded-but-not-passing review read as settled.
  *Migration:* an attestation with no `verdict:` now warns — add `verdict: pass` where the
  review did pass.
- **A `duplicate` withdrawal must name its original** — `Withdrawal.of` is required when
  `kind: duplicate` (`withdraw --of <id>`), so a duplicate always points at what it duplicates.

> The `argument:` and `label:` load errors are tombstones for the 0.4 cutover; they are
> scheduled for removal in 0.5.

## [0.3.x]

The 0.3 line turned prodc from a need-and-proof tracker into a full product-and-research
board. Highlights, newest first:

- **`prodc report`** — the board as a shareable document: a readable markdown file, or a
  single self-contained, interactive, read-only HTML viewer (filter, search, regroup,
  print to PDF) with no external assets.
- **Research boards, unified** — no profile fork. An `answer` axis (settled questions with a
  direction, including a settled-NO), a `need:` question→question DAG, and `evalgate` /
  `citation` proof adapters, gated by claim-aware lint so one board holds product bets and
  research questions the same way.
- **Lifecycle callbacks** — `prodc sync` fires a configured command for each need whose state
  changed since the last sync, ledger-tracked and retried on failure.
- **Portfolio** — roll many boards into one scoreboard with a totals footer; discover boards
  under a directory.
- **Drafts and review** — staged needs (`draft: true`), `prodc review` to triage them, an
  age gate, and portfolio exclusion.
- **Withdrawal kinds** — `wont_do` / `out_of_scope` / `duplicate` on a decision-against a need.
- **Source kinds** — the academic `primary` / `secondary` / `assumption` ladder; a need with
  no primary or secondary source is an opinion. Old kind names still load, mapped on.
- **Role noun** — a named function in the product's world; `who` + `client` is an instance of it.
- **Importance rubric**, **free-form `description`**, and the **cli/ package split**.

## [0.1.0]

Initial release.
