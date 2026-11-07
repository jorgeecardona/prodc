"""``prodc inbox`` lists the open decisions only a person can make, with options (#113)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main

_NEEDS = """needs:
  - id: I-1
    text: an unsourced must-have
    must: true
  - id: I-2
    text: a decided must-have
    must: true
  - id: I-3
    text: a need whose review returned concerns
    sources:
      - {kind: secondary, date: 2026-01-01, locator: doc}
    attestation: {who: model-x, date: 2026-01-02, kind: ai, verdict: concerns, comment: weak test}
  - id: I-4
    text: a need whose review passed
    sources:
      - {kind: secondary, date: 2026-01-01, locator: doc}
    attestation: {who: ana, date: 2026-01-02, verdict: pass}
decisions:
  - id: D-1
    text: d
    needs: [I-2]
"""


def _board(tmp_path: Path) -> Path:
    (tmp_path / "needs.yaml").write_text(_NEEDS, encoding="utf-8")
    cfg = tmp_path / "prodc.toml"
    cfg.write_text('[prodc]\nneeds = ["needs.yaml"]\n', encoding="utf-8")
    return cfg


def test_inbox_lists_must_opinions_and_warrant_concerns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _board(tmp_path)
    assert main(["inbox", "--config", str(cfg), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(i["need"], i["kind"]) for i in data["items"]] == [
        ("I-1", "must_opinion"),
        ("I-3", "warrant_review"),
    ]
    commands = [o["command"] for o in data["items"][0]["options"]]
    assert "prodc set I-1 must=false" in commands
    assert "weak test" in data["items"][1]["reason"]


def test_inbox_only_lists_and_never_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _board(tmp_path)
    before = (tmp_path / "needs.yaml").read_text(encoding="utf-8")
    assert main(["inbox", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "2 decision(s) wait on you" in out
    assert (tmp_path / "needs.yaml").read_text(encoding="utf-8") == before


def test_empty_inbox_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "needs.yaml").write_text("needs:\n  - id: A-1\n    text: t\n", encoding="utf-8")
    cfg = tmp_path / "prodc.toml"
    cfg.write_text('[prodc]\nneeds = ["needs.yaml"]\n', encoding="utf-8")
    assert main(["inbox", "--config", str(cfg)]) == 0
    assert "nothing waits on you" in capsys.readouterr().out
