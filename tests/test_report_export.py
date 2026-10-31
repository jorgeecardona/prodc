"""`prodc report --format csv|jira|confluence`: the board for product tooling (#65)."""

from __future__ import annotations

import csv
import io
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
who: jordan
goals:
  - id: G-1
    text: fewer lost orders
releases:
  - id: R-1
    text: first release
needs:
  - id: N-1
    text: "see past-due orders | at a glance"
    must: true
    client: acme
    goal: G-1
    release: R-1
    importance: 3
    proofs: ["acc:signed"]
    sources:
      - kind: secondary
        locator: https://gitlab.com/g/p/-/issues/12
        date: 2026-09-21
  - id: N-2
    text: export the run sheet
"""


def _project(tmp_path: Path) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _report(tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str) -> str:
    assert main(["report", "--config", _project(tmp_path), "--format", fmt]) == 0
    return capsys.readouterr().out


def test_csv_has_one_row_per_need_with_the_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = list(csv.DictReader(io.StringIO(_report(tmp_path, capsys, "csv"))))
    assert [r["id"] for r in rows] == ["N-1", "N-2"]
    one = rows[0]
    assert (one["client"], one["goal"], one["release"], one["importance"]) == (
        "acme",
        "G-1",
        "R-1",
        "3",
    )
    assert (one["must"], one["warrant"], one["source_type"]) == ("yes", "secondary", "ticket")
    assert one["text"] == "see past-due orders | at a glance"  # csv quoting keeps the pipe
    assert rows[1]["warrant"] == "opinion" and rows[1]["state"] == "HOLE"


def test_jira_markup_escapes_pipes_and_colours_the_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _report(tmp_path, capsys, "jira")
    lines = out.splitlines()
    assert lines[0].startswith("h1. ") and lines[0].endswith("product status")
    assert lines[2].startswith("||id||client||") and lines[2].endswith("||text||")
    assert "see past-due orders \\| at a glance" in out
    assert "{color:gray}HOLE{color}" in out


def test_confluence_storage_format_escapes_and_uses_status_macros(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _report(tmp_path, capsys, "confluence")
    assert out.startswith("<h1>") and "<table><tbody>" in out
    assert "<th>id</th>" in out and "<td>N-1</td>" in out
    assert '<ac:parameter ac:name="title">HOLE</ac:parameter>' in out
    assert '<ac:parameter ac:name="colour">Grey</ac:parameter>' in out


def test_export_formats_take_no_md_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["report", "--config", cfg, "--format", "csv", "--only-open"]) == 2
    assert "md only" in capsys.readouterr().err


def test_client_scopes_the_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    assert main(["report", "--config", cfg, "--format", "csv", "--client", "acme"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert "N-1" in [r["id"] for r in rows]
