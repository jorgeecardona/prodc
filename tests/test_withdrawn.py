"""Withdrawn / won't-do need state (#74): a decision against a need takes it off the
active board and out of coverage, with the YAML record as its durable trace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Need, Withdrawal

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_NEEDS = """
needs:
  - id: N-1
    text: user can see a delivered thing
    proofs: ["x:1"]
  - id: W-1
    text: a need we decided against
    withdrawn:
      reason: superseded by N-1
      date: 2026-10-10
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- model / loader ---------------------------------------------------------


def test_loader_parses_withdrawal(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path))
    by_id = {n.id: n for n in load(cfg).needs}
    w = by_id["W-1"].withdrawn
    assert w == Withdrawal(reason="superseded by N-1", date="2026-10-10")
    assert by_id["W-1"].is_withdrawn is True
    assert by_id["N-1"].is_withdrawn is False


def test_loader_errors_on_missing_field(tmp_path: Path) -> None:
    bad = """
needs:
  - id: W-2
    text: missing the date
    withdrawn:
      reason: no date given
"""
    with pytest.raises(LoaderError, match="withdrawal needs both 'reason' and 'date'"):
        load(Config.load(_project(tmp_path, needs=bad)))


def test_excluded_reason_precedence() -> None:
    # withdrawn overrides draft and nonproduct
    both = Need(
        id="X", text="t", draft=True, product=False, withdrawn=Withdrawal("done", "2026-01-01")
    )
    assert both.excluded_reason == "withdrawn"
    assert Need(id="X", text="t", draft=True).excluded_reason == "draft"
    assert Need(id="X", text="t", product=False).excluded_reason == "nonproduct"
    assert Need(id="X", text="t").excluded_reason is None


def test_counts_toward_coverage_excludes_withdrawn() -> None:
    live = Need(id="X", text="t")
    gone = Need(id="X", text="t", withdrawn=Withdrawal("no", "2026-01-01"))
    assert live.counts_toward_coverage is True
    assert gone.counts_toward_coverage is False


def test_board_needs_always_excludes_withdrawn() -> None:
    from prodc.model import board_needs

    live = Need(id="A", text="t")
    gone = Need(id="B", text="t", withdrawn=Withdrawal("no", "2026-01-01"))
    draft = Need(id="C", text="t", draft=True)
    # withdrawn dropped whether or not drafts are included; drafts still gated by the flag
    assert [n.id for n in board_needs([live, gone, draft], include_drafts=False)] == ["A"]
    assert [n.id for n in board_needs([live, gone, draft], include_drafts=True)] == ["A", "C"]


# --- status (board + coverage) ----------------------------------------------


def test_status_excludes_withdrawn_from_board_and_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    ids = {n["id"] for n in payload["needs"]}
    assert ids == {"N-1"}  # W-1 is off the board
    assert payload["summary"]["total"] == 1  # and out of coverage


def test_status_withdrawn_not_shown_even_with_include_drafts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--include-drafts", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {n["id"] for n in payload["needs"]} == {"N-1"}  # no --include flag for withdrawn


def test_status_text_shows_withdrawn_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "withdrawn: 1 (decided against) (#74)" in out


def test_coverage_before_and_after_withdraw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # two leaves, one delivered, one a HOLE → 1/2 (50%); withdrawing the HOLE → 1/1 (100%)
    needs = """
needs:
  - id: N-1
    text: delivered thing
    proofs: ["x:1"]
  - id: N-2
    text: an unproven thing
"""
    toml = _TOML + '\n[proofs.x]\nkind = "files"\n'
    (tmp_path / "1").write_text("ok\n", encoding="utf-8")  # files adapter root="." → payload "1"
    cfg = _project(tmp_path, toml=toml, needs=needs)
    from prodc.cli import main

    main(["status", "--config", str(cfg), "--json"])
    before = json.loads(capsys.readouterr().out)["summary"]
    assert (before["delivered"], before["total"]) == (1, 2)

    main(["withdraw", "N-2", "--reason", "out of scope", "--config", str(cfg)])
    capsys.readouterr()  # drop the withdraw diff
    main(["status", "--config", str(cfg), "--json"])
    after = json.loads(capsys.readouterr().out)["summary"]
    assert (after["delivered"], after["total"]) == (1, 1)  # HOLE gone from the denominator


# --- writer verbs (withdraw / reinstate) ------------------------------------


def test_withdraw_then_reinstate_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(
        tmp_path, needs='needs:\n  - id: N-1\n    text: a live need\n    proofs: ["x:1"]\n'
    )
    assert (
        main(
            [
                "withdraw",
                "N-1",
                "--reason",
                "won't do",
                "--date",
                "2026-10-10",
                "--config",
                str(cfg),
            ]
        )
        == 0
    )
    capsys.readouterr()
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "withdrawn:" in text and "won't do" in text
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert by_id["N-1"].withdrawn == Withdrawal(reason="won't do", date="2026-10-10")

    assert main(["reinstate", "N-1", "--config", str(cfg)]) == 0
    capsys.readouterr()
    assert "withdrawn:" not in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert load(Config.load(cfg)).needs[0].withdrawn is None


def test_withdraw_default_date_is_today(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from datetime import date

    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a live need\n")
    main(["withdraw", "N-1", "--reason", "nope", "--config", str(cfg)])
    capsys.readouterr()
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert by_id["N-1"].withdrawn is not None
    assert by_id["N-1"].withdrawn.date == date.today().isoformat()


def test_reinstate_on_non_withdrawn_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a live need\n")
    code = main(["reinstate", "N-1", "--config", str(cfg)])
    assert code == 2
    assert "not withdrawn" in capsys.readouterr().err


def test_withdraw_dry_run_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a live need\n")
    main(["withdraw", "N-1", "--reason", "maybe", "--dry-run", "--config", str(cfg)])
    capsys.readouterr()
    assert "withdrawn:" not in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")


# --- show / json payloads ---------------------------------------------------


def test_show_renders_withdrawn_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["show", "W-1", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "withdrawn: superseded by N-1 (2026-10-10)" in out


def test_show_json_carries_withdrawn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["show", "W-1", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["withdrawn"] == {"reason": "superseded by N-1", "date": "2026-10-10"}


def test_status_json_live_need_has_null_withdrawn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    n1 = next(n for n in payload["needs"] if n["id"] == "N-1")
    assert n1["withdrawn"] is None
