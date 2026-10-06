# AGENTS.md

Guidance for AI coding agents working in this repo. Humans: read README.md and CHANGELOG.md.

## Overview

prodc: Product management as code: roles, flows, and features traced to evidence.

## Build

- `make setup` once after cloning: syncs dependencies (`uv sync`) and installs the tracked git hooks (`make install-hooks`). Toolchain (moon, uv) is pinned in `.prototools`; `proto install` brings it up.

## Test

- `make test` runs the suite.
- `make check` runs lint + typecheck + test (the same stage CI runs via `moon run :ci`).
- Everything in `make check` must pass before you commit.

## Style

- Format and autofix: `make format` (ruff, line length 100).
- Lint: `make lint`. Types: `make typecheck` (pyright strict on `src/`).
- Prefer frozen dataclasses and explicit types. Keep the public API typed (`py.typed`).
- Dependencies: pyyaml only. An in-place write-back (`set`/`capture`/`accept`/`attest`) splices
  only the changed need's block back into the original text, so the file header and other needs
  keep their comments; only the edited need's block is reflowed, and an unrecognised file shape
  falls back to a full PyYAML re-dump. Keep each edit to one file, always show the diff, and dump
  with `sort_keys=False` to preserve key order.

## Gotchas

- Version lives only in `pyproject.toml`. The pre-commit hook auto-bumps it when `src/` changes. Do not edit versions by hand elsewhere.
- Record follow-ups in `docs/issues/`, not as scattered TODO comments.
