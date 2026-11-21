# CI job

Copy this job into `.gitlab-ci.yml` to run `prodc lint` on every pipeline. It fails the pipeline
on a BROKEN proof or a must-have with no evidence.

## The job

1. Add the job. Pin the prodc version, so a new release cannot change your gate:

   ```yaml
   prodc:
     stage: test
     image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
     needs: [test]
     script:
       - uvx --from prodc==0.11.3 prodc lint
   ```

2. Make your test job write a junit report and keep it as an artifact:

   ```yaml
   test:
     stage: test
     image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
     script:
       - uv run pytest -q --junitxml=reports/junit.xml
     artifacts:
       when: always
       paths: [reports/junit.xml]
       reports:
         junit: reports/junit.xml
   ```

3. Point the proof adapter at that report in `prodc.toml`:

   ```toml
   [prodc]
   files = ["product/needs/*.yaml"]

   [proofs.test]
   kind = "pytest"
   root = "."
   results = "reports/junit.xml"
   ```

`needs: [test]` makes GitLab download the `test` job's artifacts before `prodc` runs. With
`results` set, a pytest proof is DELIVERED only when its test passed in that report. Without
`results`, DELIVERED means the test exists.

## Options

- `prodc lint --strict` also fails on any warning.
- `prodc lint --baseline lint-baseline.txt` shows only the warnings that are not in the file.
  Write the file once with `prodc lint --write-baseline lint-baseline.txt` and commit it.
- Other adapters (`gherkin`, `vitest`, `playwright`) read `results` the same way. See
  [Config](config.md).
