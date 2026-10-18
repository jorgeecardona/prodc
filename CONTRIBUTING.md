# Contributing to prodc

Developer and maintainer notes: toolchain, CI, and the release process. (Package *users* need none of
this — see the [README](README.md) for what prodc does and how to use it.)

## Contributing with an AI agent

Most changes here will be written with a coding agent — that's expected and welcome. To get a good
result from yours:

- **Point it at [`AGENTS.md`](AGENTS.md) first** — the machine-facing contract for this repo: build
  and test commands, the typed-API and style rules, and the repo-specific gotchas. Agents read it
  automatically when started from the repo root.
- **Ship a green `make check`** (lint + typecheck + test). Have the agent run it and fix what it
  finds *before* opening the MR, not leave it for review.
- **Don't let it bypass the hooks.** The patch version auto-bumps on `src/` changes and CI's
  version-guard enforces it; a `--no-verify` commit fails the pipeline.
- **Keep the diff small and typed**, add a `CHANGELOG.md` entry, and don't reformat unrelated files.

## Development & CI

The toolchain is pinned with [proto](https://moonrepo.dev/proto) (`.prototools`: `moon` + `uv`)
and every task is a [moon](https://moonrepo.dev) target running through `uv run`. After cloning:

```
proto install          # installs the pinned moon + uv
make setup              # uv sync + install-hooks
moon run :ci            # lint + typecheck + test + build (one task graph)
moon run :test          # or run a single target
```

CI is a single GitLab job: `proto install` brings up the toolchain, then one `moon run` resolves the
whole graph — there are no per-language jobs or hand-wired stages. (`make` targets still work locally;
they call `uv run` directly and don't need moon.)

## Releasing

The package version in `pyproject.toml` is the single source of truth, and releases are automated:

1. **`pre-commit` auto-bumps** the patch version whenever a commit touches `src/**/*.py` (run
   `make install-hooks` once after cloning). Doc/test/example/config-only commits don't bump. For an
   intentional minor/major release, bump deliberately: `make bump TYPE=minor`.
2. **`version-guard`** (the `moon run :version-guard` task, part of `:ci`) enforces the same rule
   non-bypassably in CI: a push or MR that changes `src/` without a version bump fails the pipeline,
   catching `--no-verify` and unhooked clones.
3. **`:release`** runs on a green `main` pipeline: if the package version isn't on PyPI yet, it
   publishes via OIDC Trusted Publishing. Merging a version bump to `main` releases itself — no
   second pipeline, no tag required.

### One-time setup

**PyPI — OIDC Trusted Publishing** (no API token is stored anywhere). Account → Publishing → add a
*pending* GitLab publisher (or add it to the project after the first manual upload):

| Field | Value |
|-------|-------|
| PyPI Project Name | `prodc` |
| Namespace | `cardona-oss` |
| Project name (repo) | `prodc` |
| Top-level pipeline file | `.gitlab-ci.yml` |
| Environment name | `pypi` |

Releases are automatic on `main` — there is no manual tag or publish step. Pushes and MRs run
lint + typecheck + test + build only.
