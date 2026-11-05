"""A decision's ``awaits`` (#93): the research it waits on, as needs, with derived readiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.adapters import AcceptAdapter, Adapter
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Answer, Decision, Model, Need, ProofState
from prodc.status import awaits_warnings, decision_readiness

_ADAPTERS: dict[str, Adapter] = {"accept": AcceptAdapter()}


def _research(nid: str, *, settled: bool, answer: Answer | None = None) -> Need:
    return Need(
        id=nid,
        text=f"research {nid}",
        claim="a hypothesis",
        product=False,
        proofs=("accept:jordan@2026-10-20",) if settled else (),
        answer=answer,
    )


def _decision(*awaits: str) -> Decision:
    return Decision(id="D-1", text="a ledger", needs=("US-1",), awaits=awaits)


_US = Need(id="US-1", text="see stock")


def test_no_awaits_is_absent() -> None:
    d = Decision(id="D-1", text="x", needs=("US-1",))
    assert decision_readiness([d], [_US], _ADAPTERS) == {}


def test_unsettled_research_blocks() -> None:
    r = decision_readiness([_decision("Q-1")], [_US, _research("Q-1", settled=False)], _ADAPTERS)
    assert r["D-1"].blocked and r["D-1"].open_refs == ["Q-1"]
    assert r["D-1"].waits[0].state is ProofState.PENDING  # HOLE need → not settled


def test_settled_research_is_ready() -> None:
    r = decision_readiness([_decision("Q-1")], [_US, _research("Q-1", settled=True)], _ADAPTERS)
    assert not r["D-1"].blocked and r["D-1"].open_refs == []


def test_direction_must_match() -> None:
    yes = _research("Q-1", settled=True, answer=Answer.YES)
    no = _research("Q-2", settled=True, answer=Answer.NO)
    r = decision_readiness([_decision("Q-1@yes", "Q-2@yes")], [_US, yes, no], _ADAPTERS)["D-1"]
    assert r.open_refs == ["Q-2@yes"]  # settled NO, but the decision wanted YES
    assert "awaiting 'yes'" in r.waits[1].detail


def test_settled_without_answer_waits_on_direction() -> None:
    q = _research("Q-1", settled=True)
    r = decision_readiness([_decision("Q-1@yes")], [_US, q], _ADAPTERS)["D-1"]
    assert r.blocked and "no answer recorded" in r.waits[0].detail


def test_readiness_does_not_touch_need_states() -> None:
    from prodc.status import resolve

    q = _research("Q-1", settled=False)
    before = {r.need.id: r.state for r in resolve([_US, q], _ADAPTERS)}
    decision_readiness([_decision("Q-1")], [_US, q], _ADAPTERS)
    after = {r.need.id: r.state for r in resolve([_US, q], _ADAPTERS)}
    assert before == after


# --- loader -----------------------------------------------------------------

_TOML = '[prodc]\nfiles = ["p/*.yaml"]\n\n[proofs.accept]\nkind = "accept"\n'
_NEEDS = """needs:
  - id: US-1
    text: see stock
  - id: Q-1
    text: roasters want derived balances
    claim: a roaster who sees a derived balance does not ask for a set-stock field
    tags: [research]
