"""The story inventory: the component states a Storybook build lists in its ``index.json``.

prodc never reads stories or app code. ``storybook build`` writes ``storybook-static/index.json``
and prodc reads that file. A story is one component in one state. Its id is Storybook's own
(``components-button--primary``): the part before ``--`` names the component.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SUPPORTED_VERSIONS = frozenset({5})  # index.json ``v`` values this reader understands


class StoryIndexError(Exception):
    """The index file is missing, unreadable, or in a format this reader does not know."""


@dataclass(frozen=True)
class Story:
    """One component in one state, as listed in ``index.json``."""

    id: str  # "components-button--primary"
    title: str  # "Components/Button"
    name: str  # "Primary"
    import_path: str  # "./src/components/ui/Button.stories.tsx"
    export_name: str | None = None  # present in v5 files written by Storybook 10; may be absent
    component_path: str | None = None  # absent when the story's meta has no ``component``
    tags: tuple[str, ...] = ()

    @property
    def component(self) -> str:
        """The component id: the story id before ``--``."""
        return self.id.split("--", 1)[0]

    @property
    def testable(self) -> bool:
        """True unless the story opts out of test runs (the ``test`` tag is absent)."""
        return "test" in self.tags


@dataclass(frozen=True)
class StoryIndex:
    """Every story in one ``index.json``; docs entries are left out."""

    version: int
    stories: tuple[Story, ...] = ()

    def components(self) -> list[str]:
        """Every component id, sorted."""
        return sorted({s.component for s in self.stories})

    def get(self, story_id: str) -> Story | None:
        """The story with this id, or None."""
        return next((s for s in self.stories if s.id == story_id), None)

    def of_component(self, component: str) -> list[Story]:
        """Every story of one component."""
        return [s for s in self.stories if s.component == component]


def _opt_str(entry: dict[str, object], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) else None


def _story(entry: dict[str, object]) -> Story | None:
    sid, title, name = entry.get("id"), entry.get("title"), entry.get("name")
    if not (isinstance(sid, str) and isinstance(title, str) and isinstance(name, str)):
        return None
    raw_tags = entry.get("tags")
    tags = (
        tuple(t for t in cast("list[object]", raw_tags) if isinstance(t, str))
        if isinstance(raw_tags, list)
        else ()
    )
    return Story(
        id=sid,
        title=title,
        name=name,
        import_path=_opt_str(entry, "importPath") or "",
        export_name=_opt_str(entry, "exportName"),
        component_path=_opt_str(entry, "componentPath"),
        tags=tags,
    )


def load(path: Path) -> StoryIndex:
    """Read one ``index.json``.

    Raises:
        StoryIndexError: the file is missing, is not JSON, has no ``entries`` object, or has a
            ``v`` this reader does not support. The message says which, and what to run.
    """
    if not path.exists():
        raise StoryIndexError(f"{path} not found: run `storybook build` first")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoryIndexError(f"{path} is not readable JSON ({e})") from e
    if not isinstance(raw, dict):
        raise StoryIndexError(f"{path}: expected a JSON object")
    data = cast("dict[str, object]", raw)
    version = data.get("v")
    if not isinstance(version, int) or version not in SUPPORTED_VERSIONS:
        known = ", ".join(str(v) for v in sorted(SUPPORTED_VERSIONS))
        raise StoryIndexError(f"{path}: index.json v={version!r} is not supported (known: {known})")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise StoryIndexError(f"{path}: no 'entries' object")
    stories: list[Story] = []
    for value in cast("dict[str, object]", entries).values():
        if not isinstance(value, dict):
            continue
        entry = cast("dict[str, object]", value)
        if entry.get("type") != "story":
            continue  # docs pages are not component states
        story = _story(entry)
        if story is not None:
            stories.append(story)
    return StoryIndex(version=version, stories=tuple(sorted(stories, key=lambda s: s.id)))
