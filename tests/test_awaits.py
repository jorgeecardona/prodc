"""A decision's ``awaits`` (#93): the research it waits on, as needs, with derived readiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.adapters import AcceptAdapter, Adapter
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Answer, Decision, Model, Need, ProofState
from prodc.status import decision_readiness

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
    product: false
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