"""


def _load(tmp_path: Path, awaits: str) -> Model:
    (tmp_path / "p").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "p" / "n.yaml").write_text(
        _NEEDS
        + f"decisions:\n  - id: D-1\n    text: a ledger\n    needs: [US-1]\n    awaits: {awaits}\n",
        encoding="utf-8",
    )
    return load(Config.load(tmp_path / "prodc.toml"))


def test_loader_parses_awaits(tmp_path: Path) -> None:
    model = _load(tmp_path, "[Q-1@yes]")
    assert model.decisions[0].awaits == ("Q-1@yes",)


def test_loader_rejects_unknown_need(tmp_path: Path) -> None:
    with pytest.raises(LoaderError, match="awaits 'Q-9' is not a known need id"):
        _load(tmp_path, "[Q-9]")


def test_loader_rejects_bad_direction(tmp_path: Path) -> None:
    with pytest.raises(LoaderError, match="unknown answer 'maybe'"):
        _load(tmp_path, "[Q-1@maybe]")


def test_loader_rejects_serves_and_awaits_same_need(tmp_path: Path) -> None:
    with pytest.raises(LoaderError, match="in both needs"):
        _load(tmp_path, "[US-1]")


# --- surfacing: lint / show / status (#93 step 2) ----------------------------


def _warns(d: Decision, *needs: Need) -> list[str]:
    all_needs = [_US, *needs]
    return [
        w for _, w in awaits_warnings([d], all_needs, decision_readiness([d], all_needs, _ADAPTERS))
    ]


def test_lint_committed_before_research_settled() -> None:
    w = _warns(_decision("Q-1"), _research("Q-1", settled=False))
    assert any("committed before its research settled: Q-1" in x for x in w)


def test_lint_draft_waiting_is_fine() -> None:
    d = Decision(id="D-1", text="x", needs=("US-1",), awaits=("Q-1",), draft=True)
    assert _warns(d, _research("Q-1", settled=False)) == []


def test_lint_decided_against_its_research() -> None:
    w = _warns(_decision("Q-1@yes"), _research("Q-1", settled=True, answer=Answer.NO))
    assert any("answered no: decided against its research" in x for x in w)


def test_lint_awaits_withdrawn_need() -> None:
    from prodc.model import Withdrawal, WithdrawalKind

    q = Need(
        id="Q-1",
        text="r",
        product=False,
        proofs=("accept:j@2026-10-20",),
        withdrawn=Withdrawal(reason="dropped", date="2026-10-20", kind=WithdrawalKind.WONT_DO),
    )
    assert any("which is withdrawn" in x for x in _warns(_decision("Q-1"), q))


def _cli_project(tmp_path: Path, awaits: str, draft: bool = False) -> Path:
    (tmp_path / "p").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "p" / "n.yaml").write_text(
        _NEEDS
        + "decisions:\n  - id: D-1\n    text: a ledger\n    needs: [US-1]\n"
        + f"    awaits: {awaits}\n"
        + ("    draft: true\n" if draft else ""),
        encoding="utf-8",
    )
    return tmp_path / "prodc.toml"


def test_show_decision_blocked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    assert main(["show", "D-1", "--config", str(_cli_project(tmp_path, "[Q-1]", True))]) == 0
    out = capsys.readouterr().out
    assert "D-1 (proposed) BLOCKED: Q-1" in out
    assert "awaits (0 of 1 settled):" in out


def test_show_decision_json_readiness(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from prodc.cli import main

    cfg = _cli_project(tmp_path, "[Q-1]", True)
    assert main(["show", "D-1", "--json", "--config", str(cfg)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["awaits"] == ["Q-1"]
    assert payload["readiness"]["blocked"] is True


def test_status_tags_blocked_decision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_cli_project(tmp_path, "[Q-1]", True))])
    assert "D-1    (proposed) BLOCKED: Q-1 a ledger" in capsys.readouterr().out


def test_lint_command_warns_committed_early(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    code = main(["lint", "--config", str(_cli_project(tmp_path, "[Q-1]"))])
    out = capsys.readouterr().out
    assert "D-1: committed before its research settled: Q-1" in out
    assert code == 0  # a warning, not a gate failure


# --- the setter: set D-1 awaits+= / awaits-= ----------------------------------


def _set(cfg: Path, *args: str) -> int:
    from prodc.cli import main

    return main(["set", *args, "--config", str(cfg)])


def test_set_awaits_append_and_remove(tmp_path: Path) -> None:
    cfg = _cli_project(tmp_path, "[]", True)
    yaml_path = tmp_path / "p" / "n.yaml"
    yaml_path.write_text("# research board\n" + yaml_path.read_text(), encoding="utf-8")
    assert _set(cfg, "D-1", "awaits+=Q-1@yes") == 0
    assert load(Config.load(cfg)).decisions[0].awaits == ("Q-1@yes",)
    assert yaml_path.read_text().startswith("# research board\n")  # comments survive the splice
    assert _set(cfg, "D-1", "awaits-=Q-1@yes") == 0
    assert load(Config.load(cfg)).decisions[0].awaits == ()
    assert "awaits" not in yaml_path.read_text()  # last entry gone → key removed


def test_set_awaits_refuses_unknown_need_and_leaves_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cli_project(tmp_path, "[]", True)
    before = (tmp_path / "p" / "n.yaml").read_text()
    assert _set(cfg, "D-1", "awaits+=Q-9") != 0  # the reload gate rejects it
    assert (tmp_path / "p" / "n.yaml").read_text() == before
    assert "not a known need id" in capsys.readouterr().err


def test_set_awaits_refuses_duplicate_and_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cli_project(tmp_path, "[Q-1]", True)
    assert _set(cfg, "D-1", "awaits+=Q-1") != 0
    assert "already awaits" in capsys.readouterr().err
    assert _set(cfg, "D-1", "awaits-=Q-2") != 0
    assert "does not await" in capsys.readouterr().err


def test_set_awaits_on_a_need_id_says_no_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cli_project(tmp_path, "[]", True)
    assert _set(cfg, "US-1", "awaits+=Q-1") != 0
    assert "no decision 'US-1'" in capsys.readouterr().err


def test_withdraw_and_reinstate_decision_still_work(tmp_path: Path) -> None:
    from prodc.writer import reinstate_decision, withdraw_decision

    cfg = Config.load(_cli_project(tmp_path, "[Q-1]", True))
    withdraw_decision(cfg, "D-1", reason="superseded", date="2026-10-20", dry_run=False)
    assert load(cfg).decisions[0].withdrawn is not None
    reinstate_decision(cfg, "D-1", dry_run=False)
    assert load(cfg).decisions[0].withdrawn is None
