"""Tests for the ux pack catalog entries."""

from __future__ import annotations

from prodc.catalog.ux import UX_CATALOG


def test_all_ids_unique() -> None:
    ids = [e.id for e in UX_CATALOG]
    assert len(ids) == len(set(ids)), "duplicate catalog id"


def test_all_ids_have_ux_prefix() -> None:
    for entry in UX_CATALOG:
        assert entry.id.startswith("ux-"), f"{entry.id!r} does not start with 'ux-'"


def test_all_checkable_entries_have_a_recipe() -> None:
    for entry in UX_CATALOG:
        if entry.checkable:
            assert entry.recipe is not None, f"{entry.id!r} is checkable but has no recipe"


def test_non_checkable_entries_have_no_recipe() -> None:
    for entry in UX_CATALOG:
        if not entry.checkable:
            assert entry.recipe is None, f"{entry.id!r} is not checkable but has a recipe"


def test_all_urls_https_lawsofux() -> None:
    for entry in UX_CATALOG:
        assert entry.url.startswith("https://"), f"{entry.id!r} url is not https"
        assert "lawsofux.com" in entry.url, f"{entry.id!r} url does not point at lawsofux.com"


def test_checkable_ids_present() -> None:
    checkable = {e.id for e in UX_CATALOG if e.checkable}
    required = {"ux-fitts", "ux-hick", "ux-von-restorff", "ux-miller", "ux-jakob"}
    assert required <= checkable, f"missing checkable ids: {required - checkable}"


def test_all_packs_are_ux() -> None:
    for entry in UX_CATALOG:
        assert entry.pack == "ux", f"{entry.id!r} has pack {entry.pack!r}, expected 'ux'"
