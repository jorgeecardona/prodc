"""Issues: the engineering work behind needs, joined to the board (#36).

prodc holds product needs and principles. Engineering work is an issue, kept as a markdown file
with front matter in a ``docs/issues/`` register. :mod:`prodc.issue_store` reads and writes those
files; this module loads them for the board and lints them against it through two keys:

- ``needs``: the need ids the issue serves. An issue with none has no want behind it.
- ``sources``: pointers into other systems, ``<source adapter>:<payload>`` (``gitlab:#123``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import issue_store as store
from .adapters import SourceAdapter
from .board import warrant
from .config import Config
from .model import Issue, Model, Need, NeedResult, NeedState, Release, board_needs
from .status import current_release, now_ids, rank, recurrence, resolve


@dataclass(frozen=True)
class IssueFolder:
    """The issues that loaded, plus one message per file that did not."""

    issues: tuple[Issue, ...] = ()
    skipped: tuple[str, ...] = ()  # "<file>: <why>", for files the store could not read


def read_issues(root: Path, globs: list[str]) -> IssueFolder:
    """Every issue matched by ``globs`` (relative to ``root``), each file once, sorted by name.

    With no globs, the register is the one :func:`prodc.issue_store.find_folder` finds from
    ``root``; with none found, the result is empty. ``README.md`` and non-markdown files are not
    issues. A file the store cannot parse is listed in ``skipped`` with the reason.
    """
    if not globs:
        folder = store.find_folder(root)
        if folder is None:
            return IssueFolder()
        found, problems = store.load_all(folder)
        return IssueFolder(found, tuple(str(p) for p in problems))
    seen: set[Path] = set()
    configs: dict[Path, store.Config] = {}
    issues: list[Issue] = []
    skipped: list[str] = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path in seen or path.suffix != ".md" or path.name.lower() == "readme.md":
                continue
            seen.add(path)
            try:
                if path.parent not in configs:
                    configs[path.parent] = store.load_config(path.parent)
                issues.append(store.load(path, configs[path.parent]))
            except (store.IssueFormatError, OSError) as exc:
                skipped.append(str(exc) if path.name in str(exc) else f"{path.name}: {exc}")
    return IssueFolder(tuple(issues), tuple(skipped))


def issue_findings(
    issues: tuple[Issue, ...],
    results: list[NeedResult],
    source_adapters: dict[str, SourceAdapter],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Lint an issue list against the board: ``(errors, warnings keyed by issue id)`` (#36).

    - error: ``needs`` names a need that does not exist.
    - warning: an open issue serves no need; a closed issue whose need is not DELIVERED
      ("closed but unproven"); an open issue whose every need is DELIVERED ("proven but open");
      a ``sources`` pointer that its source adapter says does not exist.

    A withdrawn need is left out of the two state checks: nothing is owed on it any more.
    """
    by_id = {r.need.id: r for r in results}
    errors: list[str] = []
    warnings: list[tuple[str, str]] = []
    for issue in issues:
        if not issue.needs and issue.open:
            warnings.append(
                (
                    issue.id,
                    "issue serves no need: add needs: [...], or question why it exists (#36)",
                )
            )
        known = [by_id[n] for n in issue.needs if n in by_id]
        for n in issue.needs:
            if n not in by_id:
                errors.append(f"{issue.id}: needs names '{n}', which is not a need")
        live = [r for r in known if not r.need.is_withdrawn]
        if issue.is_closed:
            for r in live:
                if r.state is not NeedState.DELIVERED:
                    warnings.append(
                        (
                            issue.id,
                            f"closed, but {r.need.id} is {r.state.value.upper()}: closed but "
                            "unproven (#36)",
                        )
                    )
        elif live and all(r.state is NeedState.DELIVERED for r in live):
            warnings.append(
                (
                    issue.id,
                    f"open, but every need it serves is DELIVERED ({', '.join(r.need.id for r in live)}): "
                    "proven but open (#36)",
                )
            )
        for src in issue.sources:
            name, sep, payload = src.partition(":")
            adapter = source_adapters.get(name)
            if sep and adapter is not None:
                res = adapter.resolve(payload)
                if not res.ok:
                    warnings.append((issue.id, f"BROKEN source '{src}' ({res.detail})"))
    return errors, warnings


def ready_by_need(root: Path, *, owner: str | None = None) -> dict[str, tuple[Issue, ...]]:
    """The ready issues of the register at or above ``root``, keyed by each need they cite.

    Ready is :func:`prodc.issue_store.board` ``ready``, in the store's rank order. With ``owner``,
    an issue that ``owner`` holds counts as ready too, when nothing blocks it. Empty when there
    is no register.
    """
    folder = store.find_folder(root)
    if folder is None:
        return {}
    out: dict[str, list[Issue]] = {}
    for issue in _ready(folder, owner):
        for need in issue.needs:
            out.setdefault(need, []).append(issue)
    return {k: tuple(v) for k, v in out.items()}


