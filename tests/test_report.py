"""`prodc report`: the board rendered as a readable markdown document."""

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
"""

_FEATURE = """
Feature: orders
  @implemented
  Scenario: Past due orders are highlighted
    Given an order
    Then it is highlighted
"""

_NEEDS = """
who: jordan
needs:
  - id: N-1
    text: see past-due orders at a glance
    must: true
    sources:
      - kind: interview
        who: Jordan
        date: 2026-09-20
        quote: "I lose them"
    proofs:
      - "web:orders.feature#Past due orders are highlighted"
  - id: N-2
    text: export the run sheet
    sources:
      - kind: artifact
        locator: issues.md#N-2
        date: 2026-09-21
  - id: N-3
    text: implement a settings page
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_report_renders_summary_needs_and_open_questions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["report", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "# " in out and "product status" in out
    assert "1 of 3 delivered" in out  # one proof passes, three leaves
    assert "### jordan" in out
    assert "N-1" in out and "DELIVERED" in out
    assert "## Open questions" in out
    assert "N-3" in out and "no evidence" in out  # the opinion surfaces


def test_report_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    dest = tmp_path / "out" / "status.md"
    code = main(["report", "--config", str(cfg), "--output", str(dest)])
    assert code == 0
    assert "wrote report to" in capsys.readouterr().out
    assert dest.exists() and "product status" in dest.read_text(encoding="utf-8")


def test_report_client_scope_in_heading(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["report", "--config", str(_project(tmp_path)), "--client", "jordan"])
    out = capsys.readouterr().out
    assert code == 0
    assert "— jordan — product status" in out


_NEEDS_PD = """
principles:
  - id: P-1
    text: local-first always
    revised_at: 2026-10-15
needs:
  - id: N-1
    text: store a recording
decisions:
  - id: D-1
    text: store as FLAC on disk
    needs: [N-1]
    alternatives: [WAV]
    principles: [P-1]
    decided_at: 2026-10-16
"""


def test_report_renders_principles_and_decisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS_PD, encoding="utf-8")
    code = main(["report", "--config", str(tmp_path / "prodc.toml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "## Principles" in out and "P-1: local-first always" in out
    assert "## Decisions" in out and "D-1: store as FLAC on disk" in out
    assert "WAV" in out  # the rejected alternative is shown
