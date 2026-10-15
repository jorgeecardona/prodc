"""Load ``prodc.toml``: where the needs live and how each proof adapter resolves."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .adapters import (
    AcceptAdapter,
    Adapter,
    CitationAdapter,
    CommandProof,
    CommandSource,
    CoverageAdapter,
    EvalGateAdapter,
    External,
    FieldAdapter,
    FilesAdapter,
    FrontmatterAdapter,
    GherkinAdapter,
    GitLabSource,
    OutcomeAdapter,
    PrototypeAdapter,
    PytestAdapter,
    SourceAdapter,
)
from .callbacks import Callback
from .model import NeedState


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


def _hook_command(tbl: dict[str, object], where: str) -> tuple[list[str], float]:
    """Parse a command hook's ``command = [...]`` and optional ``timeout`` (#70)."""
    command = _as_str_list(tbl.get("command", []), f"{where}.command")
    if not command:
        raise ConfigError(f"{where}: command must be a non-empty list of strings")
    timeout = tbl.get("timeout", 10.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigError(f"{where}.timeout must be a positive number of seconds")
    return command, float(timeout)


def _state_filter(tbl: dict[str, object], key: str, where: str) -> frozenset[str]:
    """A ``from``/``to`` transition filter: a list of valid need-state names (empty = any)."""
    vals = _as_str_list(tbl.get(key, []), f"{where}.{key}")
    valid = {s.value for s in NeedState}
    bad = [v for v in vals if v not in valid]
    if bad:
        raise ConfigError(
            f"{where}.{key}: unknown state(s) {', '.join(bad)} (one of {', '.join(sorted(valid))})"
        )
    return frozenset(vals)


def _callbacks(raw: dict[str, object]) -> tuple[tuple[Callback, ...], str]:
    """Parse ``[callbacks]``: the state ledger path and the ``[[callbacks.hooks]]`` list (#71)."""
    cb_tbl = _as_dict(raw.get("callbacks", {}), "[callbacks]")
    state_file = cb_tbl.get("state_file", ".prodc/state.json")
    if not isinstance(state_file, str):
        raise ConfigError("[callbacks].state_file must be a string")
    hooks_raw = cb_tbl.get("hooks", [])
    if not isinstance(hooks_raw, list):
        raise ConfigError("[callbacks.hooks] must be a list of tables")
    out: list[Callback] = []
    for i, h in enumerate(cast("list[object]", hooks_raw)):
        where = f"[[callbacks.hooks]][{i}]"
        tbl = _as_dict(h, where)
        event = tbl.get("on")
        if event != "state_change":
            raise ConfigError(
                f"{where}.on must be 'state_change' (the only event supported), not {event!r}"
            )
        command, timeout = _hook_command(tbl, where)
        out.append(
            Callback(
                event="state_change",
                command=tuple(command),
                timeout=timeout,
                on_from=_state_filter(tbl, "from", where),
                on_to=_state_filter(tbl, "to", where),
            )
        )
    return tuple(out), state_file


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
    draft_max_age_days: int | None = None  # [lint].draft_max_age_days — flag stale drafts (#60)
    default_draft: bool = False  # [add].default_draft — `add` stages as draft by default (#60)
    callbacks: tuple[Callback, ...] = ()  # [[callbacks.hooks]] — lifecycle callbacks (#71)
    callback_state_file: str = ".prodc/state.json"  # [callbacks].state_file — the state ledger

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
            elif kind == "citation":
                inner = CitationAdapter()
            elif kind == "coverage":
                cat = tbl.get("catalog", "")
                inner = CoverageAdapter(
                    root=proof_root, catalog=cat if isinstance(cat, str) else ""
                )
            elif kind == "field":
                sch = tbl.get("schema", "")
                inner = FieldAdapter(root=proof_root, schema=sch if isinstance(sch, str) else "")
            elif kind == "external":
                if not results_s:
                    raise ConfigError(f"[proofs.{name}]: external needs results = <json file>")
                inner = OutcomeAdapter(root=proof_root, results=results_s)
            elif kind == "evalgate":
                if not results_s:
                    raise ConfigError(f"[proofs.{name}]: evalgate needs results = <json file>")
                inner = EvalGateAdapter(root=proof_root, results=results_s)
            elif kind == "command":
                command, timeout = _hook_command(tbl, f"[proofs.{name}]")
                inner = CommandProof(root=proof_root, command=command, timeout=timeout)
            else:
                raise ConfigError(
                    f"[proofs.{name}]: unknown kind {kind!r} "
                    "(gherkin|pytest|files|accept|prototype|citation|coverage|field|external|evalgate|command)"
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
            elif kind == "gitlab":
                base_url = tbl.get("base_url", "https://gitlab.com")
                project = tbl.get("project", "")
                token_env = tbl.get("token_env", "GITLAB_TOKEN")
                if not isinstance(base_url, str):
                    raise ConfigError(f"[sources.{name}].base_url must be a string")
                if not isinstance(project, str):
                    raise ConfigError(f"[sources.{name}].project must be a string")
                if not isinstance(token_env, str):
                    raise ConfigError(f"[sources.{name}].token_env must be a string")
                source_adapters[name] = GitLabSource(
                    base_url=base_url,
                    project=project,
                    token_env=token_env,
                )
            elif kind == "command":
                command, timeout = _hook_command(tbl, f"[sources.{name}]")
                source_adapters[name] = CommandSource(root=root, command=command, timeout=timeout)
            else:
                raise ConfigError(
                    f"[sources.{name}]: unknown kind {kind!r} (frontmatter|gitlab|command)"
                )

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
        draft_max_age = lint_tbl.get("draft_max_age_days")
        if draft_max_age is not None and (
            not isinstance(draft_max_age, int)
            or isinstance(draft_max_age, bool)
            or draft_max_age < 1
        ):
            raise ConfigError("[lint].draft_max_age_days must be a positive integer")

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

        callbacks, callback_state_file = _callbacks(raw)

        return cls(
            root=root,
            need_globs=need_globs,
            adapters=adapters,
            source_adapters=source_adapters,
            duplicate_threshold=float(dup),
            stale_after_days=stale,
            importance_levels=importance_levels,
            importance_revisit_days=revisit,
            draft_max_age_days=draft_max_age,
            default_draft=default_draft,
            callbacks=callbacks,
            callback_state_file=callback_state_file,
        )
