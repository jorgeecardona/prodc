"""Write-back: prodc set / add need, validated against the loader (#24)."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import load
from prodc.writer import WriteError, add_need, set_field


def _proj(tmp_path: Path, body: str) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "needs" / "a.yaml").write_text(body, encoding="utf-8")
    return Config(root=tmp_path, need_globs=["needs/*.yaml"])


def _a_yaml(cfg: Config) -> str:
    return (cfg.root / "needs" / "a.yaml").read_text(encoding="utf-8")


def test_set_scalar_field_and_reload(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: old\n")
    set_field(cfg, "N-1", "text=the owner can cancel", expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].text == "the owner can cancel"


def test_set_must_coerces_bool(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    set_field(cfg, "N-1", "must=true", expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].must is True


def test_set_appends_proof(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    set_field(cfg, "N-1", "proofs+=web:orders.feature#Done", expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].proofs == ("web:orders.feature#Done",)


def test_set_unknown_field_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="cannot set 'bogus'"):
        set_field(cfg, "N-1", "bogus=1", expect_sha=None, dry_run=False)


def test_set_dry_run_leaves_file_but_returns_diff(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: old\n")
    before = _a_yaml(cfg)
    edit = set_field(cfg, "N-1", "text=new", expect_sha=None, dry_run=True)
    assert _a_yaml(cfg) == before  # nothing written
    assert "new" in edit.diff and edit.diff.startswith("---")


def test_set_rejected_edit_reverts(tmp_path: Path) -> None:
    # goal must reference a known goal; setting an unknown one must fail AND restore the file
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    before = _a_yaml(cfg)
    with pytest.raises(WriteError, match="edit rejected"):
        set_field(cfg, "N-1", "goal=GHOST", expect_sha=None, dry_run=False)
    assert _a_yaml(cfg) == before  # reverted


def test_optimistic_lock(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="changed since it was read"):
        set_field(cfg, "N-1", "text=x", expect_sha="deadbeef", dry_run=False)


def test_add_need_carries_agent_provenance(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    add_need(
        cfg,
        "N-2",
        "the roaster can pause a batch",
        who="agent:claude",
        kind="internal",
        file="needs/a.yaml",
        expect_sha=None,
        dry_run=False,
    )
    by_id = {n.id: n for n in load(cfg).needs}
    assert "N-2" in by_id and not by_id["N-2"].is_opinion  # never a silent opinion
    src = by_id["N-2"].sources[0]
    assert src.who == "agent:claude" and src.date == datetime.date.today().isoformat()


def test_add_need_rejects_interview_kind(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="proxy or internal"):
        add_need(
            cfg,
            "N-2",
            "t",
            who="agent",
            kind="interview",
            file="needs/a.yaml",
            expect_sha=None,
            dry_run=False,
        )


def test_add_need_duplicate_id_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="already exists"):
        add_need(
            cfg,
            "N-1",
            "t",
            who="agent",
            kind="internal",
            file="needs/a.yaml",
            expect_sha=None,
            dry_run=False,
        )


def test_add_need_outside_glob_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="does not match any"):
        add_need(
            cfg,
            "N-2",
            "t",
            who="agent",
            kind="internal",
            file="outside.yaml",
            expect_sha=None,
            dry_run=False,
        )
