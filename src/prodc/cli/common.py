"""Shared CLI helpers with no dependency on the renderers or command handlers.

The leaf of the ``prodc.cli`` package: loading the model, the git stamp, the exit-code gate,
the edit diff printer, the meeting-agenda filter, and the portfolio row — all used by several
commands (and, for a couple, by both a text renderer and a JSON serialiser), kept here so
nothing above has to import sideways.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import Config, ConfigError
from ..loader import LoaderError, load
from ..model import Model, NeedResult, NeedState
from ..status import Summary
from ..writer import Edit


def load_or_report(args: argparse.Namespace) -> tuple[Config, Model] | None:
    """Load config + the whole model, or print the error to stderr and return None."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return None
    try:
        cfg = Config.load(cfg_path)
        return cfg, load(cfg)
    except (ConfigError, LoaderError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return None


def git_rev(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if ref.startswith("ref:"):
        target = root / ".git" / ref[4:].strip()
        try:
            return target.read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return None
    return ref[:7]


def exit_code(args: argparse.Namespace, summary: Summary, orphan_total: int) -> int:
    """Gate: 0 unless a threshold is crossed; HOLE never fails.

    Default fails on any BROKEN; ``--max-dangling N`` tolerates N; ``--min-coverage F``
    fails when delivered/total < F; ``--max-orphans N`` fails above N unclaimed proofs;
    ``--strict`` fails on any opinion.
    """
    if args.max_dangling is not None:
        if summary.broken > args.max_dangling:
            return 1
    elif summary.broken:
        return 1
    if args.min_coverage is not None and summary.coverage < args.min_coverage:
        return 1
    if args.max_orphans is not None and orphan_total > args.max_orphans:
        return 1
    if args.strict and summary.opinion:
        return 1
    return 0


def emit_edit(edit: Edit, dry_run: bool, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"file": edit.path.name, "dry_run": dry_run, "diff": edit.diff}, indent=2))
    else:
        print(f"{'would edit' if dry_run else 'edited'} {edit.path.name}")
        print(edit.diff, end="")
    return 0


def brief_open(results: list[NeedResult]) -> list[NeedResult]:
    """The meeting agenda: needs that are opinions (no evidence) or HOLEs (no proof),
    must-haves first, then by id."""
    open_ = [r for r in results if r.need.is_opinion or r.state is NeedState.HOLE]
    open_.sort(key=lambda r: (not r.need.must, r.need.id))
    return open_


@dataclass(frozen=True)
class RepoRow:
    """One repo's line in the portfolio roll-up."""

    repo: str
    delivered: int
    total: int
    must_hole: int
    broken: int
    coverage: float
    provenance: dict[str, int]
    error: str | None = None
