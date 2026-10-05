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
    stale_after_days: int | None = None  # [lint].stale_after_days — flag older evidence (#58)
    importance_levels: dict[int, tuple[str, str]] = field(
        default_factory=dict[int, tuple[str, str]]
    )  # [importance].levels — ordinal → (label, meaning); empty = no rubric declared (#59)
    importance_revisit_days: int | None = None  # [lint].importance_revisit_days (#59)
    default_draft: bool = False  # [add].default_draft — `add` stages as draft by default (#60)

    def importance_label(self, level: int | None) -> str | None:
        """The declared label for an importance level, or None if unset/undeclared (#59)."""
        if level is None:
            return None
        pair = self.importance_levels.get(level)
        return pair[0] if pair else None

    def resolve_importance(self, value: str) -> int:
        """Map a CLI importance value (a number or a declared label) to a valid level (#59).

        With a rubric declared, the value must be one of its levels (by number or label); without
        one, any integer is accepted so the bare ordinal keeps working. Raises on anything else.
        """
        raw = value.strip()
        if self.importance_levels:
            for level, (label, _meaning) in self.importance_levels.items():
                if raw == str(level) or raw.lower() == label.lower():
                    return level
            allowed = ", ".join(
                f"{n}={lbl}" for n, (lbl, _m) in sorted(self.importance_levels.items())
            )
            raise ConfigError(f"importance {raw!r} is not on the scale ({allowed})")
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(
                f"importance {raw!r} is not an integer (no rubric declared)"
            ) from None

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
        stale = lint_tbl.get("stale_after_days")
        if stale is not None and (
            not isinstance(stale, int) or isinstance(stale, bool) or stale < 1
        ):
            raise ConfigError("[lint].stale_after_days must be a positive integer")
        revisit = lint_tbl.get("importance_revisit_days")
        if revisit is not None and (
            not isinstance(revisit, int) or isinstance(revisit, bool) or revisit < 1
        ):
            raise ConfigError("[lint].importance_revisit_days must be a positive integer")

        importance_levels: dict[int, tuple[str, str]] = {}
        imp_tbl = _as_dict(raw.get("importance", {}), "[importance]")
        rows = imp_tbl.get("levels", [])
        if not isinstance(rows, list):
            raise ConfigError("[importance].levels must be a list of [number, label, meaning]")
        for i, row in enumerate(cast("list[object]", rows)):
            if (
                not isinstance(row, list)
                or len(cast("list[object]", row)) != 3
                or not isinstance(row[0], int)
                or isinstance(row[0], bool)
                or not isinstance(row[1], str)
                or not isinstance(row[2], str)
            ):
                raise ConfigError(f"[importance].levels[{i}] must be [number, label, meaning]")
            importance_levels[row[0]] = (row[1], row[2])

        add_tbl = _as_dict(raw.get("add", {}), "[add]")
        default_draft = add_tbl.get("default_draft", False)
        if not isinstance(default_draft, bool):
            raise ConfigError("[add].default_draft must be true or false")

        return cls(
            root=root,
            need_globs=need_globs,
            adapters=adapters,
            source_adapters=source_adapters,
            duplicate_threshold=float(dup),
            stale_after_days=stale,
            importance_levels=importance_levels,
            importance_revisit_days=revisit,
            default_draft=default_draft,
        )