def _ready(folder: Path, owner: str | None) -> tuple[Issue, ...]:
    """Ready issues in store rank order; with ``owner``, unowned or held by ``owner``."""
    config = store.load_config(folder)
    b = store.board(folder, config, owner=owner)
    if owner is None:
        return b.ready
    open_slugs = {i.slug for i in store.load_all(folder, config)[0] if i.open}
    mine = [
        i
        for i in b.mine
        if i.status is not store.Status.BLOCKED and not any(s in open_slugs for s in i.blocked_by)
    ]
    return tuple(sorted((*b.ready, *mine), key=config.rank_key))


class SkipReason(StrEnum):
    """Why :func:`next_issues` has no pick."""

    NO_BOARD = "no-board"  # no needs on the board (no prodc.toml, or every need draft/withdrawn)
    NO_REGISTER = "no-register"  # no docs/issues/ folder
    NO_RELEASES = "no-releases"  # no ``releases:`` declared, so there is no "now"
    ALL_DELIVERED = "all-delivered"  # every release is DELIVERED
    NO_LINKED_ISSUE = "no-linked-issue"  # no ready issue cites a need in the now-set


@dataclass(frozen=True)
class Candidate:
    """A ready issue that serves a now-set need, with the reason it is offered."""

    issue: Issue
    need: Need  # the best-ranked now-set need the issue cites
    need_rank: int  # that need's 1-based position in ``prodc plan``
    why: str  # "PD-17 is rank 1 in release R1: must, HOLE, primary:Jorge"


@dataclass(frozen=True)
class Next:
    """What to work on next: the candidates in order, or why there are none."""

    release: Release | None  # the current release; None when skipped before one is found
    candidates: tuple[Candidate, ...] = ()
    needs_without_issue: tuple[Need, ...] = ()  # now-set needs no ready issue cites
    skip: SkipReason | None = None
    open_needs: int = 0  # needs in ``release`` not DELIVERED

    @property
    def pick(self) -> Candidate | None:
        """The first candidate, or None."""
        return self.candidates[0] if self.candidates else None


def next_issues(
    cfg: Config, model: Model, folder: Path | None, *, owner: str | None = None, limit: int = 5
) -> Next:
    """The ready issues to work on next, walked from the top of ``prodc plan``.

    The walk covers only the now-set (:func:`prodc.status.now_ids`) in plan order and never reads
    past the current release. Per need, it takes the ready issues that cite it, in the store's rank
    order. An issue that cites two needs appears once, under its better-ranked need. A need with
    no ready issue goes to ``needs_without_issue`` and the walk continues. With ``owner``, an
    issue is ready when it is unowned or held by ``owner``.

    These are never picked: an issue with no need, an issue whose needs are all off the board
    (drafts, withdrawn), and an issue on a DELIVERED need (a DELIVERED need is not in the
    now-set, so a bug on it with a passing proof waits until its proof breaks).
    """
    needs = board_needs(list(model.needs), include_drafts=False)
    if not needs:
        return Next(None, skip=SkipReason.NO_BOARD)
    if folder is None:
        return Next(None, skip=SkipReason.NO_REGISTER)
    releases = list(model.releases)
    if not releases:
        return Next(None, skip=SkipReason.NO_RELEASES)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    current = current_release(results, releases)
    if current is None:
        return Next(None, skip=SkipReason.ALL_DELIVERED)
    open_needs = sum(
        1
        for r in results
        if r.need.release == current.id
        and r.need.counts_toward_coverage
        and r.state is not NeedState.DELIVERED
    )
    now = now_ids(results, releases)
    counts = {rec.baseline.id: rec.count for rec in recurrence(needs)}
    by_need: dict[str, list[Issue]] = {}
    for issue in _ready(folder, owner):
        for n in issue.needs:
            by_need.setdefault(n, []).append(issue)
    seen: set[str] = set()
    candidates: list[Candidate] = []
    without: list[Need] = []
    for position, r in enumerate(rank(results, counts, now), 1):
        if r.need.id not in now:
            break  # the now-set ranks first: past it is later work
        found = [i for i in by_need.get(r.need.id, []) if i.slug not in seen]
        if not by_need.get(r.need.id):
            without.append(r.need)
        where = (
            f"in release {current.id}"
            if r.need.release == current.id
            else "in the now-set (BROKEN outside the current release)"
        )
        parts = (["must"] if r.need.must else []) + [r.state.value.upper(), warrant(r.need)]
        why = f"{r.need.id} is rank {position} {where}: {', '.join(parts)}"
        for issue in found:
            seen.add(issue.slug)
            candidates.append(Candidate(issue, r.need, position, why))
    return Next(
        current,
        tuple(candidates[:limit]),
        tuple(without),
        None if candidates else SkipReason.NO_LINKED_ISSUE,
        open_needs,
    )
