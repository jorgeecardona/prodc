# prodc

prodc is about sharing product work across a team. Understanding what users need, and whether you've delivered it, tends to get locked inside one role and one set of tools. But AI assistants now help everyone read and shape software, so everyone can take part in the product thinking too. prodc gives that work a home inside the repo, next to the code it's about.

The work lives as plain files: you note what a person needs, where the need came from, and the test that proves it's done. They get reviewed in pull requests like anything else, so when someone asks "is this feature done?", the answer is read from the repo, not remembered from the last standup.

prodc only records that structure and checks it holds together. It does not call a model or ping a tracker
on its own. It reads your files and your tests and shows you the gaps. (A `gitlab` source adapter can
check a ticket exists, read-only, and a `command` hook runs only the script you configure.)

## Two rules

Both rules are about evidence.

The first: **a need with no evidence is just an opinion.** When you write down that a user wants something,
record the source: a quote from an interview, a ticket, an email. A need with nothing behind it still
loads, but prodc flags it as an opinion, because no one outside the team has said so.

The second: **"done" is a claim your tests have to back.** You do not mark a need delivered by hand. You
attach a *proof* (a locator that points into your actual test suite). `prodc status` then resolves those
locators and reports each need as DELIVERED, PENDING, a HOLE (an honest gap, no proof yet), or BROKEN
(a proof that points at nothing). The state comes from the repo; it cannot drift away from reality the
way a standup update does.

## Install

```bash
pip install prodc
prodc status
```

Run it against a project that already has needs defined. To start from nothing, the Quickstart covers
the three files you need.

## Where to go next

| Go to | For |
|---|---|
| [Quickstart](quickstart.md) | a working board in 60 seconds |
| [Commands](commands.md) | every verb and flag |
| [Model](model.md) | the nouns, the Need and Source fields, the two ladders |
| [Config](config.md) | every `prodc.toml` section |
| [Lifecycle](lifecycle.md) | how a need moves through its states as evidence arrives |
| [Grounding (Torres)](grounding-torres.md) | how prodc maps onto *Continuous Discovery Habits* |
