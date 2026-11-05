"""An active decision grounds a must-have for the lint gate, and only an active one (#86)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_NEED = "needs:\n  - id: L-1\n    text: t\n    must: true\n"


def _lint(tmp_path: Path, decisions: str) -> int:
    (tmp_path / "needs.yaml").write_text(_NEED + decisions, encoding="utf-8")
    cfg = tmp_path / "prodc.toml"
    cfg.write_text('[prodc]\nneeds = ["needs.yaml"]\n', encoding="utf-8")
    return main(["lint", "--config", str(cfg)])


_DECISION = "decisions:\n  - id: D-1\n    text: d\n    needs: [L-1]\n"


def test_active_decision_grounds_a_must_have(tmp_path: Path) -> None:
    assert _lint(tmp_path, _DECISION) == 0


@pytest.mark.parametrize(
    "extra",
    ["", "    draft: true\n", "    withdrawn: {reason: r, date: 2026-01-01}\n"],
    ids=["none", "draft", "withdrawn"],
)
def test_other_decisions_do_not_ground_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: str
) -> None:
    decisions = _DECISION + extra if extra else ""
    assert _lint(tmp_path, decisions) == 1
    assert "record the decision" in capsys.readouterr().out
