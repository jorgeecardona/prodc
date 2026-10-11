"""Shared CLI helpers with no dependency on the renderers or command handlers.

The leaf of the ``prodc.cli`` package: loading the model, the git stamp, the exit-code gate,
the edit diff printer, the meeting-agenda filter, and the portfolio row — all used by several
commands (and, for a couple, by both a text renderer and a JSON serialiser), kept here so
nothing above has to import sideways.
"""

from __future__ import annotations

import argparse
import json
import os
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


@dataclass(frozen=True)
class PortfolioTotals:
    """The aggregate across every board in a portfolio — a footer, not a merged board.

    Error rows are excluded (a board that would not load contributes no counts). ``coverage`` is
    the pooled ``delivered / total``, which is not the mean of the per-board percentages.
    """

    boards: int  # how many boards loaded cleanly and are summed here
    delivered: int
    total: int
    must_hole: int
    broken: int
    coverage: float


def portfolio_totals(rows: list[RepoRow]) -> PortfolioTotals:
    """Sum the clean rows into a :class:`PortfolioTotals` footer."""
    ok = [r for r in rows if r.error is None]
    delivered = sum(r.delivered for r in ok)
    total = sum(r.total for r in ok)
    return PortfolioTotals(
        boards=len(ok),
        delivered=delivered,
        total=total,
        must_hole=sum(r.must_hole for r in ok),
        broken=sum(r.broken for r in ok),
        coverage=round(delivered / total, 4) if total else 0.0,
    )


# Directory names never descended into during board discovery: VCS, virtualenvs, dependency and
# build trees. Any name starting with "." is pruned too (handled in the walk), so a vendored or
# example prodc.toml buried in one of these is never mistaken for a board.
_PRUNE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "site-packages",
        "vendor",
    }
)


def discover_configs(root: Path, *, max_depth: int = 4) -> list[Path]:
    """Every ``prodc.toml`` under ``root``, for the portfolio roll-up — bounded so it can't run away.

    A plain recursive scan is a footgun: it descends into ``.git``/``node_modules``/build trees and
    picks up vendored or example configs. So this prunes those (and every ``.``-prefixed dir) and
    caps the descent at ``max_depth`` directories below ``root``. Returns sorted, de-duplicated
    paths; a board is the directory that holds the ``prodc.toml``.
    """
    root = root.resolve()
    found: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        if "prodc.toml" in filenames:
            found.add(Path(dirpath) / "prodc.toml")
        depth = len(Path(dirpath).relative_to(root).parts)
        # Prune in place so os.walk never descends into the skipped dirs, then stop at the depth cap.
        dirnames[:] = (
            []
            if depth >= max_depth
            else [d for d in dirnames if d not in _PRUNE_DIRS and not d.startswith(".")]
        )
    return sorted(found)
