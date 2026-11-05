"""Write-back: prodc set / add need, validated against the loader (#24)."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import load
from prodc.writer import (
    WriteError,
    add_need,
    add_role,
    capture_source,
    delete_need,
    relink_proof,
    set_field,
)


def _proj(tmp_path: Path, body: str) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "needs" / "a.yaml").write_text(body, encoding="utf-8")
    return Config(root=tmp_path, file_globs=["needs/*.yaml"])


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
        kind="assumption",
        file="needs/a.yaml",
        expect_sha=None,
        dry_run=False,
    )
    by_id = {n.id: n for n in load(cfg).needs}
    # It still carries a source — an explicit assumption, not a silent/sourceless need. It is
    # still an opinion (an assumption is no external evidence), but an *owned, dated* one.
    assert "N-2" in by_id and by_id["N-2"].only_assumption and by_id["N-2"].is_opinion
    src = by_id["N-2"].sources[0]
    assert src.who == "agent:claude" and src.date == datetime.date.today().isoformat()


def test_add_need_rejects_primary_kind(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="assumption or secondary"):
        add_need(
            cfg,
            "N-2",
            "t",
            who="agent",
            kind="primary",
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
            kind="assumption",
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
            kind="assumption",
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
        kind="primary",
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
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=False, expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].proofs == ("accept:jorge@2026-10-05",)
    accept(
        cfg, "N-1", who="jorge", date="2026-10-05", revoke=False, expect_sha=None, dry_run=False
    )  # again
    assert load(cfg).needs[0].proofs == ("accept:jorge@2026-10-05",)  # no duplicate


def test_accept_revoke_removes(tmp_path: Path) -> None:
    from prodc.writer import accept

    cfg = _proj(
        tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: [accept:jorge@2026-10-05]\n"
    )
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=True, expect_sha=None, dry_run=False)
    assert load(cfg).needs[0].proofs == ()


def test_attest_ai_records_model_verdict_comment(tmp_path: Path) -> None:
    from prodc.model import AttestationKind
    from prodc.writer import attest

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: [web:x#y]\n")
    attest(
        cfg,
        "N-1",
        who="claude-opus-4-8",
        date="2026-10-05",
        kind="ai",
        verdict="pass",
        comment="looks right",
        expect_sha=None,
        dry_run=False,
    )
    a = load(cfg).needs[0].attestation
    assert a is not None and a.kind is AttestationKind.AI and a.who == "claude-opus-4-8"
    assert a.verdict == "pass" and a.comment == "looks right"


def test_attest_bad_kind_rejected(tmp_path: Path) -> None:
    from prodc.writer import attest

    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="human or ai"):
        attest(
            cfg,
            "N-1",
            who="x",
            date="2026-10-05",
            kind="robot",
            verdict=None,
            comment=None,
            expect_sha=None,
            dry_run=False,
        )


def test_add_role_declares_role_in_new_file(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    add_role(cfg, "owner", "owns the roastery", file="needs/roles.yaml", dry_run=False)
    model = load(cfg)
    assert {r.id: r.text for r in model.roles} == {"owner": "owns the roastery"}


def test_add_role_duplicate_id_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "roles:\n  - id: owner\n    text: one\n")
    with pytest.raises(WriteError, match="already exists"):
        add_role(cfg, "owner", "two", file="needs/a.yaml", dry_run=False)


def test_add_role_outside_glob_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="does not match any"):
        add_role(cfg, "owner", "t", file="outside.yaml", dry_run=False)


def test_add_role_dry_run_leaves_no_file(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    edit = add_role(cfg, "owner", "owns it", file="needs/roles.yaml", dry_run=True)
    assert "owner" in edit.diff
    assert not (cfg.root / "needs" / "roles.yaml").exists()  # dry-run wrote nothing


def test_delete_need_removes_the_block_keeping_others(tmp_path: Path) -> None:
    cfg = _proj(
        tmp_path,
        "# keep me\nneeds:\n  - id: N-1\n    text: one\n  - id: N-2\n    text: two\n",
    )
    delete_need(cfg, "N-1", dry_run=False)
    text = _a_yaml(cfg)
    assert {n.id for n in load(cfg).needs} == {"N-2"}
    assert "# keep me" in text  # header comment survives the splice


def test_children_append_stepped_edge(tmp_path: Path) -> None:
    # #90: `children+=id@step` appends a {id, step} edge; a bare id stays a plain string.
    body = (
        "needs:\n"
        "  - id: F-1\n    text: a flow\n    children: [N-2]\n"
        "  - id: N-2\n    text: step two\n    proofs: ['x:1']\n"
        "  - id: N-3\n    text: step three\n    proofs: ['x:2']\n"
    )
    cfg = _proj(tmp_path, body)
    set_field(cfg, "F-1", "children+=N-3@conclude", expect_sha=None, dry_run=False)
    flow = next(n for n in load(cfg).needs if n.id == "F-1")
    assert [(c.id, c.step) for c in flow.children] == [("N-2", None), ("N-3", "conclude")]


def test_children_append_bare_id(tmp_path: Path) -> None:
    body = (
        "needs:\n"
        "  - id: F-1\n    text: a flow\n    children: [N-2]\n"
        "  - id: N-2\n    text: step two\n    proofs: ['x:1']\n"
        "  - id: N-3\n    text: step three\n    proofs: ['x:2']\n"
    )
    cfg = _proj(tmp_path, body)
    set_field(cfg, "F-1", "children+=N-3", expect_sha=None, dry_run=False)
    flow = next(n for n in load(cfg).needs if n.id == "F-1")
    assert [(c.id, c.step) for c in flow.children] == [("N-2", None), ("N-3", None)]


def test_tags_append(tmp_path: Path) -> None:
    # #80: tags are a plain string list; `tags+=X` appends like proofs.
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: a need\n    tags: [search]\n")
    set_field(cfg, "N-1", "tags+=onboarding", expect_sha=None, dry_run=False)
    need = next(n for n in load(cfg).needs if n.id == "N-1")
    assert need.tags == ("search", "onboarding")


def test_delete_need_unknown_id_rejected(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n")
    with pytest.raises(WriteError, match="no need 'N-9'"):
        delete_need(cfg, "N-9", dry_run=False)


def test_delete_need_dangling_reference_reverts(tmp_path: Path) -> None:
    # N-2 is a child of flow N-1; deleting N-2 would dangle the reference, so the reload gate
    # must reject the write and restore the file.
    body = (
        "needs:\n"
        "  - id: N-1\n    text: a flow\n    children: [N-2]\n"
        "  - id: N-2\n    text: a step\n    proofs: ['x:1']\n"
    )
    cfg = _proj(tmp_path, body)
    before = _a_yaml(cfg)
    with pytest.raises(WriteError, match="edit rejected"):
        delete_need(cfg, "N-2", dry_run=False)
    assert _a_yaml(cfg) == before  # reverted


def test_delete_need_dry_run_leaves_file(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: one\n  - id: N-2\n    text: two\n")
    before = _a_yaml(cfg)
    edit = delete_need(cfg, "N-1", dry_run=True)
    assert _a_yaml(cfg) == before  # nothing written
    assert "N-1" in edit.diff and edit.diff.startswith("---")


def test_relink_proof_swaps_locator(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: ['web:a#Old']\n")
    relink_proof(cfg, "N-1", "web:a#Old", "web:a#New", dry_run=False)
    assert load(cfg).needs[0].proofs == ("web:a#New",)


def test_relink_proof_rejects_absent_old(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs:\n  - id: N-1\n    text: t\n    proofs: ['web:a#Old']\n")
    with pytest.raises(WriteError, match="is not a proof on 'N-1'"):
        relink_proof(cfg, "N-1", "web:a#Missing", "web:a#New", dry_run=False)


def test_relink_proof_dedupes_when_new_already_present(tmp_path: Path) -> None:
    cfg = _proj(
        tmp_path,
        "needs:\n  - id: N-1\n    text: t\n    proofs: ['web:a#Old', 'web:a#New']\n",
    )
    relink_proof(cfg, "N-1", "web:a#Old", "web:a#New", dry_run=False)
    assert load(cfg).needs[0].proofs == ("web:a#New",)  # broken dropped, no duplicate


def test_add_draft_stamps_draft_added(tmp_path: Path) -> None:
    cfg = _proj(tmp_path, "needs: []\n")
    add_need(
        cfg,
        "D-1",
        "a staged idea",
        who="agent",
        kind="assumption",
        file="needs/a.yaml",
        draft=True,
        expect_sha=None,
        dry_run=False,
    )
    need = {n.id: n for n in load(cfg).needs}["D-1"]
    assert need.draft is True
    assert need.draft_added == datetime.date.today().isoformat()
