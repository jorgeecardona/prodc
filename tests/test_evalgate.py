"""The `evalgate` proof adapter (research-board step 4, #75): a scored sibling of the external
(OutcomeAdapter) proof. It reads a numeric eval score from a results file and gates it against a
threshold carried in the locator (`accuracy>=0.9`), so one adapter serves many metrics and cutoffs.
Records-only — prodc reads the recorded score, never runs the eval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.adapters import EvalGateAdapter
from prodc.config import Config, ConfigError
from prodc.model import ProofState


def _adapter(tmp_path: Path, results: object, name: str = "eval.json") -> EvalGateAdapter:
    (tmp_path / name).write_text(json.dumps(results), encoding="utf-8")
    return EvalGateAdapter(root=tmp_path, results=name)


def test_delivered_when_score_meets_gate(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"accuracy": {"score": 0.82}})
    r = a.resolve("accuracy>=0.8")
    assert r.state is ProofState.DELIVERED
    assert "0.82" in r.detail and "pass" in r.detail


def test_pending_when_score_below_gate(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"accuracy": {"score": 0.72}})
    r = a.resolve("accuracy>=0.8")
    assert r.state is ProofState.PENDING  # recorded, but not green
    assert "below gate" in r.detail


def test_bare_number_is_accepted_as_a_score(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"f1": 0.9})
    assert a.resolve("f1>=0.9").state is ProofState.DELIVERED  # >= is inclusive


def test_less_than_gate_for_a_loss_metric(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"val_loss": {"score": 0.15}})
    assert a.resolve("val_loss<=0.2").state is ProofState.DELIVERED
    assert a.resolve("val_loss<=0.1").state is ProofState.PENDING


def test_strict_operators(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"m": 0.5})
    assert a.resolve("m>0.5").state is ProofState.PENDING  # strict: 0.5 is not > 0.5
    assert a.resolve("m<0.6").state is ProofState.DELIVERED


def test_pending_when_metric_absent_from_present_file(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"accuracy": {"score": 0.82}})
    r = a.resolve("recall>=0.8")
    assert r.state is ProofState.PENDING  # file read, metric not recorded yet
    assert "not in results" in r.detail


def test_broken_when_results_file_absent(tmp_path: Path) -> None:
    a = EvalGateAdapter(root=tmp_path, results="missing.json")  # never written
    r = a.resolve("accuracy>=0.8")
    assert r.state is ProofState.BROKEN
    assert "no results file" in r.detail


def test_broken_on_malformed_locator(tmp_path: Path) -> None:
    a = _adapter(tmp_path, {"accuracy": {"score": 0.82}})
    assert a.resolve("accuracy").state is ProofState.BROKEN  # no operator
    assert a.resolve("accuracy>=high").state is ProofState.BROKEN  # threshold not a number


def test_bool_is_not_a_score(tmp_path: Path) -> None:
    # a pass/fail bool belongs to the external adapter, not the gate — treated as absent
    a = _adapter(tmp_path, {"flag": True})
    assert a.resolve("flag>=0.5").state is ProofState.PENDING


# --- config wiring ----------------------------------------------------------


def test_config_builds_evalgate_adapter(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n\n'
        '[proofs.eval]\nkind = "evalgate"\nresults = "eval.json"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    assert isinstance(cfg.adapters["eval"], EvalGateAdapter)


def test_config_evalgate_requires_results(tmp_path: Path) -> None:
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n\n[proofs.eval]\nkind = "evalgate"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="evalgate needs results"):
        Config.load(tmp_path / "prodc.toml")
