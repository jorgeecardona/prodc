"""``prodc issue next``: the ready issue to work on, walked from the current release."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
"""

_RELEASES = """
releases:
  - id: R1
    text: first
  - id: R2
    text: second
"""

_NEEDS = """
needs:
  - id: N-1
    text: top of R1
    release: R1
    must: true
  - id: N-2
    text: second in R1
    release: R1
  - id: N-3
    text: in R2
    release: R2
  - id: N-4
    text: shipped
    release: R1
    proofs: ["acc:signed"]
"""


def _board(root: Path, needs: str, *, register: bool = True) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if register:
        (root / "docs" / "issues").mkdir(parents=True)
    (root / "needs").mkdir()
    (root / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (root / "needs" / "a.yaml").write_text(needs, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _board(tmp_path, _RELEASES + _NEEDS)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _file(title: str, *needs: str, owner: str | None = None) -> None:
    args = ["issue", "file", "--title", title, "--area", "cli", "--body", "b"]
    for n in needs:
        args += ["--need", n]
    assert main(args) == 0
    if owner:
        slug = title.lower().replace(" ", "-")
        assert main(["issue", "update", slug, "--status", "in-progress", "--owner", owner]) == 0


def _next(capsys: pytest.CaptureFixture[str], *extra: str) -> Any:
    capsys.readouterr()
    assert main(["issue", "next", "--json", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_no_board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert _next(capsys)["skip"] == "no-board"


def test_no_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    _board(tmp_path, _RELEASES + _NEEDS, register=False)
    monkeypatch.chdir(tmp_path)
    assert _next(capsys)["skip"] == "no-register"


def test_no_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    _board(tmp_path, "\nneeds:\n  - id: N-1\n    text: t\n")
    monkeypatch.chdir(tmp_path)
    assert _next(capsys)["skip"] == "no-releases"


def test_all_delivered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    done = '\nneeds:\n  - id: N-1\n    text: t\n    release: R1\n    proofs: ["acc:x"]\n'
    _board(tmp_path, _RELEASES + done)
    monkeypatch.chdir(tmp_path)
    data = _next(capsys)
    assert (data["skip"], data["release"]) == ("all-delivered", None)


def test_no_linked_issue_lists_the_needs(repo: Path, capsys: Any) -> None:
    _file("Later work", "N-3")  # R2 is not current: never read
    _file("Done work", "N-4")  # DELIVERED: never picked
    _file("Loose work")  # no need: never picked
    data = _next(capsys)
    assert data["skip"] == "no-linked-issue" and data["pick"] is None
    assert data["needs_without_issue"] == ["N-1", "N-2"]
    assert data["release"] == {"id": "R1", "text": "first", "open_needs": 2}


def test_walks_down_past_a_need_without_issue(repo: Path, capsys: Any) -> None:
    _file("Second", "N-2")
    data = _next(capsys)
    assert data["skip"] is None
    assert data["pick"]["issue"] == "second" and data["pick"]["need"] == "N-2"
    assert data["pick"]["need_rank"] == 2
    assert data["pick"]["why"] == "N-2 is rank 2 in release R1: HOLE, opinion"
    assert data["needs_without_issue"] == ["N-1"]


def test_an_issue_citing_two_needs_appears_once(repo: Path, capsys: Any) -> None:
    _file("Both", "N-2", "N-1")
    _file("Only two", "N-2")
    data = _next(capsys)
    assert [(c["issue"], c["need"]) for c in data["candidates"]] == [
        ("both", "N-1"),
        ("only-two", "N-2"),
    ]
    assert data["pick"]["why"].startswith("N-1 is rank 1 in release R1: must, HOLE")


def test_owner_counts_own_issues_as_ready(repo: Path, capsys: Any) -> None:
    _file("Mine", "N-1", owner="ana")
    _file("Theirs", "N-1", owner="bob")
    assert _next(capsys)["skip"] == "no-linked-issue"
    assert [c["issue"] for c in _next(capsys, "--owner", "ana")["candidates"]] == ["mine"]


def test_load_failure_is_exit_2(repo: Path, capsys: Any) -> None:
    (repo / "needs" / "a.yaml").write_text("needs: [", encoding="utf-8")
    assert main(["issue", "next", "--json"]) == 2
