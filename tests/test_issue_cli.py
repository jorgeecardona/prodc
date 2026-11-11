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
