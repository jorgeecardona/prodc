# prodc

Product management as code: needs, evidence and proofs live in the repo, so status is read, not asked.

Two rules:

1. **No source = opinion.** A need with no evidence is flagged.
2. **Status comes from the repo, not a standup.** A proof is a locator into your tests; `prodc status` reports DELIVERED / PENDING / HOLE / BROKEN.

## Install

```bash
pip install prodc          # or: uv add prodc
uv sync && make check      # contributors: deps + lint + typecheck + test
```

## Use

```bash
prodc status
```

```text
prodc status — quickstart
gaps: 2 HOLE  ·  1 opinion    coverage 1/3 (33%)
     id        GROUNDS         need                                        WARRANT

jordan (design partner)    1 DELIVERED  ·  2 HOLE
  !! N-1       DELIVERED* 1/1   see which orders are past due at a glance   interview:Jordan
     N-2       HOLE             export the day's delivery run sheet         artifact
     N-3       HOLE             implement a settings page                   opinion
       ⚠ text may be a solution in disguise (starts with 'implement')
```

GROUNDS = does a test prove it. WARRANT = did a user ask for it. The gap between them is the point.

## Docs

- [Quickstart](docs/quickstart.md) — 60 seconds to a board
- [Commands](docs/commands.md) — every verb, one line each
- [Model](docs/model.md) — the nouns and the Need fields

`docs/issues/` holds follow-ups. `AGENTS.md` is for coding agents.
