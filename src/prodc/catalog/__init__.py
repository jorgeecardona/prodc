"""Catalog of reusable principle definitions grouped by pack.

A pack is a named collection of :class:`CatalogEntry` items. Each entry carries a
:class:`Recipe` when the rule can be verified by a test. Import the ux pack with
:data:`prodc.catalog.ux.UX_CATALOG`.
"""

from .ux import UX_CATALOG, CatalogEntry, Recipe

__all__ = ["UX_CATALOG", "CatalogEntry", "Recipe"]
