"""The story inventory: reading Storybook's index.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc import storybook

FIXTURE = Path(__file__).parent / "fixtures" / "storybook" / "index.json"


def test_reads_the_real_tyko_index() -> None:
    idx = storybook.load(FIXTURE)
    assert idx.version == 5
    assert len(idx.stories) == 9
    s = idx.get("components-codeblock--python")
    assert s is not None
    assert s.title == "Components/CodeBlock"
    assert s.component == "components-codeblock"
    assert s.import_path.endswith("CodeBlock.stories.tsx")
    assert s.testable


def test_components_and_their_stories() -> None:
    idx = storybook.load(FIXTURE)
    assert idx.components() == [
        "components-capabilities",
        "components-changelog",
        "components-codeblock",
    ]
    assert len(idx.of_component("components-codeblock")) == 7


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "index.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_docs_entries_and_bad_entries_are_left_out(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "v": 5,
            "entries": {
                "a--b": {"type": "story", "id": "a--b", "title": "A", "name": "B"},
                "a--docs": {"type": "docs", "id": "a--docs", "title": "A", "name": "Docs"},
                "broken": {"type": "story", "id": 3},
            },
        },
    )
    idx = storybook.load(p)
    assert [s.id for s in idx.stories] == ["a--b"]
    assert idx.stories[0].export_name is None
    assert not idx.stories[0].testable


def test_missing_file_says_to_build(tmp_path: Path) -> None:
    with pytest.raises(storybook.StoryIndexError, match="storybook build"):
        storybook.load(tmp_path / "index.json")


def test_empty_file_is_an_error_not_a_crash(tmp_path: Path) -> None:
    p = tmp_path / "index.json"
    p.write_text("", encoding="utf-8")
    with pytest.raises(storybook.StoryIndexError, match="not readable JSON"):
        storybook.load(p)


def test_unknown_version_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, {"v": 99, "entries": {}})
    with pytest.raises(storybook.StoryIndexError, match="v=99 is not supported"):
        storybook.load(p)


def test_no_entries_is_refused(tmp_path: Path) -> None:
    with pytest.raises(storybook.StoryIndexError, match="no 'entries'"):
        storybook.load(_write(tmp_path, {"v": 5}))
