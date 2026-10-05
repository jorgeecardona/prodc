"""External-behaviour proof adapter (#25): assert an observable outcome from a recorded result."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.adapters import OutcomeAdapter
from prodc.config import Config, ConfigError
from prodc.model import ProofState


def _adapter(tmp_path: Path, results: dict[str, object] | None) -> OutcomeAdapter:
    if results is not None:
        (tmp_path / "outcomes.json").write_text(json.dumps(results), encoding="utf-8")
    return OutcomeAdapter(root=tmp_path, results="outcomes.json")


def test_recorded_pass_is_delivered(tmp_path: Path) -> None:
    r = _adapter(tmp_path, {"checkout-returns-200": True}).resolve("checkout-returns-200")
    assert r.state is ProofState.DELIVERED and r.declared is False


def test_recorded_fail_is_pending(tmp_path: Path) -> None:
    r = _adapter(tmp_path, {"checkout-returns-200": False}).resolve("checkout-returns-200")
    assert r.state is ProofState.PENDING


def test_key_absent_from_present_file_is_pending(tmp_path: Path) -> None:
    r = _adapter(tmp_path, {"other": True}).resolve("checkout-returns-200")
    assert r.state is ProofState.PENDING and "not in results" in r.detail


def test_missing_results_file_is_broken(tmp_path: Path) -> None:
    r = _adapter(tmp_path, None).resolve("checkout-returns-200")
    assert r.state is ProofState.BROKEN and "no results file" in r.detail


def test_nested_passed_object_form(tmp_path: Path) -> None:
    r = _adapter(tmp_path, {"login-flow": {"passed": True}}).resolve("login-flow")
    assert r.state is ProofState.DELIVERED


def test_config_wires_external_kind(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n'
        '[proofs.api]\nkind = "external"\nresults = "outcomes.json"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    assert isinstance(cfg.adapters["api"], OutcomeAdapter)


def test_config_external_requires_results(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n[proofs.api]\nkind = "external"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="external needs results"):
        Config.load(tmp_path / "prodc.toml")
