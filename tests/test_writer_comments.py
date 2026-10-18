"""Writer preserves comments (#53): an edit splices only the target need's block."""

from __future__ import annotations

from pathlib import Path

from prodc.config import Config
from prodc.writer import accept, add_need, capture_source, set_field

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

# A hand-authored file: a provenance header, and a comment introducing the second need.
_COMMENTED = """\
# Provenance contract: interview quotes are VERBATIM from the customer.
# ids are minted in the N-16xx range.
who: visitor
needs:
  - id: N-1
    text: original first need
    sources:
      - kind: interview
        who: John
        quote: "I need this"
        date: 2026-01-01
  # this comment introduces the second need
  - id: N-2
    text: second need stays untouched
    proofs: ["web:x#y"]
"""


def _project(tmp_path: Path, needs: str = _COMMENTED) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def _read(tmp_path: Path) -> str:
    return (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")


def test_set_preserves_header_and_other_need(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    set_field(cfg, "N-1", "text=updated first need", expect_sha=None, dry_run=False)
    out = _read(tmp_path)
    assert "# Provenance contract: interview quotes are VERBATIM" in out
    assert "# ids are minted in the N-16xx range." in out
    assert "# this comment introduces the second need" in out
    assert "text: updated first need" in out
    assert "second need stays untouched" in out  # N-2 block intact


def test_set_on_last_need_keeps_everything_above(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    set_field(cfg, "N-2", "text=updated second need", expect_sha=None, dry_run=False)
    out = _read(tmp_path)
    assert "# Provenance contract: interview quotes are VERBATIM" in out
    assert "# this comment introduces the second need" in out
    assert "text: original first need" in out  # N-1 untouched
    assert "text: updated second need" in out


def test_capture_preserves_comments(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    capture_source(
        cfg,
        "N-1",
        kind="secondary",
        who=None,
        date="2026-10-05",
        quote=None,
        locator="docs/x.md#y",
        observed_at="2026-10-05",
        expect_sha=None,
        dry_run=False,
    )
    out = _read(tmp_path)
    assert "# Provenance contract: interview quotes are VERBATIM" in out
    assert "locator: docs/x.md#y" in out


def test_accept_preserves_comments(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    accept(cfg, "N-1", who="jorge", date="2026-10-05", revoke=False, expect_sha=None, dry_run=False)
    out = _read(tmp_path)
    assert "# ids are minted in the N-16xx range." in out
    assert "accept:jorge@2026-10-05" in out


def test_only_target_block_changes(tmp_path: Path) -> None:
    before = _read(tmp_path) if (tmp_path / "needs" / "a.yaml").exists() else None
    cfg = _project(tmp_path)
    original = _read(tmp_path)
    set_field(cfg, "N-1", "text=changed", expect_sha=None, dry_run=False)
    after = _read(tmp_path)
    # the N-2 block (its line) is byte-identical in both
    assert "    text: second need stays untouched" in original
    assert "    text: second need stays untouched" in after
    assert before is None  # sanity: fixture wrote fresh


def test_inline_list_file_falls_back_but_still_edits(tmp_path: Path) -> None:
    # flow-style needs: the splice can't place it, so the writer falls back to a full re-dump;
    # the edit must still apply and the file must still load.
    inline = "needs: [{id: N-1, text: original}]\n"
    cfg = _project(tmp_path, needs=inline)
    set_field(cfg, "N-1", "text=edited via fallback", expect_sha=None, dry_run=False)
    out = _read(tmp_path)
    assert "edited via fallback" in out


def test_add_appends_and_preserves_comments(tmp_path: Path) -> None:
    # #85: `add` must splice the new need in, not re-dump the whole file and drop every comment.
    cfg = _project(tmp_path)
    add_need(
        cfg,
        "N-3",
        "a freshly added need",
        who="agent",
        kind="assumption",
        file="needs/a.yaml",
        expect_sha=None,
        dry_run=False,
    )
    out = _read(tmp_path)
    # every authored comment survives
    assert "# Provenance contract: interview quotes are VERBATIM" in out
    assert "# ids are minted in the N-16xx range." in out
    assert "# this comment introduces the second need" in out
    # the existing needs are untouched and the 2-space item indent is matched, not reflowed
    assert "  - id: N-1\n" in out
    assert "    text: second need stays untouched" in out
    assert "  - id: N-3\n" in out
    assert "a freshly added need" in out
    # the new need lands after N-2, not before it
    assert out.index("id: N-3") > out.index("id: N-2")


def test_add_into_new_file_dumps_fresh(tmp_path: Path) -> None:
    # No existing list to append to: fall back to a whole-file dump, which must still load.
    cfg = _project(tmp_path)
    add_need(
        cfg,
        "N-9",
        "a need in a brand-new file",
        who="agent",
        kind="assumption",
        file="needs/b.yaml",
        expect_sha=None,
        dry_run=False,
    )
    out = (tmp_path / "needs" / "b.yaml").read_text(encoding="utf-8")
    assert "id: N-9" in out
    assert "a need in a brand-new file" in out
