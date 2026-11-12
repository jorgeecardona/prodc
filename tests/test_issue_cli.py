"""prodc issue: file, update, close, check and board over a real docs/issues folder."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from prodc.cli import main


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _json(capsys: pytest.CaptureFixture[str]) -> Any:
    return json.loads(capsys.readouterr().out)


def test_file_then_board_shows_it_ready(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["issue", "file", "--title", "Fix the thing", "--area", "cli", "--body", "b", "--json"]
    )
    assert rc == 0
    filed = _json(capsys)
    assert filed["file"].endswith("fix-the-thing.md")
    assert main(["issue", "board", "--json"]) == 0
    board = _json(capsys)
    assert [r["slug"] for r in board["ready"]] == ["fix-the-thing"]


def test_blocked_issue_waits_until_its_blocker_closes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["issue", "file", "--title", "First", "--area", "a", "--body", "b"])
    main(
        [
            "issue",
            "file",
            "--title",
            "Second",
            "--area",
            "a",
            "--body",
            "b",
            "--blocked-by",
            "first",
        ]
    )
    capsys.readouterr()
    main(["issue", "board", "--json"])
    board = _json(capsys)
    assert [w["slug"] for w in board["waiting"]] == ["second"]
    assert main(["issue", "close", "first", "--fixed-in", "abc1234", "--json"]) == 0
    closed = _json(capsys)
    assert closed["unblocked"] == ["second"]


def test_update_changes_only_what_is_passed(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["issue", "file", "--title", "T", "--area", "a", "--body", "b", "--field", "scope=S"])
    capsys.readouterr()
    assert main(["issue", "update", "t", "--status", "in-progress", "--json"]) == 0
    row = _json(capsys)
    assert row["status"] == "in-progress" and row["area"] == "a" and row["fields"]["scope"] == "S"


def test_check_exits_1_on_a_broken_issue(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "docs" / "issues" / "11-11-2026-bad.md").write_text("no front matter\n")
    assert main(["issue", "check"]) == 1
    assert main(["issue", "update", "nope", "--status", "open"]) == 2


def test_no_register_is_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["issue", "board"]) == 2


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
"""

_NEEDS = """
needs:
  - id: N-1
    text: a delivered want
    proofs: ["acc:signed"]
  - id: N-2
    text: a want with no proof yet
"""


@pytest.fixture
def board(repo: Path) -> Path:
    (repo / "needs").mkdir()
    (repo / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (repo / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    return repo


def _file(*extra: str) -> int:
    return main(["issue", "file", "--title", "Work", "--area", "cli", "--body", "b", *extra])


def test_file_with_needs_records_them(board: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _file("--need", "N-1", "--need", "N-2", "--json") == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["needs"] == ["N-1", "N-2"]
    assert "serves no need" not in out.err
    (path,) = (board / "docs" / "issues").glob("*-work.md")
    assert "needs:\n  - N-1\n  - N-2\n" in path.read_text()


def test_file_refuses_an_unknown_need(board: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _file("--need", "N-99") == 2
    assert "no such need: N-99" in capsys.readouterr().err
    assert not list((board / "docs" / "issues").glob("*.md"))


def test_file_without_a_need_warns_but_files(
    board: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _file() == 0
    assert "issue serves no need" in capsys.readouterr().err
    assert list((board / "docs" / "issues").glob("*-work.md"))


def test_close_reports_need_states_and_warns_when_unproven(
    board: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _file("--need", "N-1", "--need", "N-2") == 0
    capsys.readouterr()
    assert main(["issue", "close", "work", "--fixed-in", "abc1234"]) == 0
    out = capsys.readouterr()
    assert "serves N-1: DELIVERED" in out.out and "serves N-2: HOLE" in out.out
    assert "closed but unproven: N-2 is HOLE" in out.err
    assert "N-1 is" not in out.err


def test_update_sets_and_clears_the_owner(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _file() == 0
    assert main(["issue", "update", "work", "--status", "in-progress", "--owner", "ana"]) == 0
    assert main(["issue", "check"]) == 0
    capsys.readouterr()
    assert main(["issue", "update", "work", "--owner", "none", "--json"]) == 0
    assert _json(capsys)["owner"] is None


@pytest.mark.parametrize("how", [["--field", "needs="], ["--clear-needs"]])
def test_update_with_an_empty_needs_clears_the_list(
    board: Path, capsys: pytest.CaptureFixture[str], how: list[str]
) -> None:
    assert _file("--need", "N-1") == 0
    capsys.readouterr()
    assert main(["issue", "update", "work", *how, "--json"]) == 0
    assert _json(capsys)["needs"] == []
    (path,) = (board / "docs" / "issues").glob("*-work.md")
    assert "needs" not in path.read_text()


def test_update_with_an_empty_extra_field_removes_the_key(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _file("--field", "tags=a", "--field", "tags=b") == 0
    capsys.readouterr()
    assert main(["issue", "update", "work", "--field", "tags=", "--json"]) == 0
    assert "tags" not in _json(capsys)["fields"]
    (path,) = (repo / "docs" / "issues").glob("*-work.md")
    assert "tags" not in path.read_text()
