"""Each deprecated thing prints one line per run: ``deprecated, removed in 0.12: ...``."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_NEED = "  - id: N-1\n    text: When I log in, I can see my orders.\n"


def _board(tmp_path: Path, toml: str = "", needs: str = _NEED, top: str = "") -> str:
    (tmp_path / "n.yaml").write_text(f"{top}needs:\n{needs}", encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(f'[prodc]\nfiles = ["n.yaml"]\n{toml}', encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _lines(err: str, thing: str) -> list[str]:
    return [ln for ln in err.splitlines() if f"deprecated, removed in 0.12: {thing}" in ln]


def test_sync_and_callbacks_warn_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _board(tmp_path, '[[callbacks.hooks]]\non = "state_change"\ncommand = ["true"]\n')
    main(["sync", "--config", cfg, "--dry-run"])
    err = capsys.readouterr().err
    assert len(_lines(err, "prodc sync")) == 1
    assert len(_lines(err, "[callbacks]")) == 1
    assert main(["lint", "--config", cfg]) == 0
    assert len(_lines(capsys.readouterr().out, "[callbacks]")) == 1


def test_gitlab_source_warns_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _board(tmp_path, '[sources.gl]\nkind = "gitlab"\nproject = "a/b"\n')
    assert main(["status", "--config", cfg]) == 0
    assert len(_lines(capsys.readouterr().err, '[sources.gl] kind = "gitlab"')) == 1


@pytest.mark.parametrize(
    ("argv", "thing"),
    [
        (["brief", "acme"], "prodc brief"),
        (["dupes"], "prodc dupes"),
        (["recurrence", "--suggest"], "prodc recurrence --suggest/--apply"),
        (["accept", "N-1", "--who", "ana", "--date", "2026-11-14", "--dry-run"], "prodc accept"),
        (
            ["outcome", "N-1", "--not-landed", "--by", "ana", "--date", "2026-11-14", "--dry-run"],
            "prodc outcome",
        ),
    ],
)
def test_deprecated_commands_warn_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], thing: str
) -> None:
    cfg = _board(tmp_path)
    main([*argv, "--config", cfg])
    assert len(_lines(capsys.readouterr().err, thing)) == 1


def test_plain_recurrence_does_not_warn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["recurrence", "--config", _board(tmp_path)])
    assert "deprecated" not in capsys.readouterr().err


def test_deprecated_need_fields_warn_once_per_field_not_per_need(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    needs = (
        "  - id: N-1\n    text: When I log in, I can see my orders.\n    tags: [a]\n"
        "    importance: 2\n    terms: [order]\n    expects: test\n    contradicts: [N-2]\n"
        "  - id: N-2\n    text: When I log out, I can see nothing.\n    tags: [b]\n"
        "    importance: 1\n"
    )
    top = "glossary:\n  - term: order\n    text: a purchase\n"
    toml = '[importance]\nlevels = [[1, "low", "nice"], [2, "high", "core"]]\n'
    cfg = _board(tmp_path, toml, needs, top)
    main(["status", "--config", cfg])
    err = capsys.readouterr().err
    for thing in (
        "need field tags",
        "need field importance",
        "need field terms",
        "need field expects",
        "need field contradicts",
        "glossary:",
        "[importance]",
    ):
        assert len(_lines(err, thing)) == 1, thing
    main(["plan", "--config", cfg, "--revisit", "30"])
    assert len(_lines(capsys.readouterr().err, "prodc plan --revisit")) == 1


def test_a_board_without_deprecated_fields_is_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["status", "--config", _board(tmp_path)])
    assert "deprecated" not in capsys.readouterr().err
