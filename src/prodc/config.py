"""Load ``prodc.toml``: where the needs live and how each proof adapter resolves."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .adapters import Adapter, GherkinAdapter, PytestAdapter


class ConfigError(Exception):
    pass


def _as_dict(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a table")
    return cast("dict[str, object]", value)


def _as_str_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{where}: expected a list of strings")
    items = cast("list[object]", value)
    if not all(isinstance(x, str) for x in items):
        raise ConfigError(f"{where}: expected a list of strings")
    return [x for x in items if isinstance(x, str)]


@dataclass
class Config:
    root: Path
    need_globs: list[str]
    adapters: dict[str, Adapter] = field(default_factory=dict[str, Adapter])

    @classmethod
    def load(cls, path: Path) -> Config:
        root = path.parent
        raw = _as_dict(tomllib.loads(path.read_text(encoding="utf-8")), "prodc.toml")

        prodc_tbl = _as_dict(raw.get("prodc", {}), "[prodc]")
        need_globs = _as_str_list(prodc_tbl.get("needs", []), "[prodc].needs")
        if not need_globs:
            raise ConfigError("[prodc].needs must list at least one glob")

        adapters: dict[str, Adapter] = {}
        proofs = _as_dict(raw.get("proofs", {}), "[proofs]")
        for name, body in proofs.items():
            tbl = _as_dict(body, f"[proofs.{name}]")
            kind = tbl.get("kind")
            results = tbl.get("results")
            results_s = results if isinstance(results, str) else None
            if kind == "gherkin":
                adapters[name] = GherkinAdapter(
                    root=root,
                    paths=_as_str_list(tbl.get("paths", []), f"[proofs.{name}].paths"),
                    delivered_tags=_as_str_list(
                        tbl.get("delivered", []), f"[proofs.{name}].delivered"
                    ),
                    pending_tags=_as_str_list(
                        tbl.get("pending", []), f"[proofs.{name}].pending"
                    ),
                    results=results_s,
                )
            elif kind == "pytest":
                sub = tbl.get("root", ".")
                adapters[name] = PytestAdapter(
                    root=root / (sub if isinstance(sub, str) else "."),
                    results=results_s,
                )
            else:
                raise ConfigError(f"[proofs.{name}]: unknown kind {kind!r} (gherkin|pytest)")
        return cls(root=root, need_globs=need_globs, adapters=adapters)
