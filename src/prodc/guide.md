# prodc in 60 seconds

prodc keeps product work in the repo, next to the code: who needs what, why, and the test that proves it is done. Plain YAML files, reviewed in pull requests like code.

Try it now: `prodc status`

## The two rules

- **No evidence means it is an opinion.** A need backed only by your own guess still loads, but prodc marks it an opinion until a real user has said something. Example: "users want dark mode" with nobody quoted is an opinion.
- **"Done" is a test, not a claim.** You do not mark a need done; you attach a proof that points into the real test suite. `prodc status` reads DELIVERED, HOLE, or BROKEN from it. Example: `proofs: ["pytest:tests/test_checkout.py::test_pays"]`.

## Your first board

Three files make a board.

`prodc.toml`:

```toml
[prodc]
needs = ["needs/*.yaml"]
```

`needs/needs.yaml`:

```yaml
needs:
  - id: N-1
    text: a buyer can pay for a cart
    who: Dana
    sources:
      - kind: primary
        who: Dana
        quote: I could not check out on mobile
    proofs: ["pytest:tests/test_checkout.py::test_pays"]
```

Then run `prodc status`. You get one board line per need, with its state and coverage.

## Read the board

| Command | Shows |
|---|---|
| `prodc status` | the whole board and coverage |
| `prodc show <id>` | one need as a citable answer |
| `prodc plan` | the backlog, ranked |
| `prodc brief <client>` | what to ask a client before a call |

## Record a need

```
prodc add need N-2 --text "a buyer can save a cart" --who you --kind assumption --file needs/needs.yaml
```

Warning: never record a `primary` source you invented. `primary` means a real user actually said it. Your own reasoning is `assumption`.

## Prove a need

A need moves HOLE, then PENDING, then DELIVERED as its proof comes true. For a HOLE, let prodc find the test:

```
prodc suggest N-1 --apply
```

## Gate it in CI

```
prodc lint --strict
```

Exit codes are the contract: 0 is clean, 1 is a gate failed (a broken proof or a must-have opinion), 2 is a usage or config error.

## Stuck? A gap is a valid answer

A HOLE (no proof yet) or an opinion (no evidence yet) is honest output, not a failure. Leave it visible. Never attach a fake proof to turn a row green.

## Cheat sheet

| To | Run |
|---|---|
| see the board | `prodc status` |
| read one need | `prodc show <id>` |
| rank the backlog | `prodc plan` |
| prep a client call | `prodc brief <client>` |
| add a need | `prodc add need <id> --text "..." --who you --kind assumption --file <f>` |
| attach evidence | `prodc capture <id> --kind primary --who <person> --date <ISO> --quote "..."` |
| attach a proof | `prodc suggest <id> --apply` |
| decide against a need | `prodc withdraw <id> --reason "..."` |
| gate in CI | `prodc lint --strict` |

## Going further

- The vision, held as given: `prodc add principle <id> --text "..."`
- How a need gets built (the chosen solution): `prodc add decision <id> --text "..." --needs <ids>`
- Full command list: `docs/commands.md`. The nouns: `docs/model.md`. Config: `docs/config.md`.
- Teaching an AI agent to run prodc for you: `prodc agent`.
