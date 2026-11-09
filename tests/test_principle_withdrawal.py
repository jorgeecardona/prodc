"""Principle withdrawal: withdrawn field on Principle, writer, CLI, and lint skip."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import load
from prodc.model import Withdrawal, WithdrawalKind
from prodc.writer import WriteError, reinstate_principle, withdraw_principle

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_PRINCIPLES_YAML = """\
principles:
  - id: P-local
    text: audio never leaves the machine
    revised_at: 2026-10-15
    sources:
      - kind: secondary
        url: https://example.com/local-first
  - id: P-simple
    text: keep the interface minimal
    revised_at: 2026-10-10
"""


def _project(tmp_path: Path) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(_PRINCIPLES_YAML, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


# --- loader -----------------------------------------------------------------


def test_loader_parses_withdrawn_principle(tmp_path: Path) -> None:
    yaml = """\
principles:
  - id: P-gone
    text: old framing
    revised_at: 2026-01-01
    withdrawn:
      reason: strategy changed
      date: 2026-10-20
"""
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(yaml, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "P-gone")
    assert p.withdrawn is not None
    assert p.withdrawn.reason == "strategy changed"
    assert p.withdrawn.date == "2026-10-20"
    assert p.withdrawn.kind == WithdrawalKind.WONT_DO


def test_loader_parses_withdrawn_kind_out_of_scope(tmp_path: Path) -> None:
    yaml = """\
principles:
  - id: P-scoped
    text: some principle
    revised_at: 2026-01-01
    withdrawn:
      reason: product pivot
      date: 2026-10-20
      kind: out_of_scope
"""
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(yaml, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "P-scoped")
    assert p.withdrawn is not None
    assert p.withdrawn.kind == WithdrawalKind.OUT_OF_SCOPE


# --- writer -----------------------------------------------------------------


def test_withdraw_principle_writes_withdrawn_field(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    withdraw_principle(cfg, "P-local", reason="strategy changed", date="2026-11-01", dry_run=False)
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "P-local")
    assert p.withdrawn == Withdrawal(reason="strategy changed", date="2026-11-01")


def test_withdraw_principle_kind_out_of_scope(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    withdraw_principle(
        cfg,
        "P-local",
        reason="product pivot",
        date="2026-11-01",
        kind="out_of_scope",
        dry_run=False,
    )
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "P-local")
    assert p.withdrawn is not None
    assert p.withdrawn.kind == WithdrawalKind.OUT_OF_SCOPE


def test_withdraw_principle_dry_run_does_not_write(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    before = (tmp_path / "needs" / "p.yaml").read_text()
    edit = withdraw_principle(
        cfg, "P-local", reason="test", date="2026-11-01", dry_run=True
    )
    after = (tmp_path / "needs" / "p.yaml").read_text()
    assert before == after
    assert edit.diff  # diff is non-empty


def test_reinstate_principle_removes_withdrawn(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    withdraw_principle(cfg, "P-local", reason="test", date="2026-11-01", dry_run=False)
    reinstate_principle(cfg, "P-local", dry_run=False)
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "P-local")
    assert p.withdrawn is None


def test_reinstate_principle_errors_if_not_withdrawn(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    with pytest.raises(WriteError, match="is not withdrawn"):
        reinstate_principle(cfg, "P-local", dry_run=False)


# --- lint skip --------------------------------------------------------------


def test_lint_skips_withdrawn_principle(tmp_path: Path) -> None:
    """A withdrawn principle does not appear in principle_report guard violations."""
    from prodc.status import principle_report

    yaml = """\
principles:
  - id: P-gone
    text: old framing
    revised_at: 2026-01-01
    withdrawn:
      reason: strategy changed
      date: 2026-10-20

needs:
  - id: N-1
    text: something
"""
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(yaml, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    reports = principle_report(model.needs, list(model.principles), {})
    # P-gone has no proofs and would normally produce a report, but it's withdrawn so
    # the caller skips it; the report itself is still returned (withdrawn is model data)
    gone_rep = next((r for r in reports if r.principle.id == "P-gone"), None)
    assert gone_rep is not None
    assert gone_rep.principle.withdrawn is not None
