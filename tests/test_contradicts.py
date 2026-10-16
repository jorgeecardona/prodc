"""The `contradicts` need→need edge (step 3): two needs that oppose each other.

Symmetric, validated at load, and surfaced so the board can show clients pulling in opposite
directions. The relation is declared once in the file but carried on both needs in the model.
`lint` warns when a contradicting pair is left both-live — the vision has not decided yet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.status import contradictions

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

# N-1 declares the edge; N-2 does not — the loader closes it symmetrically.
_NEEDS = """
needs:
  - id: N-1
    text: recordings never leave the device
    contradicts: [N-2]
  - id: N-2
    text: share a live session with a teammate
  - id: N-3
    text: a metronome keeps steady tempo
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- loader (parse + symmetry + validation) ---------------------------------


def test_loader_parses_and_symmetrizes(tmp_path: Path) -> None:
    by_id = {n.id: n for n in load(Config.load(_project(tmp_path))).needs}
    assert by_id["N-1"].contradicts == ("N-2",)
    assert by_id["N-2"].contradicts == ("N-1",)  # symmetric, though N-2's YAML never declared it
    assert by_id["N-3"].contradicts == ()


def test_unknown_contradicts_target_rejected(tmp_path: Path) -> None:
    needs = "needs:\n  - id: N-1\n    text: t\n    contradicts: [N-9]\n"
    with pytest.raises(LoaderError, match="contradicts 'N-9' is not a known need id"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_self_contradiction_rejected(tmp_path: Path) -> None:
    needs = "needs:\n  - id: N-1\n    text: t\n    contradicts: [N-1]\n"
    with pytest.raises(LoaderError, match="contradicts itself"):
        load(Config.load(_project(tmp_path, needs=needs)))


# --- contradictions() view --------------------------------------------------


def test_contradictions_unresolved_when_both_live(tmp_path: Path) -> None:
    model = load(Config.load(_project(tmp_path)))
    cs = contradictions(list(model.needs))
    assert len(cs) == 1  # one unordered pair, not two
    assert (cs[0].a.id, cs[0].b.id) == ("N-1", "N-2")
    assert cs[0].unresolved is True


def test_contradiction_resolved_when_one_withdrawn(tmp_path: Path) -> None:
    needs = """
needs:
  - id: N-1
    text: recordings never leave the device
    contradicts: [N-2]
  - id: N-2
    text: share a live session with a teammate
    withdrawn:
      kind: out_of_scope
      reason: breaks local-first
      date: 2026-10-10
"""
    model = load(Config.load(_project(tmp_path, needs=needs)))
    cs = contradictions(list(model.needs))
    assert len(cs) == 1
    assert cs[0].unresolved is False  # N-2 is off the board; the vision decided


# --- writer: set contradicts+= ----------------------------------------------


def test_set_contradicts_appends_and_symmetrizes(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(
        tmp_path,
        needs="needs:\n  - id: N-1\n    text: local only\n  - id: N-2\n    text: cloud sync\n",
    )
    assert main(["set", "N-1", "contradicts+=N-2", "--config", str(cfg)]) == 0
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert by_id["N-1"].contradicts == ("N-2",)
    assert by_id["N-2"].contradicts == ("N-1",)  # symmetric on reload


# --- show (text + json) -----------------------------------------------------


def test_show_text_names_the_contradiction_symmetrically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    # N-2 never declared the edge, but show still names it (the relation is symmetric)
    main(["show", "N-2", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "contradicts: N-1" in out


def test_status_json_carries_contradicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    by_id = {n["id"]: n for n in json.loads(capsys.readouterr().out)["needs"]}
    assert by_id["N-1"]["contradicts"] == ["N-2"]
    assert by_id["N-2"]["contradicts"] == ["N-1"]
    assert by_id["N-3"]["contradicts"] == []


# --- lint (both-live warning) -----------------------------------------------


def test_lint_warns_unresolved_contradiction_on_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    code = main(["lint", "--config", str(_project(tmp_path))])
    assert code == 0  # a warning, never a hard error
    out = capsys.readouterr().out
    assert "N-1: unresolved contradiction with N-2" in out
    assert "N-2: unresolved contradiction with N-1" in out


def test_status_text_shows_unresolved_contradictions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "contradictions (two needs in tension" in out
    assert "N-1 vs N-2" in out


def test_lint_silent_when_contradiction_resolved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: recordings never leave the device
    contradicts: [N-2]
  - id: N-2
    text: share a live session with a teammate
    withdrawn:
      kind: out_of_scope
      reason: breaks local-first
      date: 2026-10-10
"""
    main(["lint", "--config", str(_project(tmp_path, needs=needs))])
    assert "unresolved contradiction" not in capsys.readouterr().out
