# prodc

Product management as code: needs, evidence and proofs live in the repo, so status is read, not asked.

Two rules:

1. **No source = opinion.** A need with no evidence is flagged.
2. **Status comes from the repo, not a standup.** A proof is a locator into your tests; `prodc status` reports what is delivered, pending, a hole, or broken.

```bash
pip install prodc
prodc status
```

| Go to | For |
|---|---|
| [Quickstart](quickstart.md) | a working board in 60 seconds |
| [Commands](commands.md) | every verb and flag |
| [Model](model.md) | the nouns, the Need and Source fields, the two ladders |
| [Config](config.md) | every `prodc.toml` section |
