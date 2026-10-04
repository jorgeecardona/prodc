"""CLI board, end to end: gap summary line, warrant column, and the gate exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]
"""

_NEEDS = """
who: jordan
needs:
  - id: D-1
    text: a delivered need
    sources:
      - kind: interview
        who: John
        quote: "I need this"
        date: 2026-01-01
    proofs: ["web:orders.feature#Done"]
  - id: H-1
    text: a must-have with no proof
    must: true
    sources:
      - kind: artifact
        locator: issues.md#H-1
        date: 2026-01-01
  - id: O-1
    text: an unsourced opinion
"""

_FEATURE = """
Feature: orders
  @implemented
  Scenario: Done
    Given a thing
    Then it works

  Scenario: Unclaimed extra
    Given another thing
    Then no need references me
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir()
    (tmp_path / "features").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_board_shows_summary_and_warrant(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0  # a must-HOLE is an honest gap, never a failure
    assert "gaps:" in out and "coverage 1/3" in out  # leading gap-count line (#2)
    assert "WARRANT" in out  # the warrant column header (#3)
    assert "interview:John" in out  # strongest warrant for D-1
    assert "opinion" in out  # O-1's warrant
    assert "legend:" in out  # glyph legend (#10)
    # provenance mix (#11): 1 interview, 1 artifact, 0 internal, 1 opinion
    assert "provenance:" in out and "1 interview" in out and "1 artifact" in out


def test_json_has_summary_and_grounds_warrant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    code = main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["total"] == 3 and payload["summary"]["must_hole"] == 1
    d1 = next(n for n in payload["needs"] if n["id"] == "D-1")
    assert d1["grounds"] == "delivered" and d1["warrant"] == "interview:John"


def test_min_coverage_gate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path)), "--min-coverage", "0.9"])
    capsys.readouterr()
    assert code == 1  # coverage is 1/3, below 0.9


def test_strict_fails_on_opinion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path)), "--strict"])
    capsys.readouterr()
    assert code == 1  # O-1 has no source


def test_orphan_report_lists_unclaimed_scenarios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0  # orphans alone don't fail without a gate
    assert "orphan proofs (claimed by no need): 1" in out
    assert "web:orders.feature#Unclaimed extra" in out
    assert "web:orders.feature#Done" not in out.split("orphan proofs")[1]  # Done is claimed


def test_max_orphans_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = str(_project(tmp_path))
    assert main(["status", "--config", p, "--max-orphans", "0"]) == 1  # 1 orphan > 0
    capsys.readouterr()
    assert main(["status", "--config", p, "--max-orphans", "1"]) == 0  # 1 orphan <= 1
    capsys.readouterr()


def test_orphans_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["orphans"] == 1
    assert payload["orphans"]["web"] == ["orders.feature#Unclaimed extra"]
