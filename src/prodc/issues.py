"""Issues: the engineering work behind needs, joined to the board (#36).

prodc holds product needs and principles. Engineering work is an issue, kept as a markdown file
with front matter in a ``docs/issues/`` register. :mod:`prodc.issue_store` reads and writes those
files; this module loads them for the board and lints them against it through two keys:

- ``needs``: the need ids the issue serves. An issue with none has no want behind it.
- ``sources``: pointers into other systems, ``<source adapter>:<payload>`` (``gitlab:#123``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import issue_store as store
from .adapters import SourceAdapter
from .model import Issue, NeedResult, NeedState


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
    - warning: an issue serves no need; a closed issue whose need is not DELIVERED
      ("closed but unproven"); an open issue whose every need is DELIVERED ("proven but open");
      a ``sources`` pointer that its source adapter says does not exist.

    A withdrawn need is left out of the two state checks: nothing is owed on it any more.
    """
    by_id = {r.need.id: r for r in results}
    errors: list[str] = []
    warnings: list[tuple[str, str]] = []
    for issue in issues:
        if not issue.needs:
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
