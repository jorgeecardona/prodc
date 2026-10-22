"""The `decision` noun (Opportunity-Solution-Tree): the solution chosen for a need, and the
alternatives rejected. Not an ADR — a PM record of *which* solution, serving which need, resting
on which principle. A decision must serve a need (load error otherwise); revising a principle it
cites after `decided_at` flags it stale; a decision left serving only withdrawn needs is orphaned."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Decision
from prodc.status import decisions_for, orphaned_decisions, stale_decisions

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_NEEDS = """
principles:
  - id: P-1
    text: timbre is local-first
    revised_at: 2026-10-15

needs:
  - id: N-1
    text: a recording is stored on disk
  - id: N-2
    text: another need

decisions:
  - id: D-1
    text: store takes as FLAC on disk
    needs: [N-1]
    alternatives: [WAV, cloud blob]
    consequences: bigger files, but lossless and no transcode
    principles: [P-1]
    decided_at: 2026-10-16
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- loader -----------------------------------------------------------------


def test_loader_parses_decision(tmp_path: Path) -> None:
    model = load(Config.load(_project(tmp_path)))
    by_id = {d.id: d for d in model.decisions}
    assert by_id["D-1"] == Decision(
        id="D-1",
        text="store takes as FLAC on disk",
        needs=("N-1",),
        alternatives=("WAV", "cloud blob"),
        consequences="bigger files, but lossless and no transcode",
        principles=("P-1",),
        decided_at="2026-10-16",
    )


