"""Catalog of reusable principle definitions grouped by pack.

A pack is a named collection of :class:`CatalogEntry` items. Each entry carries a
:class:`Recipe` when the rule can be verified by a test. :data:`CATALOG` holds every entry of
every pack; :func:`find` looks one up by id. An entry id starts with its pack name and a dash
(``ux-fitts``), so ``ux-`` is reserved for the ux pack.
"""

from __future__ import annotations

from .model import CatalogEntry, Recipe
from .ux import UX_CATALOG

CATALOG: tuple[CatalogEntry, ...] = UX_CATALOG
"""Every catalog entry, all packs."""

PACKS: frozenset[str] = frozenset(e.pack for e in CATALOG)
"""The pack names ``[principles].packs`` accepts."""

_BY_ID: dict[str, CatalogEntry] = {e.id: e for e in CATALOG}


def find(entry_id: str) -> CatalogEntry | None:
    """Return the catalog entry with this id, or None."""
    return _BY_ID.get(entry_id)


def reserved_pack(principle_id: str) -> str | None:
    """Return the pack whose prefix ``principle_id`` uses, or None when it uses no pack prefix."""
    head = principle_id.split("-", 1)[0]
    return head if head in PACKS and principle_id.startswith(f"{head}-") else None


__all__ = ["CATALOG", "PACKS", "UX_CATALOG", "CatalogEntry", "Recipe", "find", "reserved_pack"]
