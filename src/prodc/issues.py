"""Issues: the engineering work behind needs, read from a ``docs/issues/`` folder (#36).

prodc holds product needs and principles. Engineering work is an issue, kept as a markdown file
with YAML front matter (the format cabildo's issue tools write and check). prodc reads those
files and joins them to the board through two front matter keys:

- ``needs``: the need ids the issue serves. An issue with none has no want behind it.
- ``sources``: pointers into other systems, ``<source adapter>:<payload>`` (``gitlab:#123``).

prodc never writes an issue and never computes its state: ``status`` is whatever the file says.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from .adapters import SourceAdapter
from .model import Issue, NeedResult, NeedState


@dataclass(frozen=True)
class IssueFolder:
    """The issues read from the configured globs, plus the files that were not issues."""

    issues: tuple[Issue, ...] = ()
    skipped: tuple[str, ...] = ()  # paths with no front matter: not readable as issues


def _strings(value: object) -> tuple[str, ...]:
    """A front matter list of strings; a bare string is a list of one; anything else is empty."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        items = cast("list[object]", value)
        return tuple(str(v) for v in items if isinstance(v, str | int | float))
    return ()


def _opt(value: object) -> str | None:
    return str(value) if isinstance(value, str | int | float) and str(value) else None


def parse_issue(path: Path, root: Path) -> Issue | None:
    """Read one issue file, or None when it has no readable front matter."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    head, sep, _ = text[3:].partition("\n---")
    if not sep:
        return None
    try:
        data: object = yaml.safe_load(head)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    fm = {str(k): v for k, v in cast("dict[object, object]", data).items()}
    return Issue(
        id=path.stem,
        title=_opt(fm.get("title")) or path.stem,
        status=_opt(fm.get("status")) or "open",
        needs=_strings(fm.get("needs")),
        sources=_strings(fm.get("sources")),
        area=_opt(fm.get("area")),
        fixed_in=_opt(fm.get("fixed_in")),
        path=str(path.relative_to(root)),
    )


def read_issues(root: Path, globs: list[str]) -> IssueFolder:
    """Every issue matched by ``globs`` (relative to ``root``), each file once, sorted by name.

    ``README.md`` and non-markdown files are not issues. A markdown file with no front matter is
    listed in ``skipped``, not read: run ``cabildo issues check`` to fix it.
    """
    seen: set[Path] = set()
    issues: list[Issue] = []
    skipped: list[str] = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path in seen or path.suffix != ".md" or path.name.lower() == "readme.md":
                continue
            seen.add(path)
            issue = parse_issue(path, root)
            if issue is None:
                skipped.append(str(path.relative_to(root)))
            else:
                issues.append(issue)
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
