"""``prodc plan`` over a board with releases: the now-set ranks first, and rows name their issues."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
"""

_NEEDS = """
releases:
  - id: R1
    text: first
  - id: R2
    text: second
needs:
  - id: N-1
    text: shipped
    release: R1
    proofs: ["acc:signed"]
  - id: N-2
    text: next up
    release: R2
  - id: N-3
    text: a must with no release
    must: true
"""


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_plan_json_marks_now_and_names_ready_issues(
    board: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["issue", "file", "--title", "Do N2", "--area", "cli", "--body", "b", "--need", "N-2"]
    assert main(args) == 0
    capsys.readouterr()
    assert main(["plan", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["current_release"] == {"id": "R2", "text": "second"}
    first = data["plan"][0]
    assert (first["id"], first["now"], first["release"]) == ("N-2", True, "R2")
    assert first["issues"] == ["do-n2"]
    assert all(not row["now"] for row in data["plan"][1:])


def test_plan_text_separates_now_from_later(
    board: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "now: release R2 (second)" in out
    assert out.index("N-2") < out.index("---- later") < out.index("N-3")
