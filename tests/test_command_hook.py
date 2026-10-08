"""CommandProof / CommandSource: the generic command-backed hook adapters (#70).

Tests inject a fake ``_runner`` so no process is spawned: the runner returns the
parsed-JSON object a real hook would print, or ``None`` for "could not read" (non-zero
exit, timeout, spawn failure, unparseable output). ``_hook_argv`` is tested directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.adapters import (
    CommandProof,
    CommandSource,
    ProofState,
)
from prodc.config import Config, ConfigError

# ---------------------------------------------------------------------------
# argv construction: locator is an argv element, never a shell string
# ---------------------------------------------------------------------------


def _captured_argv(command: list[str], locator: str) -> list[str]:
    """Run a CommandProof with a spy runner and return the argv it built."""
    seen: list[list[str]] = []

    def spy(argv: list[str], cwd: Path, timeout: float) -> object:
        seen.append(argv)
        return {"state": "pending"}

    CommandProof(root=Path("."), command=command, _runner=spy).resolve(locator)
    return seen[0]


def test_argv_appends_locator_when_no_placeholder() -> None:
    assert _captured_argv(["./hook.sh"], "JIRA-7") == ["./hook.sh", "JIRA-7"]


def test_argv_substitutes_placeholder_in_place() -> None:
    argv = _captured_argv(["tool", "--id", "{locator}", "--json"], "JIRA-7")
    assert argv == ["tool", "--id", "JIRA-7", "--json"]


def test_argv_substitutes_every_placeholder_and_does_not_append() -> None:
    assert _captured_argv(["tool", "{locator}", "{locator}"], "x") == ["tool", "x", "x"]


def test_argv_passes_shell_metachars_as_one_literal_arg() -> None:
    # A locator with shell metacharacters stays a single argv element — no injection.
    assert _captured_argv(["./hook.sh"], "; rm -rf / #") == ["./hook.sh", "; rm -rf / #"]


# ---------------------------------------------------------------------------
# CommandProof: maps the hook's JSON state to a ProofState
# ---------------------------------------------------------------------------


def _proof(result: object | None) -> CommandProof:
    return CommandProof(
        root=Path("."),
        command=["./hook.sh"],
        _runner=lambda argv, cwd, timeout: result,
    )


def test_proof_delivered() -> None:
    r = _proof({"state": "delivered", "detail": "JIRA-7 closed"}).resolve("JIRA-7")
    assert r.state is ProofState.DELIVERED
    assert r.detail == "JIRA-7 closed"
    assert r.declared is False


def test_proof_pending() -> None:
    r = _proof({"state": "pending"}).resolve("JIRA-7")
    assert r.state is ProofState.PENDING
    assert "pending" in r.detail  # falls back to the state name when no detail


def test_proof_broken() -> None:
    r = _proof({"state": "broken", "detail": "no such ticket"}).resolve("JIRA-9")
    assert r.state is ProofState.BROKEN
    assert r.detail == "no such ticket"


def test_proof_could_not_read_is_unresolved_not_a_false_pass() -> None:
    # None == non-zero exit / timeout / spawn failure / unparseable output.
    r = _proof(None).resolve("JIRA-7")
    assert r.state is ProofState.UNRESOLVED
    assert "could not read" in r.detail


def test_proof_unknown_state_is_unresolved() -> None:
    r = _proof({"state": "shipped"}).resolve("JIRA-7")
    assert r.state is ProofState.UNRESOLVED
    assert "unknown state" in r.detail


def test_proof_non_object_output_is_unresolved() -> None:
    r = _proof(["not", "an", "object"]).resolve("JIRA-7")
    assert r.state is ProofState.UNRESOLVED


def test_proof_missing_state_is_unresolved() -> None:
    r = _proof({"detail": "no state key"}).resolve("JIRA-7")
    assert r.state is ProofState.UNRESOLVED


# ---------------------------------------------------------------------------
# CommandSource: exists -> ok=True; absent -> BROKEN; unreadable -> unverified
# ---------------------------------------------------------------------------


def _source(result: object | None) -> CommandSource:
    return CommandSource(
        root=Path("."),
        command=["./hook.sh"],
        _runner=lambda argv, cwd, timeout: result,
    )


def test_source_exists_builds_provenance_detail() -> None:
    r = _source(
        {"exists": True, "who": "ana", "date": "2026-09-01", "quote": "we lose data"}
    ).resolve("JIRA-7")
    assert r.ok is True
    assert "by ana" in r.detail
    assert "at 2026-09-01" in r.detail
    assert "we lose data" in r.detail


def test_source_exists_minimal() -> None:
    r = _source({"exists": True}).resolve("JIRA-7")
    assert r.ok is True
    assert r.detail == "exists"


def test_source_absent_is_broken() -> None:
    r = _source({"exists": False}).resolve("JIRA-9")
    assert r.ok is False
    assert r.detail == "not found"


def test_source_absent_carries_detail() -> None:
    r = _source({"exists": False, "detail": "deleted ticket"}).resolve("JIRA-9")
    assert r.ok is False
    assert r.detail == "deleted ticket"


def test_source_could_not_read_is_unverified_not_broken() -> None:
    r = _source(None).resolve("JIRA-7")
    assert r.ok is True  # never a false BROKEN
    assert "unverified" in r.detail


def test_source_missing_exists_is_unverified() -> None:
    r = _source({"who": "ana"}).resolve("JIRA-7")
    assert r.ok is True
    assert "unverified" in r.detail


# ---------------------------------------------------------------------------
# Real subprocess: the default runner actually spawns and parses (no injection)
# ---------------------------------------------------------------------------


def _script(tmp_path: Path, body: str) -> list[str]:
    fp = tmp_path / "hook.sh"
    fp.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    fp.chmod(0o755)
    return [str(fp)]


def test_real_hook_delivered(tmp_path: Path) -> None:
    # The locator arrives as $1; the hook echoes a JSON object.
    cmd = _script(tmp_path, 'printf \'{"state": "delivered", "detail": "saw %s"}\' "$1"')
    r = CommandProof(root=tmp_path, command=cmd).resolve("TICKET-1")
    assert r.state is ProofState.DELIVERED
    assert r.detail == "saw TICKET-1"


def test_real_hook_nonzero_exit_is_unresolved(tmp_path: Path) -> None:
    cmd = _script(tmp_path, "exit 3")
    r = CommandProof(root=tmp_path, command=cmd).resolve("x")
    assert r.state is ProofState.UNRESOLVED
    assert "could not read" in r.detail


def test_real_hook_garbage_stdout_is_unresolved(tmp_path: Path) -> None:
    cmd = _script(tmp_path, "echo not json")
    r = CommandProof(root=tmp_path, command=cmd).resolve("x")
    assert r.state is ProofState.UNRESOLVED


def test_real_hook_missing_binary_is_unresolved(tmp_path: Path) -> None:
    r = CommandProof(
        root=tmp_path, command=[str(tmp_path / "does-not-exist")]
    ).resolve("x")
    assert r.state is ProofState.UNRESOLVED


def test_real_hook_timeout_is_unresolved(tmp_path: Path) -> None:
    cmd = _script(tmp_path, "sleep 5")
    r = CommandProof(root=tmp_path, command=cmd, timeout=0.2).resolve("x")
    assert r.state is ProofState.UNRESOLVED


def test_real_source_hook_exists(tmp_path: Path) -> None:
    cmd = _script(tmp_path, 'printf \'{"exists": true, "who": "ana"}\'')
    r = CommandSource(root=tmp_path, command=cmd).resolve("JIRA-7")
    assert r.ok is True
    assert "by ana" in r.detail


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, body: str) -> Config:
    (tmp_path / "needs").mkdir(exist_ok=True)
    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nneeds = ["needs/*.yaml"]\n' + body, encoding="utf-8"
    )
    return Config.load(tmp_path / "prodc.toml")


def test_config_wires_command_proof(tmp_path: Path) -> None:
    cfg = _write_toml(
        tmp_path,
        '[proofs.jira]\nkind = "command"\ncommand = ["./hook.sh"]\ntimeout = 5\n',
    )
    assert isinstance(cfg.adapters["jira"], CommandProof)


def test_config_wires_command_source(tmp_path: Path) -> None:
    cfg = _write_toml(
        tmp_path,
        '[sources.feedback]\nkind = "command"\ncommand = ["./resolve.sh", "{locator}"]\n',
    )
    assert isinstance(cfg.source_adapters["feedback"], CommandSource)


def test_config_command_requires_non_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non-empty"):
        _write_toml(tmp_path, '[proofs.jira]\nkind = "command"\ncommand = []\n')


def test_config_command_rejects_non_positive_timeout(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="positive number"):
        _write_toml(
            tmp_path,
            '[proofs.jira]\nkind = "command"\ncommand = ["./h.sh"]\ntimeout = 0\n',
        )
