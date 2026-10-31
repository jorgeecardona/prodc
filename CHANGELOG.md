# Changelog

All notable changes are documented here. Versioning is [SemVer](https://semver.org/).

## [0.4.x]

Patch releases on the 0.4 line. Highlights, newest first:

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
