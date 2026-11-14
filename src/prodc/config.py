"""Load ``prodc.toml``: where the needs live and how each proof adapter resolves."""

from __future__ import annotations

import difflib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .adapters import (
    PYTEST_PATHS,
    VITEST_PATHS,
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
    PlaywrightAdapter,
    PrototypeAdapter,
    PytestAdapter,
    SourceAdapter,
    StorybookAdapter,
    ViewsAdapter,
    VitestAdapter,
)
from .callbacks import Callback
from .catalog import PACKS as CATALOG_PACKS
from .deprecation import deprecation
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


@dataclass(frozen=True)
class _Spec:
    """One ``[proofs.<name>]`` or ``[sources.<name>]`` table, ready for a builder."""

    name: str
    tbl: dict[str, object]
    root: Path  # the repo the adapter reads (the sibling repo for a proof with ``repo``)
    results: str | None  # the table's ``results`` file, when it is a string


def _sub_root(spec: _Spec) -> Path:
    """The directory a proof table's paths resolve against: its ``root``, else the repo (#124).

    Every path-reading adapter uses this, so ``root`` means the same in every ``[proofs.X]``.
    """
    sub = spec.tbl.get("root", ".")
    return spec.root / (sub if isinstance(sub, str) else ".")


def _need_results(spec: _Spec, kind: str) -> str:
    if not spec.results:
        raise ConfigError(f"[proofs.{spec.name}]: {kind} needs results = <json file>")
    return spec.results


def _str_field(spec: _Spec, key: str, default: str) -> str:
    val = spec.tbl.get(key, default)
    return val if isinstance(val, str) else default


def _gherkin(c: _Spec) -> Adapter:
    where = f"[proofs.{c.name}]"
    return GherkinAdapter(
        root=_sub_root(c),
        paths=_as_str_list(c.tbl.get("paths", []), f"{where}.paths"),
        delivered_tags=_as_str_list(c.tbl.get("delivered", []), f"{where}.delivered"),
        pending_tags=_as_str_list(c.tbl.get("pending", []), f"{where}.pending"),
        results=c.results,
    )


def _pytest(c: _Spec) -> Adapter:
    paths = _as_str_list(c.tbl.get("paths", list(PYTEST_PATHS)), f"[proofs.{c.name}].paths")
    return PytestAdapter(root=_sub_root(c), results=c.results, paths=paths)


def _vitest(c: _Spec) -> Adapter:
    paths = _as_str_list(c.tbl.get("paths", list(VITEST_PATHS)), f"[proofs.{c.name}].paths")
    return VitestAdapter(root=_sub_root(c), results=c.results, paths=paths)


def _playwright(c: _Spec) -> Adapter:
    where = f"[proofs.{c.name}]"
    paths = _as_str_list(
        c.tbl.get("paths", ["**/*.visual.tsx", "**/*.spec.ts", "**/*.spec.tsx"]), f"{where}.paths"
    )
    return PlaywrightAdapter(root=_sub_root(c), results=c.results, paths=paths)


def _command_proof(c: _Spec) -> Adapter:
    command, timeout = _hook_command(c.tbl, f"[proofs.{c.name}]")
    return CommandProof(root=c.root, command=command, timeout=timeout)


# kind -> builder. The key order is the order the unknown-kind error lists, so the message
# cannot drift from the supported set (#83). `External` wrapping is applied once, by the loader.
_PROOF_BUILDERS: dict[str, Callable[[_Spec], Adapter]] = {
    "gherkin": _gherkin,
    "pytest": _pytest,
    "vitest": _vitest,
    "playwright": _playwright,
    "files": lambda c: FilesAdapter(root=_sub_root(c)),
    "accept": lambda c: AcceptAdapter(),
    "prototype": lambda c: PrototypeAdapter(),
    "citation": lambda c: CitationAdapter(),
    "coverage": lambda c: CoverageAdapter(root=_sub_root(c), catalog=_str_field(c, "catalog", "")),
    "field": lambda c: FieldAdapter(root=_sub_root(c), schema=_str_field(c, "schema", "")),
    "external": lambda c: OutcomeAdapter(root=_sub_root(c), results=_need_results(c, "external")),
    "evalgate": lambda c: EvalGateAdapter(root=_sub_root(c), results=_need_results(c, "evalgate")),
    "command": _command_proof,
    "storybook": lambda c: StorybookAdapter(
        root=_sub_root(c),
        index=_str_field(c, "index", "storybook-static/index.json"),
        url=_str_field(c, "url", "") or None,
    ),
    "views": lambda c: ViewsAdapter(
        root=_sub_root(c), files=_as_str_list(c.tbl.get("files", []), f"[proofs.{c.name}].files")
    ),
}


