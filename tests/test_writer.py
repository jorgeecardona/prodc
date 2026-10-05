"""Write-back: prodc set / add need, validated against the loader (#24)."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import load
from prodc.writer import WriteError, add_need, capture_source, set_field


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


def test_capture_appends_source_turns_opinion_into_sourced(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")  # opinion (no source)
    assert load(cfg).needs[0].is_opinion
    capture_source(
        cfg,
        "N-1",
        kind="interview",
        who="Ana",
        date="2026-10-05",
        quote="we need this",
        locator=None,
        expect_sha=None,
        dry_run=False,
    )
    need = load(cfg).needs[0]
    assert not need.is_opinion
    assert need.sources[0].who == "Ana" and need.sources[0].quote == "we need this"


def test_capture_bad_kind_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="source kind must be"):
        capture_source(
            cfg,
            "N-1",
            kind="rumor",
            who=None,
            date=None,
            quote=None,
            locator=None,
            expect_sha=None,
            dry_run=False,
        )


def test_accept_appends_and_is_idempotent(tmp_path: Path) -> None:
    from prodc.writer import accept

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=False,
           expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].proofs == ("accept:jorge@2026-10-05",)
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=False,
           expect_sha=None, dry_run=False)  # again
    assert load(cfg).needs[0].proofs == ("accept:jorge@2026-10-05",)  # no duplicate


def test_accept_revoke_removes(tmp_path: Path) -> None:
    from prodc.writer import accept

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: [accept:jorge@2026-10-05]\n")
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=True,
           expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].proofs == ()


def test_attest_ai_records_model_verdict_comment(tmp_path: Path) -> None:
    from prodc.model import AttestationKind
    from prodc.writer import attest

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: [web:x#y]\n")
    attest(cfg, "N-1", who="claude-opus-4-8", date="2026-10-05", kind="ai",
           verdict="pass", comment="looks right", expect_sha=None, dry_run=False)
    a = load(cfg).needs[0].attestation
    assert a is not None and a.kind is AttestationKind.AI and a.who == "claude-opus-4-8"
    assert a.verdict == "pass" and a.comment == "looks right"


def test_attest_bad_kind_rejected(tmp_path: Path) -> None:
    from prodc.writer import attest

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="human or ai"):
        attest(cfg, "N-1", who="x", date="2026-10-05", kind="robot",
               verdict=None, comment=None, expect_sha=None, dry_run=False)
