"""The catalog records: a principle template and the test recipe that guards it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Recipe:
    """A test recipe for a checkable catalog principle.

    ``kind`` names the test framework. ``snippet`` is a real guard taken from a consumer repo,
    to adapt to the adopting repo's paths. ``proof_locator_hint`` suggests
    the locator prefix and path to put under ``proofs:`` in the principle YAML.
    """

    kind: Literal["vitest", "playwright", "pytest"]
    summary: str
    snippet: str
    proof_locator_hint: str


@dataclass(frozen=True)
class CatalogEntry:
    """One principle template from a named pack.

    ``id`` is globally unique across all packs, starts with ``<pack>-``, and is the id written
    to the YAML when the team adopts the entry. ``scope`` is the principle scope the adopted
    principle gets; it must be listed in ``[principles].scopes``. ``text_template`` uses
    ``{slot}`` placeholders for values the team fills in (e.g. ``{N}`` for a numeric threshold).
    ``checkable`` is True when the rule can be verified by a test; a checkable entry must carry
    a ``recipe``. ``sign_off`` is True when no test can check the rule and a person signs it off
    with an ``accept:`` proof instead; lint asks for it like a checkable entry.
    """

    id: str
    pack: str
    title: str
    url: str
    text_template: str
    checkable: bool
    recipe: Recipe | None
    scope: str = "design"
    sign_off: bool = False
