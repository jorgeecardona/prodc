"""The catalog registry: one lookup over every pack, pack names checked, prefixes reserved."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.catalog import CATALOG, PACKS, find, reserved_pack
from prodc.config import Config
from prodc.loader import LoaderError, load


def test_every_entry_id_starts_with_its_pack() -> None:
    for entry in CATALOG:
        assert entry.id.startswith(f"{entry.pack}-"), entry.id
        assert reserved_pack(entry.id) == entry.pack


def test_ids_are_unique_across_packs() -> None:
    ids = [e.id for e in CATALOG]
    assert len(ids) == len(set(ids))


def test_find_returns_the_entry_or_none() -> None:
    assert find("ux-fitts") is not None
    assert find("ux-nope") is None


def test_reserved_pack_needs_the_dash() -> None:
    assert reserved_pack("ux-anything") == "ux"
    assert reserved_pack("uxfoo") is None
    assert reserved_pack("P-1") is None


def test_every_sign_off_or_checkable_entry_is_well_formed() -> None:
    for entry in CATALOG:
        assert not (entry.checkable and entry.sign_off), entry.id
        assert (entry.recipe is not None) == entry.checkable, entry.id


def _project(tmp_path: Path, toml: str, yaml: str = "needs: []\n") -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(yaml, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_unknown_pack_is_a_notice_not_an_error(tmp_path: Path) -> None:
    toml = '[prodc]\nneeds = ["needs/*.yaml"]\n[principles]\npacks = ["ux", "uxx"]\n'
    cfg = Config.load(_project(tmp_path, toml))
    assert cfg.principle_packs == ("ux", "uxx")
    assert any("unknown pack 'uxx'" in n for n in cfg.notices)
    assert not any("'ux'" in n for n in cfg.notices)
    assert "ux" in PACKS


def test_a_made_up_id_with_a_pack_prefix_is_refused(tmp_path: Path) -> None:
    toml = '[prodc]\nneeds = ["needs/*.yaml"]\n'
    yaml = "principles:\n  - id: ux-mine\n    text: t\n    revised_at: 2026-01-01\n"
    with pytest.raises(LoaderError, match="'ux-' prefix is reserved"):
        load(Config.load(_project(tmp_path, toml, yaml)))
