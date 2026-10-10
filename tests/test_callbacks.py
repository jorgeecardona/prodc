"""Lifecycle callbacks: `prodc sync` fires a command when a need changes state (#71).

Engine tests inject a fake invoker (no process spawns); the CLI tests use a tiny real script in
tmp_path, like the command-hook tests, to exercise the actual subprocess + stdin path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.callbacks import (
    Callback,
    Fired,
    Transition,
    advance_ledger,
    fire,
    read_ledger,
    transitions,
    write_ledger,
)
from prodc.cli import main
from prodc.config import Config, ConfigError
from prodc.model import Need

# ---------------------------------------------------------------------------
# Pure engine
# ---------------------------------------------------------------------------


def test_transitions_detects_changes_ignores_new_and_unchanged() -> None:
    ledger = {"N-1": "pending", "N-2": "delivered"}
    current = {"N-1": "delivered", "N-2": "delivered", "N-3": "hole"}  # N-3 is new
    assert transitions(ledger, current) == [Transition("N-1", "pending", "delivered")]


def test_callback_matches_from_and_to_filters() -> None:
    cb = Callback("state_change", ("x",), on_to=frozenset({"delivered"}))
    assert cb.matches("pending", "delivered")
    assert not cb.matches("delivered", "pending")
    cb2 = Callback("state_change", ("x",), on_from=frozenset({"pending"}))
    assert cb2.matches("pending", "broken")
    assert not cb2.matches("hole", "broken")
    assert Callback("state_change", ("x",)).matches("a", "b")  # no filter = any


def _need(nid: str) -> Need:
    return Need(id=nid, text=f"text {nid}", who="ana", client="acme", must=True)


def test_fire_pipes_payload_and_runs_only_matching() -> None:
    seen: list[str] = []

    def spy(cmd: tuple[str, ...], payload: str, cwd: Path, timeout: float) -> tuple[bool, str]:
        seen.append(payload)
        return True, "ok"

    cbs = [
        Callback("state_change", ("notify",), on_to=frozenset({"delivered"})),
        Callback("state_change", ("other",), on_to=frozenset({"broken"})),  # must not fire
    ]
    trans = [Transition("N-1", "pending", "delivered")]
    fired = fire(
        trans,
        cbs,
        context={"N-1": _need("N-1")},
        board={"coverage_pct": 50},
        cwd=Path("."),
        invoke=spy,
    )
    assert len(fired) == 1 and fired[0].ok and fired[0].command == ("notify",)
    payload = json.loads(seen[0])
    assert payload["from"] == "pending" and payload["to"] == "delivered"
    assert payload["need"]["id"] == "N-1" and payload["need"]["must"] is True
    assert payload["board"]["coverage_pct"] == 50


def test_advance_ledger_keeps_failed_need_for_retry() -> None:
    current = {"N-1": "delivered", "N-2": "broken"}
    ledger = {"N-1": "pending", "N-2": "pending"}
    fired = [
        Fired(Transition("N-1", "pending", "delivered"), ("ok",), True, "ok"),
        Fired(Transition("N-2", "pending", "broken"), ("bad",), False, "exit 1"),
    ]
    out = advance_ledger(current, ledger, fired)
    assert out == {"N-1": "delivered", "N-2": "pending"}  # N-2 held back for retry


def test_ledger_round_trip_and_missing(tmp_path: Path) -> None:
    p = tmp_path / ".prodc" / "state.json"
    assert read_ledger(p) is None  # absent = first run
    write_ledger(p, {"N-1": "delivered"})
    assert read_ledger(p) == {"N-1": "delivered"}
    p.write_text("not json", encoding="utf-8")
    assert read_ledger(p) is None  # malformed = treat as first run, never crash


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

_BASE = '[prodc]\nneeds = ["needs/*.yaml"]\n'


def _cfg(tmp_path: Path, body: str) -> Config:
    (tmp_path / "needs").mkdir(exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_BASE + body, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def test_config_parses_hooks_and_filters(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        '[callbacks]\nstate_file = ".prodc/s.json"\n'
        '[[callbacks.hooks]]\non = "state_change"\nto = ["delivered", "broken"]\n'
        'command = ["./notify.sh"]\ntimeout = 20\n',
    )
    assert cfg.callback_state_file == ".prodc/s.json"
    assert len(cfg.callbacks) == 1
    cb = cfg.callbacks[0]
    assert cb.command == ("./notify.sh",) and cb.timeout == 20.0
    assert cb.on_to == frozenset({"delivered", "broken"})


def test_config_rejects_unknown_event(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="state_change"):
        _cfg(tmp_path, '[[callbacks.hooks]]\non = "on_capture"\ncommand = ["x"]\n')


def test_config_rejects_unknown_state(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown state"):
        _cfg(
            tmp_path,
            '[[callbacks.hooks]]\non = "state_change"\nto = ["shipped"]\ncommand = ["x"]\n',
        )


def test_config_rejects_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non-empty"):
        _cfg(tmp_path, '[[callbacks.hooks]]\non = "state_change"\ncommand = []\n')


# ---------------------------------------------------------------------------
# CLI `sync` (real subprocess)
# ---------------------------------------------------------------------------

_TOML_CB = (
    _BASE
    + '[proofs.web]\nkind = "gherkin"\npaths = ["features/*.feature"]\ndelivered = ["@implemented"]\n'
    + '[[callbacks.hooks]]\non = "state_change"\nto = ["delivered"]\ncommand = ["./notify.sh"]\n'
)
_NEED = 'needs:\n  - id: N-1\n    text: see past-due orders\n    proofs: ["web:orders.feature#S"]\n'


def _feature(delivered: bool) -> str:
    tag = "  @implemented\n" if delivered else ""
    return f"Feature: orders\n{tag}  Scenario: S\n    Given x\n    Then y\n"


def _project(tmp_path: Path, *, delivered: bool) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML_CB, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEED, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_feature(delivered), encoding="utf-8")
    script = tmp_path / "notify.sh"
    script.write_text("#!/bin/sh\ncat >> fired.log\nprintf '\\n' >> fired.log\n", encoding="utf-8")
    script.chmod(0o755)
    return tmp_path / "prodc.toml"


def _sync(cfg: Path, *extra: str) -> int:
    return main(["sync", "--config", str(cfg), *extra])


def test_sync_first_run_is_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path, delivered=False)
    assert _sync(cfg) == 0
    assert "baseline" in capsys.readouterr().out
    assert (tmp_path / ".prodc" / "state.json").exists()
    assert not (tmp_path / "fired.log").exists()  # nothing fired on first run


def test_sync_fires_on_transition(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path, delivered=False)
    _sync(cfg)  # baseline (pending)
    (tmp_path / "features" / "orders.feature").write_text(_feature(True), encoding="utf-8")
    assert _sync(cfg) == 0
    out = capsys.readouterr().out
    assert "pending → delivered" in out
    payload = json.loads((tmp_path / "fired.log").read_text(encoding="utf-8").strip())
    assert payload["need"]["id"] == "N-1" and payload["to"] == "delivered"


def test_sync_failing_callback_exits_nonzero_and_retries(tmp_path: Path) -> None:
    cfg = _project(tmp_path, delivered=False)
    _sync(cfg)
    (tmp_path / "notify.sh").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    (tmp_path / "notify.sh").chmod(0o755)
    (tmp_path / "features" / "orders.feature").write_text(_feature(True), encoding="utf-8")
    assert _sync(cfg) == 1  # a failed callback makes sync exit non-zero
    ledger = json.loads((tmp_path / ".prodc" / "state.json").read_text(encoding="utf-8"))
    assert ledger["N-1"] == "pending"  # not advanced — next sync retries


def test_sync_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path, delivered=False)
    _sync(cfg)
    (tmp_path / "features" / "orders.feature").write_text(_feature(True), encoding="utf-8")
    assert _sync(cfg, "--dry-run") == 0
    assert "would fire" in capsys.readouterr().out
    assert not (tmp_path / "fired.log").exists()  # nothing ran
    ledger = json.loads((tmp_path / ".prodc" / "state.json").read_text(encoding="utf-8"))
    assert ledger["N-1"] == "pending"  # ledger untouched
