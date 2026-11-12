"""The store's front matter reader agrees with ``yaml.safe_load`` on every value it writes."""

from __future__ import annotations

import pathlib
from typing import cast

import pytest
import yaml

from prodc import issue_store as store

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTER = sorted(p for p in (ROOT / "docs" / "issues").glob("*.md") if p.name != "README.md")

TRICKY = [
    'say "hi"',
    "back\\slash",
    'both \\" mixed',
    "key: value",
    "a # not a comment",
    "yes",
    "No",
    "on",
    "null",
    "~",
    "007",
    "42",
    "1.5",
    "0x1F",
    "1_000",
    ".inf",
    "- leading dash",
    "[not a list]",
    "{not: a map}",
    "'single'",
    "it's fine",
    "@handle",
    "*star",
    "trailing ",
    "tab\there",
    "plain words",
]


def _norm(value: object) -> str | tuple[str, ...] | None:
    """A ``yaml.safe_load`` value as the store would hold it: strings, tuples of strings, None."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return tuple(str(v) for v in cast("list[object]", value))
    return str(value)


def _both(text: str, path: pathlib.Path) -> tuple[dict[str, object], dict[str, object]]:
    front, _ = store._split_front(text, path)  # pyright: ignore[reportPrivateUsage]
    ours = store._parse_front(front, path)  # pyright: ignore[reportPrivateUsage]
    theirs = cast("dict[str, object]", yaml.safe_load(front))
    return (
        {k: (None if v == "" else v) for k, v in ours.items()},
        {k: _norm(v) for k, v in theirs.items()},
    )


@pytest.mark.parametrize("path", REGISTER, ids=lambda p: p.name)
def test_every_register_file_reads_the_same_in_yaml(path: pathlib.Path) -> None:
    ours, theirs = _both(path.read_text(encoding="utf-8"), path)
    assert ours == theirs


@pytest.mark.parametrize("value", TRICKY)
def test_a_rendered_tricky_value_reads_back_the_same_in_both(
    tmp_path: pathlib.Path, value: str
) -> None:
    issue = store.Issue(
        path=tmp_path / "03-08-2026-x.md",
        title=value,
        status=store.Status.IN_PROGRESS,
        area=value,
        filed="2026-08-03",
        owner=value,
        blocked_by=(value, "other"),
        fixed_in=value,
        extra={"note": value, "tags": (value, "plain")},
    )
    text = store.render(issue)
    ours, theirs = _both(text, issue.path)
    assert ours == theirs
    parsed = store.parse(text, issue.path)
    assert (parsed.title, parsed.area, parsed.owner, parsed.fixed_in) == (value,) * 4
    assert parsed.extra["note"] == value
    assert parsed.blocked_by == (value, "other")
    raw = cast("dict[str, object]", yaml.safe_load(store._split_front(text, issue.path)[0]))  # pyright: ignore[reportPrivateUsage]
    assert raw["title"] == value  # a string in YAML too, not a bool or an int