def _gitlab_source(c: _Spec) -> SourceAdapter:
    for key, default in (
        ("base_url", "https://gitlab.com"),
        ("project", ""),
        ("token_env", "GITLAB_TOKEN"),
    ):
        if not isinstance(c.tbl.get(key, default), str):
            raise ConfigError(f"[sources.{c.name}].{key} must be a string")
    return GitLabSource(
        base_url=_str_field(c, "base_url", "https://gitlab.com"),
        project=_str_field(c, "project", ""),
        token_env=_str_field(c, "token_env", "GITLAB_TOKEN"),
    )


def _command_source(c: _Spec) -> SourceAdapter:
    command, timeout = _hook_command(c.tbl, f"[sources.{c.name}]")
    return CommandSource(root=c.root, command=command, timeout=timeout)


_SOURCE_BUILDERS: dict[str, Callable[[_Spec], SourceAdapter]] = {
    "frontmatter": lambda c: FrontmatterAdapter(
        root=c.root, paths=_as_str_list(c.tbl.get("paths", []), f"[sources.{c.name}].paths")
    ),
    "gitlab": _gitlab_source,
    "command": _command_source,
}


_PROOF_KEYS = frozenset(
    [
        "kind",
        "root",
        "repo",
        "results",
        "paths",
        "delivered",
        "pending",
        "catalog",
        "schema",
        "files",
        "command",
        "timeout",
        "index",
        "url",
    ]
)
_SOURCE_KEYS = frozenset(
    ["kind", "paths", "base_url", "project", "token_env", "command", "timeout"]
)
_HOOK_KEYS = frozenset({"on", "command", "timeout", "from", "to"})
_TABLE_KEYS: dict[str, frozenset[str]] = {
    "prodc": frozenset({"files", "needs", "issues", "name", "profile"}),
    "lint": frozenset(
        {
            "duplicate_threshold",
            "stale_after_days",
            "importance_revisit_days",
            "draft_max_age_days",
            "unjustified_views",
            "unjustified_stories",
            "link_without_why",
            "ai_attestation",
            "missing_catalog_principles",
        }
    ),
    "importance": frozenset({"levels"}),
    "add": frozenset({"default_draft"}),
    "callbacks": frozenset({"state_file", "hooks"}),
    "principles": frozenset({"scopes", "packs"}),
    "flows": frozenset({"steps"}),
}
_TOP_KEYS = frozenset(_TABLE_KEYS) | {"proofs", "sources"}


def _unknown_in(tbl: dict[str, object], known: frozenset[str], where: str) -> list[str]:
    """A notice for each key of ``tbl`` not in ``known``, with a hint when one is close."""
    out: list[str] = []
    for key in tbl:
        if key not in known:
            close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.8)
            hint = f" (did you mean '{close[0]}'?)" if close else ""
            out.append(f"prodc.toml: {where}: unknown key '{key}' is ignored{hint}")
    return out


def _unknown_packs(packs: tuple[str, ...]) -> tuple[str, ...]:
    """The notices for ``[principles].packs`` names no catalog pack has, so a typo is not silent."""
    known = ", ".join(sorted(CATALOG_PACKS))
    return tuple(
        f"[principles].packs: unknown pack {name!r}; known packs: {known}"
        for name in packs
        if name not in CATALOG_PACKS
    )


def _deprecated_toml(raw: dict[str, object]) -> tuple[str, ...]:
    """The deprecation lines for ``prodc.toml`` settings that 0.12 removes."""
    out: list[str] = []
    if "profile" in _as_dict(raw.get("prodc", {}), "[prodc]"):
        out.append(deprecation("[prodc].profile", "delete it: a research board needs no profile"))
    return tuple(out)


def _unknown_toml_keys(raw: dict[str, object]) -> tuple[str, ...]:
    """The notices for keys prodc does not read, so a dead setting is not silently ignored.

    Notices, not a :class:`ConfigError`: a load failure would block the writes that fix a board
    (#96). Only called on a config that already parsed, so every table has the right type.
    """
    out = _unknown_in(raw, _TOP_KEYS, "top level")
    for name, known in _TABLE_KEYS.items():
        out += _unknown_in(_as_dict(raw.get(name, {}), f"[{name}]"), known, f"[{name}]")
    for table, known in (("proofs", _PROOF_KEYS), ("sources", _SOURCE_KEYS)):
        for name, body in _as_dict(raw.get(table, {}), f"[{table}]").items():
            where = f"[{table}.{name}]"
            out += _unknown_in(_as_dict(body, where), known, where)
    hooks = _as_dict(raw.get("callbacks", {}), "[callbacks]").get("hooks", [])
    for i, hook in enumerate(cast("list[object]", hooks)):
        where = f"[[callbacks.hooks]][{i}]"
        out += _unknown_in(_as_dict(hook, where), _HOOK_KEYS, where)
    return tuple(out)


