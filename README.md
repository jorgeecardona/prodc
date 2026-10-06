# prodc

Product management as code: roles, flows, and features, each traced to the evidence behind it and the test that proves it. The aim is to make product work something a whole team can share — kept in the repo, next to the code, read by the tools you already use — rather than a specialty locked in one person's head and one tracker.

prodc records that structure and checks it holds together; it does not call a model or ping a tracker. Two ideas carry it, both about not fooling yourself:

1. **A need with no evidence is an opinion.** Write down who asked for something — an interview, a ticket, an email — or prodc flags it as an opinion, because that is what it is until someone outside the room has asked.
2. **"Done" is a claim your tests back.** You attach a proof (a locator into your test suite), and `prodc status` reports each need as DELIVERED, PENDING, HOLE (an honest gap), or BROKEN. The status is read from the repo, not remembered from a standup.

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
- [Model](docs/model.md) — the nouns (Need, Role, Goal, Release) and the Need fields

`docs/issues/` holds follow-ups. `AGENTS.md` is for coding agents.