def test_decision_without_needs_rejected(tmp_path: Path) -> None:
    needs = "decisions:\n  - id: D-1\n    text: a choice\n    needs: []\n"
    with pytest.raises(LoaderError, match="must serve at least one need"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_decision_unknown_need_rejected(tmp_path: Path) -> None:
    needs = "decisions:\n  - id: D-1\n    text: a choice\n    needs: [N-9]\n"
    with pytest.raises(LoaderError, match="needs 'N-9' is not a known need id"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_decision_unknown_principle_rejected(tmp_path: Path) -> None:
    needs = (
        "needs:\n  - id: N-1\n    text: t\n"
        "decisions:\n  - id: D-1\n    text: a choice\n    needs: [N-1]\n    principles: [P-9]\n"
    )
    with pytest.raises(LoaderError, match="principle 'P-9' is not a known principle id"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_duplicate_decision_id_rejected(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: N-1\n    text: t\ndecisions:\n  - id: D-1\n    text: x\n    needs: [N-1]\n",
        encoding="utf-8",
    )
    (tmp_path / "needs" / "b.yaml").write_text(
        "decisions:\n  - id: D-1\n    text: y\n    needs: [N-1]\n", encoding="utf-8"
    )
    with pytest.raises(LoaderError, match="duplicate decision id 'D-1'"):
        load(Config.load(tmp_path / "prodc.toml"))


# --- status helpers ---------------------------------------------------------


def test_decisions_for_excludes_withdrawn_and_draft(tmp_path: Path) -> None:
    needs = """
needs:
  - id: N-1
    text: t
decisions:
  - id: D-1
    text: live decision
    needs: [N-1]
  - id: D-2
    text: a proposed one
    needs: [N-1]
    draft: true
  - id: D-3
    text: a superseded one
    needs: [N-1]
    withdrawn:
      reason: superseded by D-1
      date: 2026-10-16
"""
    model = load(Config.load(_project(tmp_path, needs=needs)))
    served = decisions_for("N-1", list(model.decisions))
    assert [d.id for d in served] == ["D-1"]  # draft + withdrawn excluded


def test_orphaned_decision_when_all_needs_withdrawn(tmp_path: Path) -> None:
    needs = """
needs:
  - id: N-1
    text: t
    withdrawn:
      kind: out_of_scope
      reason: off strategy
      date: 2026-10-10
decisions:
  - id: D-1
    text: a decision for a now-withdrawn need
    needs: [N-1]
"""
    model = load(Config.load(_project(tmp_path, needs=needs)))
    orphans = orphaned_decisions(list(model.decisions), list(model.needs))
    assert [d.id for d in orphans] == ["D-1"]


def test_stale_decision_when_principle_revised_after(tmp_path: Path) -> None:
    needs = """
principles:
  - id: P-1
    text: local-first
    revised_at: 2026-10-15
needs:
  - id: N-1
    text: t
decisions:
  - id: D-1
    text: decided under the old statement of P-1
    needs: [N-1]
    principles: [P-1]
    decided_at: 2026-10-10
"""
    model = load(Config.load(_project(tmp_path, needs=needs)))
    stale = stale_decisions(list(model.decisions), list(model.principles))
    assert [(d.id, pid) for d, pid in stale] == [("D-1", "P-1")]


# --- writer / CLI (add decision) --------------------------------------------


def test_add_decision_writes_all_fields(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a need\n")
    code = main(
        [
            "add",
            "decision",
            "D-1",
            "--text",
            "use SQLite for the index",
            "--needs",
            "N-1",
            "--alternative",
            "flat files",
            "--alternative",
            "Postgres",
            "--consequences",
            "one file, no server",
            "--date",
            "2026-10-16",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    d = {x.id: x for x in load(Config.load(cfg)).decisions}["D-1"]
    assert d.text == "use SQLite for the index"
    assert d.needs == ("N-1",)
    assert d.alternatives == ("flat files", "Postgres")
    assert d.consequences == "one file, no server"
    assert d.decided_at == "2026-10-16"


def test_add_decision_date_defaults_today(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a need\n")
    main(
        [
            "add",
            "decision",
            "D-1",
            "--text",
            "x",
            "--needs",
            "N-1",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    d = {x.id: x for x in load(Config.load(cfg)).decisions}["D-1"]
    assert d.decided_at == date.today().isoformat()


def test_add_decision_requires_needs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a need\n")
    code = main(
        ["add", "decision", "D-1", "--text", "x", "--file", "needs/a.yaml", "--config", str(cfg)]
    )
    assert code == 2
    assert "requires --needs" in capsys.readouterr().err


def test_withdraw_and_reinstate_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)  # has D-1 serving N-1
    assert (
        main(
            [
                "withdraw",
                "decision",
                "D-1",
                "--reason",
                "superseded by D-2",
                "--date",
                "2026-10-20",
                "--config",
                str(cfg),
            ]
        )
        == 0
    )
    capsys.readouterr()
    d1 = {d.id: d for d in load(Config.load(cfg)).decisions}["D-1"]
    assert d1.withdrawn is not None and d1.withdrawn.reason == "superseded by D-2"
    # off the in-force set while withdrawn
    assert decisions_for("N-1", list(load(Config.load(cfg)).decisions)) == []
    assert main(["reinstate", "decision", "D-1", "--config", str(cfg)]) == 0
    assert {d.id: d for d in load(Config.load(cfg)).decisions}["D-1"].withdrawn is None


def test_reinstate_decision_not_withdrawn_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    assert main(["reinstate", "decision", "D-1", "--config", str(cfg)]) == 2
    assert "not withdrawn" in capsys.readouterr().err


def test_add_decision_requires_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a need\n")
    code = main(
        ["add", "decision", "D-1", "--needs", "N-1", "--file", "needs/a.yaml", "--config", str(cfg)]
    )
    assert code == 2
    assert "requires --text" in capsys.readouterr().err


# --- show / status / lint ---------------------------------------------------


def test_show_need_lists_decisions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["show", "N-1", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "decisions (how it's built):" in out
    assert "D-1: store takes as FLAC on disk  (over WAV, cloud blob)" in out


def test_status_json_carries_decisions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    d = {x["id"]: x for x in payload["decisions"]}["D-1"]
    assert d["needs"] == ["N-1"]
    assert d["alternatives"] == ["WAV", "cloud blob"]
    assert d["principles"] == ["P-1"]


def test_status_text_shows_decisions_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "decisions (the solution chosen for a need, how it gets built):" in out
    assert "D-1" in out and "serves: N-1" in out and "over: WAV, cloud blob" in out


def test_lint_flags_orphaned_and_stale_decisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    needs = """
principles:
  - id: P-1
    text: local-first
    revised_at: 2026-10-15
needs:
  - id: N-1
    text: still live
  - id: N-2
    text: gone
    withdrawn:
      kind: out_of_scope
      reason: off strategy
      date: 2026-10-10
decisions:
  - id: D-ORPHAN
    text: decision for a withdrawn need
    needs: [N-2]
  - id: D-STALE
    text: decided under the old P-1
    needs: [N-1]
    principles: [P-1]
    decided_at: 2026-10-10
"""
    code = main(["lint", "--config", str(_project(tmp_path, needs=needs))])
    assert code == 0  # warnings, not errors
    out = capsys.readouterr().out
    assert "D-ORPHAN: decision serves only withdrawn/non-product needs" in out
    assert "D-STALE: decided 2026-10-10 under principle P-1, revised later" in out
