# prodc

prodc keeps user needs as YAML files in your repo. Each need lists where it came from (its
sources) and the test that proves it is delivered (its proofs).

Everyone on the team reads and edits the same files, and they are reviewed in merge requests like
code. The answer to "is this feature done?" is read from the repo and the test suite.

prodc reads your files and your tests and shows the gaps. It does not call a model or contact a
tracker by itself. A `gitlab` source adapter can check that a ticket exists (read-only), and a
`command` proof runs only the script you configure.

## Two rules

Both rules are about evidence.

1. A need with no evidence is an **opinion**. When you write that a user wants something, record
   the source: a quote from an interview, a ticket, an email. A need with no primary or
   secondary source still loads, and prodc marks it as an opinion.
2. A need is done when a test proves it. You do not set a need to delivered by hand. You attach a
   **proof**: a locator that points into your test suite. `prodc status` resolves the locators
   and computes the state of each need.

The five states:

| State | Means |
|---|---|
| DELIVERED | every proof passes |
| PENDING | the proof exists and is not green yet |
| HOLE | the need has no proof |
| BROKEN | a proof points at nothing; `prodc lint` exits 1 |
| UNRESOLVED | a proof's source could not be read, for example a sibling repo that is not checked out |

## Install

Add prodc as a dev dependency. Your package does not import it.

```bash
uv add --dev prodc
uv run prodc status
```

Without uv, run `pip install prodc` in your dev environment.

Run it in a project that already has needs. To start from nothing, the
[Quickstart](quickstart.md) has the three files you need.

## Where to go next

| Go to | For |
|---|---|
| [Quickstart](quickstart.md) | a working board from three files |
| [Commands](commands.md) | every verb and flag |
| [Model](model.md) | the nouns, the Need and Source fields, the source and attestation kinds |
| [Config](config.md) | every `prodc.toml` section |
| [Lifecycle](lifecycle.md) | how a need moves through its states as evidence arrives |
| [Grounding (Torres)](grounding-torres.md) | how prodc maps onto *Continuous Discovery Habits* |
