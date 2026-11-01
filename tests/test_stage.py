"""The capture funnel (#77): captured, triaged and committed. Only committed needs are counted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Need, Stage, board_needs

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
"""

_NEEDS = """
needs:
  - id: C-1
    text: a committed need
    proofs: ["acc:a"]
  - id: D-1
    text: a captured need
    draft: true
  - id: T-1
    text: a triaged need
    stage: triaged
"""


def _project(tmp_path: Path, needs: str = _NEEDS) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _stages(cfg: str) -> dict[str, tuple[Stage, bool]]:
    return {n.id: (n.stage, n.draft) for n in load(Config.load(Path(cfg))).needs}


def test_stage_defaults_and_draft_is_captured(tmp_path: Path) -> None:
    got = _stages(_project(tmp_path))
    assert got == {
        "C-1": (Stage.COMMITTED, False),
        "D-1": (Stage.CAPTURED, True),
        "T-1": (Stage.TRIAGED, False),
    }


def test_a_need_keeps_draft_and_stage_one_fact() -> None:
    assert Need(id="X", text="t", draft=True).stage is Stage.CAPTURED
    assert Need(id="X", text="t", stage=Stage.CAPTURED).draft is True
    assert Need(id="X", text="t").stage is Stage.COMMITTED


def test_stage_next_walks_up_the_funnel() -> None:
    assert Stage.CAPTURED.next is Stage.TRIAGED
    assert Stage.TRIAGED.next is Stage.COMMITTED
    assert Stage.COMMITTED.next is Stage.COMMITTED


def test_draft_next_to_a_later_stage_is_rejected(tmp_path: Path) -> None:
    cfg = _project(
        tmp_path, "needs:\n  - id: X-1\n    text: x\n    draft: true\n    stage: triaged\n"
    )
    with pytest.raises(LoaderError, match="draft: true means captured"):
        load(Config.load(Path(cfg)))


def test_an_unknown_stage_is_rejected(tmp_path: Path) -> None:
    cfg = _project(tmp_path, "needs:\n  - id: X-1\n    text: x\n    stage: maybe\n")
    with pytest.raises(LoaderError, match="unknown stage 'maybe'"):
        load(Config.load(Path(cfg)))


def test_the_board_counts_only_committed_needs() -> None:
    needs = [
        Need(id="C", text="t"),
        Need(id="D", text="t", draft=True),
        Need(id="T", text="t", stage=Stage.TRIAGED),
    ]
    assert [n.id for n in board_needs(needs, include_drafts=False)] == ["C"]
    assert [n.id for n in board_needs(needs, include_drafts=True)] == ["C", "D", "T"]
    assert needs[2].excluded_reason == "triaged"


def test_status_shows_the_funnel_and_does_not_count_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["status", "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "drafts: 1 staged" in out
    assert "triaged: 1 reviewed, not committed (not counted)" in out
    assert "1 of 1" in out or "1/1" in out
    assert main(["status", "--config", cfg, "--include-drafts", "--json"]) == 0
    stages = {n["id"]: n["stage"] for n in json.loads(capsys.readouterr().out)["needs"]}
    assert stages == {"C-1": "committed", "D-1": "captured", "T-1": "triaged"}


def test_review_promotes_one_stage_at_a_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["review", "--config", cfg, "--json"]) == 0
    rows = {r["id"]: r["stage"] for r in json.loads(capsys.readouterr().out)["drafts"]}
    assert rows == {"D-1": "captured", "T-1": "triaged"}
    assert main(["review", "--config", cfg, "--promote", "D-1", "T-1"]) == 0
    capsys.readouterr()
    assert _stages(cfg)["D-1"] == (Stage.TRIAGED, False)
    assert _stages(cfg)["T-1"] == (Stage.COMMITTED, False)
    assert main(["review", "--config", cfg, "--promote", "D-1"]) == 0
    assert _stages(cfg)["D-1"] == (Stage.COMMITTED, False)


def test_review_promote_all_commits_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["review", "--config", cfg, "--promote-all"]) == 0
    capsys.readouterr()
    assert {s for s, _ in _stages(cfg).values()} == {Stage.COMMITTED}


def test_review_refuses_a_committed_need(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["review", "--config", cfg, "--promote", "C-1"]) == 2
    assert "not a staged draft: C-1" in capsys.readouterr().err
