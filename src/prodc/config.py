"""Load ``prodc.toml``: where the needs live and how each proof adapter resolves."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .adapters import (
    AcceptAdapter,
    Adapter,
    CoverageAdapter,
    External,
    FieldAdapter,
    FilesAdapter,
    FrontmatterAdapter,
    GherkinAdapter,
    PrototypeAdapter,
    PytestAdapter,
    SourceAdapter,
)


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
    need_globs: list[str]  # the prodc files; each may carry any noun list (needs:, goals:, …)
    adapters: dict[str, Adapter] = field(default_factory=dict[str, Adapter])
    source_adapters: dict[str, SourceAdapter] = field(default_factory=dict[str, SourceAdapter])
    duplicate_threshold: float = 0.8  # [lint].duplicate_threshold — dupe score to flag (#55)

    @classmethod
    def load(cls, path: Path) -> Config:
        root = path.resolve().parent  # resolve so root.name is the dir, not "" for a bare file
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
            # `repo` points the adapter at a sibling repo checked out beside this one;
            # its paths then resolve under that repo and reads are wrapped by External.
            repo_field = tbl.get("repo")
            proof_root = root / repo_field if isinstance(repo_field, str) else root
            if kind == "gherkin":
                inner: Adapter = GherkinAdapter(
                    root=proof_root,
                    paths=_as_str_list(tbl.get("paths", []), f"[proofs.{name}].paths"),
                    delivered_tags=_as_str_list(
                        tbl.get("delivered", []), f"[proofs.{name}].delivered"
                    ),
                    pending_tags=_as_str_list(tbl.get("pending", []), f"[proofs.{name}].pending"),
                    results=results_s,
                )
            elif kind == "pytest":
                sub = tbl.get("root", ".")
                inner = PytestAdapter(
                    root=proof_root / (sub if isinstance(sub, str) else "."),
                    results=results_s,
                )
            elif kind == "files":
                sub = tbl.get("root", ".")
                inner = FilesAdapter(root=proof_root / (sub if isinstance(sub, str) else "."))
            elif kind == "accept":
                inner = AcceptAdapter()
            elif kind == "prototype":
                inner = PrototypeAdapter()
            elif kind == "coverage":
                cat = tbl.get("catalog", "")
                inner = CoverageAdapter(
                    root=proof_root, catalog=cat if isinstance(cat, str) else ""
                )
            elif kind == "field":
                sch = tbl.get("schema", "")
                inner = FieldAdapter(root=proof_root, schema=sch if isinstance(sch, str) else "")
            else:
                raise ConfigError(
                    f"[proofs.{name}]: unknown kind {kind!r} "
                    "(gherkin|pytest|files|accept|prototype|coverage|field)"
                )
            adapters[name] = (
                External(inner, root / repo_field) if isinstance(repo_field, str) else inner
            )

        source_adapters: dict[str, SourceAdapter] = {}
        sources = _as_dict(raw.get("sources", {}), "[sources]")
        for name, body in sources.items():
            tbl = _as_dict(body, f"[sources.{name}]")
            kind = tbl.get("kind")
            if kind == "frontmatter":
                source_adapters[name] = FrontmatterAdapter(
                    root=root,
                    paths=_as_str_list(tbl.get("paths", []), f"[sources.{name}].paths"),
                )
            else:
                raise ConfigError(f"[sources.{name}]: unknown kind {kind!r} (frontmatter)")

        lint_tbl = _as_dict(raw.get("lint", {}), "[lint]")
        dup = lint_tbl.get("duplicate_threshold", 0.8)
        if not isinstance(dup, (int, float)) or isinstance(dup, bool) or not 0 < dup <= 1:
            raise ConfigError("[lint].duplicate_threshold must be a number in (0, 1]")

        return cls(
            root=root,
            need_globs=need_globs,
            adapters=adapters,
            source_adapters=source_adapters,
            duplicate_threshold=float(dup),
        )
