"""The story inventory: reading Storybook's index.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc import storybook
from prodc.adapters import StorybookAdapter
from prodc.cli import main
from prodc.model import ProofState

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


# --- the adapter ---------------------------------------------------------------------------


def _adapter(url: str | None = None) -> StorybookAdapter:
    return StorybookAdapter(root=FIXTURE.parent, index="index.json", url=url)


def test_a_story_in_the_index_is_declared_delivered() -> None:
    r = _adapter().resolve("components-codeblock--python")
    assert r.state is ProofState.DELIVERED
    assert r.declared
    assert "story components-codeblock--python in the index (built " in r.detail


def test_a_component_claims_every_story() -> None:
    r = _adapter().resolve("components-codeblock")
    assert r.state is ProofState.DELIVERED
    assert "7 stories of components-codeblock" in r.detail


def test_an_unknown_story_is_broken() -> None:
    assert _adapter().resolve("components-codeblock--rust").state is ProofState.BROKEN
    assert _adapter().resolve("components-nothing").state is ProofState.BROKEN


def test_a_missing_index_is_unresolved(tmp_path: Path) -> None:
    r = StorybookAdapter(root=tmp_path, index="storybook-static/index.json").resolve("a--b")
    assert r.state is ProofState.UNRESOLVED
    assert "storybook build" in r.detail


def test_inventory_and_covers_are_per_component() -> None:
    ad = _adapter()
    assert ad.inventory() == [
        "components-capabilities",
        "components-changelog",
        "components-codeblock",
    ]
    assert ad.covers("components-codeblock--python") == ["components-codeblock"]
    assert ad.covers("components-codeblock") == ["components-codeblock"]
    assert ad.covers("components-codeblock--rust") == []


def test_the_story_url_is_in_the_detail_when_configured() -> None:
    r = _adapter(url="https://sb.example.com/").resolve("components-codeblock--python")
    assert r.detail.endswith("https://sb.example.com/?path=/story/components-codeblock--python")
    assert "?path=" not in _adapter().resolve("components-codeblock--python").detail


def test_a_story_excluded_from_tests_says_so(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "v": 5,
            "entries": {"a--b": {"type": "story", "id": "a--b", "title": "A", "name": "B"}},
        },
    )
    r = StorybookAdapter(root=tmp_path, index="index.json").resolve("a--b")
    assert "excluded from test runs: a--b" in r.detail


def test_config_builds_the_adapter(tmp_path: Path) -> None:
    from prodc.config import Config

    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n\n[proofs.sb]\nkind = "storybook"\nroot = "web"\n'
        'url = "https://sb.example.com"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    ad = cfg.adapters["sb"]
    assert isinstance(ad, StorybookAdapter)
    assert ad.story_url("a--b") == "https://sb.example.com/?path=/story/a--b"
    assert ad.resolve("a--b").state is ProofState.UNRESOLVED  # web/storybook-static missing


# --- orphans and the unjustified_stories lint ----------------------------------------------


def _board(tmp_path: Path, lint: str = "") -> str:
    (tmp_path / "sb").mkdir()
    (tmp_path / "sb" / "index.json").write_text(FIXTURE.read_text(encoding="utf-8"), "utf-8")
    (tmp_path / "needs").mkdir()
    (tmp_path / "needs" / "n.yaml").write_text(
        "needs:\n"
        "  - id: D-1\n"
        "    text: When a reader opens a snippet, they can read it highlighted\n"
        '    proofs: ["sb:components-codeblock--python"]\n',
        encoding="utf-8",
    )
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n\n'
        '[proofs.sb]\nkind = "storybook"\nindex = "sb/index.json"\n' + lint,
        encoding="utf-8",
    )
    return str(tmp_path / "prodc.toml")


def test_orphans_lists_components_no_need_points_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["status", "--config", _board(tmp_path)])
    out = capsys.readouterr().out
    assert "components-capabilities" in out
    assert "components-changelog" in out


def test_unjustified_stories_is_opt_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["lint", "--config", _board(tmp_path)])
    assert "unjustified component" not in capsys.readouterr().out


def test_unjustified_stories_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "lint",
            "--config",
            _board(tmp_path, '\n[lint]\nunjustified_stories = "warn"\n'),
            "--all-warnings",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "sb:components-changelog: unjustified component" in out
    assert "components-codeblock: unjustified" not in out


def test_unjustified_stories_error_fails_lint(tmp_path: Path) -> None:
    cfg = _board(tmp_path, '\n[lint]\nunjustified_stories = "error"\n')
    assert main(["lint", "--config", cfg]) == 1


def test_suggest_leaves_stories_out_unless_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _board(tmp_path)
    (tmp_path / "needs" / "h.yaml").write_text(
        "needs:\n  - id: H-1\n    text: When a reader opens the changelog, they can see changes\n",
        encoding="utf-8",
    )
    main(["suggest", "--config", cfg, "--json"])
    assert "sb:" not in capsys.readouterr().out
    main(["suggest", "--config", cfg, "--kind", "sb", "--json", "--min-score", "0"])
    assert "sb:components-changelog" in capsys.readouterr().out


# --- story links in show and report ---------------------------------------------------------


def test_report_lists_story_links_when_url_is_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _board(tmp_path)
    toml = tmp_path / "prodc.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            'index = "sb/index.json"\n', 'index = "sb/index.json"\nurl = "https://sb.example.com"\n'
        ),
        encoding="utf-8",
    )
    main(["report", "--config", cfg])
    out = capsys.readouterr().out
    assert "## Stories" in out
    assert (
        "| D-1 | [components-codeblock--python]"
        "(https://sb.example.com/?path=/story/components-codeblock--python) |"
    ) in out


def test_report_has_no_stories_section_without_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["report", "--config", _board(tmp_path)])
    assert "## Stories" not in capsys.readouterr().out


def test_show_prints_the_story_link(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _board(tmp_path)
    toml = tmp_path / "prodc.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + 'url = "https://sb.example.com"\n', encoding="utf-8"
    )
    main(["show", "D-1", "--config", cfg])
    assert "https://sb.example.com/?path=/story/components-codeblock--python" in (
        capsys.readouterr().out
    )