@dataclass
class Config:
    root: Path
    # [prodc].files (+ the older alias [prodc].needs): the prodc files. Every matched file may
    # carry any noun list (needs:, goals:, roles:, principles:, decisions:, …). (#95)
    file_globs: list[str]
    issue_globs: list[str] = field(default_factory=list[str])  # [prodc].issues: issue files (#36)
    adapters: dict[str, Adapter] = field(default_factory=dict[str, Adapter])
    source_adapters: dict[str, SourceAdapter] = field(default_factory=dict[str, SourceAdapter])
    duplicate_threshold: float = 0.8  # [lint].duplicate_threshold: dupe score to flag (#55)
    stale_after_days: int | None = None  # [lint].stale_after_days: flag older evidence (#58)
    importance_levels: dict[int, tuple[str, str]] = field(
        default_factory=dict[int, tuple[str, str]]
    )  # [importance].levels: ordinal → (label, meaning); empty = no rubric declared (#59)
    importance_revisit_days: int | None = None  # [lint].importance_revisit_days (#59)
    draft_max_age_days: int | None = None  # [lint].draft_max_age_days: flag stale drafts (#60)
    unjustified_views: str | None = None  # [lint].unjustified_views: "warn" | "error" (#108)
    unjustified_stories: str | None = None  # [lint].unjustified_stories: "warn" | "error"
    link_without_why: str | None = None  # [lint].link_without_why: "warn" | "error" (#104)
    ai_attestation: str = "warns"  # [lint].ai_attestation: "counts" | "warns" (#87)
    default_draft: bool = False  # [add].default_draft: ``add`` stages as draft by default (#60)
    callbacks: tuple[Callback, ...] = ()  # [[callbacks.hooks]]: lifecycle callbacks (#71)
    callback_state_file: str = ".prodc/state.json"  # [callbacks].state_file: the state ledger
    principle_scopes: tuple[str, ...] = ("product",)  # [principles].scopes: allowed scopes (#88)
    principle_packs: tuple[str, ...] = ()  # [principles].packs: catalog packs to lint against
    missing_catalog_principles: str = "warn"  # [lint].missing_catalog_principles: warn|error|off
    flow_steps: tuple[str, ...] = ()  # [flows].steps: ordered step vocab; () = undeclared (#90)
    notices: tuple[str, ...] = ()  # unknown prodc.toml keys: printed on reads, fail lint
    # Settings 0.11 still reads and 0.12 removes: printed once per run, a lint warning, never fatal.
    deprecations: tuple[str, ...] = ()
    name: str = ""  # [prodc].name: the board's name; "" means the directory's name (#125)

    @property
    def board_name(self) -> str:
        """The name status, portfolio and reports show: ``[prodc].name``, else the directory (#125)."""
        return self.name or self.root.name

    @property
    def terminal_step(self) -> str | None:
        """The step that ends a journey: the last declared step, or None when no vocab (#90).

        The single definition of 'terminal': status/lint read it here, never recompute
        ``flow_steps[-1]`` elsewhere. Order in ``[flows].steps`` *is* the journey.
        """
        return self.flow_steps[-1] if self.flow_steps else None

    def prodc_files(self) -> list[Path]:
        """Every file matched by the configured globs, each once, in glob-then-name order.

        A path matched by two globs (say ``files`` and ``needs`` overlap) is read once, so
        its ids are not reported as duplicates of themselves.
        """
        seen: set[Path] = set()
        out: list[Path] = []
        for pattern in self.file_globs:
            for path in sorted(self.root.glob(pattern)):
                if path not in seen:
                    seen.add(path)
                    out.append(path)
        return out

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
        # `files` is the neutral name (#95); `needs` stays as an alias and the two are merged, so
        # an existing config keeps working and a repo can split decisions/roles into their own
        # folder without listing them under a key that says "needs".
        files = _as_str_list(prodc_tbl.get("files", []), "[prodc].files")
        needs = _as_str_list(prodc_tbl.get("needs", []), "[prodc].needs")
        file_globs = files + [g for g in needs if g not in files]
        if not file_globs:
            raise ConfigError("[prodc].files must list at least one glob")
        issue_globs = _as_str_list(prodc_tbl.get("issues", []), "[prodc].issues")
        board_name = prodc_tbl.get("name", "")
        if not isinstance(board_name, str):
            raise ConfigError("[prodc].name must be a string")

        adapters: dict[str, Adapter] = {}
        proofs = _as_dict(raw.get("proofs", {}), "[proofs]")
        for name, body in proofs.items():
            tbl = _as_dict(body, f"[proofs.{name}]")
            kind = tbl.get("kind")
            builder = _PROOF_BUILDERS.get(kind) if isinstance(kind, str) else None
            if builder is None:
                raise ConfigError(
                    f"[proofs.{name}]: unknown kind {kind!r} ({'|'.join(_PROOF_BUILDERS)})"
                )
            # `repo` points the adapter at a sibling repo checked out beside this one;
            # its paths then resolve under that repo and reads are wrapped by External.
            repo_field = tbl.get("repo")
            proof_root = root / repo_field if isinstance(repo_field, str) else root
            results = tbl.get("results")
            inner = builder(
                _Spec(name, tbl, proof_root, results if isinstance(results, str) else None)
            )
            adapters[name] = (
                External(inner, root / repo_field) if isinstance(repo_field, str) else inner
            )

        source_adapters: dict[str, SourceAdapter] = {}
        sources = _as_dict(raw.get("sources", {}), "[sources]")
        for name, body in sources.items():
            tbl = _as_dict(body, f"[sources.{name}]")
            kind = tbl.get("kind")
            source_builder = _SOURCE_BUILDERS.get(kind) if isinstance(kind, str) else None
            if source_builder is None:
                raise ConfigError(
                    f"[sources.{name}]: unknown kind {kind!r} ({'|'.join(_SOURCE_BUILDERS)})"
                )
            source_adapters[name] = source_builder(_Spec(name, tbl, root, None))

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

        lint_levels: dict[str, str | None] = {}
        for key in ("unjustified_views", "unjustified_stories", "link_without_why"):
            level = lint_tbl.get(key)
            if level is not None and level not in ("warn", "error"):
                raise ConfigError(f'[lint].{key} must be "warn" or "error"')
            lint_levels[key] = level

        ai_attestation = lint_tbl.get("ai_attestation", "warns")
        if ai_attestation not in ("counts", "warns"):
            raise ConfigError('[lint].ai_attestation must be "counts" or "warns"')

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

        principles_tbl = _as_dict(raw.get("principles", {}), "[principles]")
        if "scopes" in principles_tbl:
            scopes = _as_str_list(principles_tbl["scopes"], "[principles].scopes")
            if not scopes:
                raise ConfigError("[principles].scopes must list at least one scope")
            principle_scopes = tuple(scopes)
        else:
            principle_scopes = ("product",)
        if "packs" in principles_tbl:
            packs_raw = _as_str_list(principles_tbl["packs"], "[principles].packs")
            principle_packs = tuple(packs_raw)
        else:
            principle_packs = ()

        missing_catalog_level = lint_tbl.get("missing_catalog_principles", "warn")
        if missing_catalog_level not in ("warn", "error", "off"):
            raise ConfigError('[lint].missing_catalog_principles must be "warn", "error", or "off"')

        flows_tbl = _as_dict(raw.get("flows", {}), "[flows]")
        if "steps" in flows_tbl:
            steps = _as_str_list(flows_tbl["steps"], "[flows].steps")
            if not steps:
                raise ConfigError("[flows].steps must list at least one step")
            if len(set(steps)) != len(steps):
                raise ConfigError("[flows].steps must not repeat a step (order is its rank)")
            flow_steps = tuple(steps)
        else:
            flow_steps = ()

        return cls(
            root=root,
            file_globs=file_globs,
            issue_globs=issue_globs,
            adapters=adapters,
            source_adapters=source_adapters,
            duplicate_threshold=float(dup),
            stale_after_days=stale,
            importance_levels=importance_levels,
            importance_revisit_days=revisit,
            draft_max_age_days=draft_max_age,
            unjustified_views=lint_levels["unjustified_views"],
            unjustified_stories=lint_levels["unjustified_stories"],
            link_without_why=lint_levels["link_without_why"],
            ai_attestation=ai_attestation,
            default_draft=default_draft,
            callbacks=callbacks,
            callback_state_file=callback_state_file,
            principle_scopes=principle_scopes,
            principle_packs=principle_packs,
            missing_catalog_principles=missing_catalog_level,
            flow_steps=flow_steps,
            notices=_unknown_toml_keys(raw) + _unknown_packs(principle_packs),
            deprecations=_deprecated_toml(raw),
            name=board_name.strip(),
        )
