# AGENTS.md

Guidance for AI coding agents working in this repo. Humans: read README.md and CHANGELOG.md.

## Overview

prodc is a product-management-as-code tool: roles, flows, and features traced to evidence. Needs live
in YAML under `product/needs/`; each need carries sources, and "done" means a test proof. A need with
no external evidence is an opinion — `primary` sources are real users' own words and are never added
via `prodc add`.

## Build

- `make setup` once after cloning: syncs dependencies (`uv sync`) and installs the tracked git hooks (`make install-hooks`). Toolchain (moon, uv) is pinned in `.prototools`; `proto install` brings it up.

## Test

- `make test` runs the suite.
- `make check` runs lint + typecheck + test. Everything in it must pass before you commit.
  `moon run :ci` runs more (build, docs, version-guard) — use it before pushing.

## Style

- Format and autofix: `make format` (ruff, line length 100).
- Lint: `make lint` (ruff, `select = ["E","F","W","I","B","UP","SIM","RUF"]`). Types: `make typecheck` (pyright strict on `src/`, `tests/`, `examples/`).
- Python 3.12+ only.
- Prefer frozen dataclasses and explicit types. Keep the public API typed (`py.typed`).
- Dependencies: pyyaml only. An in-place write-back (`set`/`capture`/`accept`/`attest`) splices
  only the changed need's block back into the original text, so the file header and other needs
  keep their comments; only the edited need's block is reflowed, and an unrecognised file shape
  falls back to a full PyYAML re-dump. Keep each edit to one file, always show the diff, and dump
  with `sort_keys=False` to preserve key order.

## Gotchas

- The version is the `__version__` literal in `src/prodc/__init__.py`, which hatchling reads so `pyproject.toml` never disagrees. Do not edit it by hand: the pre-commit hook auto-bumps it when anything under `src/` changes, and CI's version-guard enforces that a `src/` change carries a bump.
- Record follow-ups in `docs/issues/`, not as scattered TODO comments.
