"""The issue register in ``docs/issues/``: read, write, and check its files.

One markdown file per piece of work that is known, scoped, and not being done right now. The
files are the store: there is no database, cache, or second copy. Everything derived (the README
index above all) is generated from the files and is never the source of truth. ``git`` and an
editor work on the register without this module.

Prior art. Beads (``bd``) has the ``blocked_by`` dependency graph used here, because "what can I
pick up now" needs it; its database store is not used. Backlog.md and ditz keep one file per
issue, as here. git-bug keeps issues as git objects, which need the tool to read.

Front matter has a small core that every folder enforces::

    title  status  area  owner  filed  blocked_by  fixed_in  needs  sources

``needs`` names the prodc needs an issue serves; ``sources`` holds pointers into other systems.
Each folder declares the rest in ``docs/issues/config.toml``: its ``areas`` vocabulary and any
extra fields. ``prodc issue init`` style adoption (:func:`infer_config`) writes that config from
the files already there, so adopting the register does not invalidate old issues. Unknown fields
are kept unchanged on every write.

Status::

    open -> in-progress -> done,  with blocked to the side

``done`` keeps the file and requires ``fixed_in``: the sha that was pushed to the mainline.
``closed`` and ``resolved`` are refused with a message that names ``done``.

cabildo imports this module as ``from prodc import issue_store as issues``. Keep the public names
and signatures stable.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as _dt
import os
import pathlib
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping
from typing import TypedDict, cast

from .model import Issue, IssueStatus

#: Where a register may live, in the order it is looked for. ``docs/issues`` is the convention.
#: The others are for repos that keep ``docs/`` out of git or have no ``docs/`` at all.
#: ``PRODC_ISSUES_DIR`` (or the older ``CABILDO_ISSUES_DIR``) overrides the search.
FOLDER_CANDIDATES = (("docs", "issues"), ("issues",), (".issues",))
CONFIG_NAME = "config.toml"
README_NAME = "README.md"

INDEX_BEGIN = "<!-- BEGIN GENERATED INDEX: `prodc issue reindex` -->"
#: The marker cabildo wrote. Still read; a reindex replaces it with :data:`INDEX_BEGIN`.
LEGACY_INDEX_BEGIN = "<!-- BEGIN GENERATED INDEX \u2014 `cabildo issues reindex` -->"
INDEX_END = "<!-- END GENERATED INDEX -->"


class IssueFormatError(ValueError):
    """A file in docs/issues/ does not obey the contract its config states."""


#: The issue statuses. Kept under this name for callers of the store.
Status = IssueStatus

#: Statuses other tools use for finished work. The store refuses them and names ``done``.
FOREIGN_CLOSED = ("closed", "resolved")

#: Core front matter, in render order. Extras follow, in the order the file had them.
CORE_ORDER = (
    "title",
    "status",
    "area",
    "owner",
    "filed",
    "blocked_by",
    "fixed_in",
    "needs",
    "sources",
)


# --------------------------------------------------------------------------- #
# What a folder requires of its issues
# --------------------------------------------------------------------------- #
#: Named patterns, so a config says what it means instead of carrying a regex. Anything not named
#: here is used as a regex directly.
PATTERNS = {
    "kebab": r"^[a-z0-9]+(-[a-z0-9]+)*$",
    "sha": r"^[0-9a-f]{7,40}$",
}


@dataclasses.dataclass(frozen=True)
class Field:
    """One project-declared front-matter field beyond the core."""

    name: str
    required: bool = False
    values: tuple[str, ...] = ()  # empty means free text
    is_list: bool = False  # a YAML block list rather than a scalar
    #: a file, relative to the issue folder, this field's value must appear in, and which must
    #: link back to the issue. One direction is not enough: a register that names a gap but does
    #: not point at the task is how the same gap gets found four times and fixed zero.
    crossref: str = ""
    #: `kebab`, `sha`, `slug`, or a regex. For fields whose shape matters but whose values cannot be
    #: enumerated: a tag vocabulary grows, but `Roast Detect` and `roast-detect` must not both
    #: exist, because then neither groups with the other.
    pattern: str = ""

    @property
    def regex(self) -> re.Pattern[str] | None:
        if not self.pattern:
            return None
        return re.compile(PATTERNS.get(self.pattern, self.pattern))

    def problems(self, value: str | tuple[str, ...] | None) -> list[str]:
        if value is None or value == ():
            return [f"missing required `{self.name}`"] if self.required else []
        got: tuple[str, ...] = value if isinstance(value, tuple) else (value,)
        if isinstance(value, tuple) and not self.is_list:
            return [f"`{self.name}` is a list, but this folder declares it a scalar"]
        if self.is_list and not isinstance(value, tuple):
            # Say what is actually wrong. An agent given only "does not match kebab" here spent
            # four attempts trying comma, comma-space and space as separators, then gave up and
            # filed with one tag instead of the four it meant, because nothing told it that a
            # delimited string was never going to be the answer.
            return [
                f"`{self.name}` is a list: pass a list of values, not the delimited "
                f"string {value!r}"
            ]
        out: list[str] = []
        if self.values:
            out += [
                f"unknown {self.name} {v!r}: one of {', '.join(self.values)}"
                for v in got
                if v not in self.values
            ]
        rx = self.regex
        if rx is not None:
            out += [
                f"{self.name} {v!r} does not match {self.pattern}" for v in got if not rx.match(v)
            ]
        return out


@dataclasses.dataclass(frozen=True)
class Config:
    """`docs/issues/config.toml`: what this folder's issues must say.

    `areas` has no default on purpose. It is the one field whose vocabulary cannot be guessed from
    outside the repo, and a tool that accepts any area silently accepts every typo as a new one.
    """

    areas: tuple[str, ...] = ()
    fields: Mapping[str, Field] = dataclasses.field(
        default_factory=lambda: cast(dict[str, Field], {})
    )
    index: bool = True
    date_style: str = "DMY"  # DMY → 03-08-2026-slug.md; YMD → 2026-08-03-slug.md
    #: groups where at least one member must be present. For "name the register entry, or say why
    #: there is none": an either/or that `required` cannot express, and where the point is that
    #: silence is not an allowed answer.
    require_one_of: tuple[tuple[str, ...], ...] = ()
    #: project fields to add as columns in the generated index. The index is for scanning, and what
    #: is worth scanning is exactly what the folder chose to track: scope and verify in one repo,
    #: priority in another. Core columns are always there.
    index_fields: tuple[str, ...] = ()
    #: The front matter, in the order it must appear. When set it does three jobs at once: `check`
    #: enforces the order, `render` writes exactly these keys (so a field the folder does not want,
    #: `filed`, say, which the filename already carries, is never added behind its back), and with
    #: `strict_fields` it is the allowed set. Front matter is then a schema rather than a bag.
    field_order: tuple[str, ...] = ()
    #: Reject any front-matter key not in `field_order`. Off by default: preserving a key you do not
    #: recognise is the safer failure. On, when a folder wants its schema closed.
    strict_fields: bool = False
    #: `fixed_in` must name a commit reachable from this branch. The sha that matters is the one
    #: that PUSHED: a worktree sha resolves until that worktree is pruned, and then the register
    #: points at nothing.
    fixed_in_on_branch: str = ""
    #: Headings (regexes, matched at the start of a `## ` heading) every issue body must carry.
    #: "Define done" is a rule every one of these folders states; this is the version that is
    #: enforced instead of hoped for.
    require_sections: tuple[str, ...] = ()
    #: What is exempt from `require_sections`, as "field=value" (e.g. "type=handoff"). A hand-off
    #: records tree state and resume order for work already in flight, so it carries no acceptance
    #: criteria of its own: it points at the issues that do.
    sections_exempt: str = ""
    #: Check that short shas cited in issue bodies are still reachable from some branch. An issue
    #: whose evidence is a commit that no longer exists is worse than one with no evidence: it reads
    #: as verified.
    check_body_shas: bool = False
    #: Add a table of finished work to the index, with the sha that fixed each. Closing keeps the
    #: file, so this is the payoff: "was this fixed, and by what?" answered by looking.
    index_done: bool = False
    #: Group the open work by a list field (tags, usually) under the table. Two issues that share a
    #: tag are usually one afternoon's work; the flat table cannot show that.
    index_group_by: str = ""
    #: The field whose declared `values` order ranks the board. Defaults to `priority` when a
    #: field of that name declares values, which is what these folders already called it.
    rank_by: str = ""
    #: Require `fixed_in` on a `done` issue. On by default: a code register closes an issue by
    #: naming the sha that pushed it. A register that is not tracking code (a personal agenda, say)
    #: turns this off, so `done` is just done with no sha to cite.
    closed_needs_fixed_in: bool = True
    #: Fields of which at most one issue in the register may carry a value: an exclusive flag such
    #: as a single "focus of the day". A second one set is a `check` error naming the conflict.
    singleton_fields: tuple[str, ...] = ()

    @property
    def ranking(self) -> Field | None:
        """The field that decides what comes first.

        `rank_by` names it; with nothing named, a field literally called `priority` that declares
        its values is used, because that is what every one of these folders called it without being
        asked. Declaration order IS the ranking: `values = ["P0", "P1", "P2"]` says P0 first, so
        there is no second place to keep the order in and no way for the two to disagree.
        """
        name = self.rank_by or "priority"
        field = self.fields.get(name)
        return field if field is not None and field.values else None

    def rank_key(self, issue: Issue) -> tuple[int, int, str]:
        """Sort order for the board: priority first, then the folder's own area order, then age.

        Priority dominates on purpose. A P0 in the area someone happened to list last is still the
        most important thing in the repo, and a board that buries it is worse than no board.
        """
        areas = {a: n for n, a in enumerate(self.areas)}
        field = self.ranking
        rank = len(field.values) if field else 0
        if field is not None:
            value = issue.extra.get(field.name)
            if isinstance(value, str) and value in field.values:
                rank = field.values.index(value)
        return (rank, areas.get(issue.area, len(areas)), issue.filed)

    @property
    def filename_re(self) -> re.Pattern[str]:
        head = (
            r"(\d{2})-(\d{2})-(\d{4})" if self.date_style == "DMY" else r"(\d{4})-(\d{2})-(\d{2})"
        )
        return re.compile(rf"^{head}-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")

    def filename(self, filed: str, slug: str) -> str:
        y, m, d = filed.split("-")
        return f"{d}-{m}-{y}-{slug}.md" if self.date_style == "DMY" else f"{y}-{m}-{d}-{slug}.md"

    def filed_from_name(self, name: str) -> str | None:
        m = self.filename_re.match(name)
        if not m:
            return None
        a, b, c = m.group(1), m.group(2), m.group(3)
        return f"{c}-{b}-{a}" if self.date_style == "DMY" else f"{a}-{b}-{c}"


DEFAULT_CONFIG = Config()


def _toml_list(raw: dict[str, object], key: str) -> list[object]:
    v = raw.get(key)
    return list(cast(list[object], v)) if isinstance(v, (list, tuple)) else []


def _toml_dict(raw: dict[str, object], key: str) -> dict[str, object]:
    v = raw.get(key)
    return cast(dict[str, object], v) if isinstance(v, dict) else {}


def _toml_str(raw: dict[str, object], key: str, default: str = "") -> str:
    v = raw.get(key)
    return str(v) if v is not None else default


def load_config(folder: pathlib.Path) -> Config:
    path = folder / CONFIG_NAME
    if not path.exists():
        return DEFAULT_CONFIG
    with path.open("rb") as fh:
        raw: dict[str, object] = cast(dict[str, object], tomllib.load(fh))
    fields: dict[str, Field] = {}
    for name_raw, spec_raw in _toml_dict(raw, "fields").items():
        spec = cast(dict[str, object], spec_raw) if isinstance(spec_raw, dict) else {}
        values_list: list[str] = [str(v) for v in _toml_list(spec, "values")]
        fields[str(name_raw)] = Field(
            name=str(name_raw),
            required=bool(spec.get("required", False)),
            values=tuple(values_list),
            is_list=bool(spec.get("list", False)),
            crossref=_toml_str(spec, "crossref"),
            pattern=_toml_str(spec, "pattern"),
        )
    style = _toml_str(raw, "date_style", "DMY").upper()
    if style not in ("DMY", "YMD"):
        raise IssueFormatError(f"{path}: date_style must be DMY or YMD, not {style!r}")
    groups: tuple[tuple[str, ...], ...] = tuple(
        tuple(str(x) for x in cast(list[object], g))
        for g in _toml_list(raw, "require_one_of")
        if isinstance(g, (list, tuple)) and g
    )
    order: tuple[str, ...] = tuple(str(k) for k in _toml_list(raw, "field_order"))
    missing = [k for k in ("title", "status", "area") if order and k not in order]
    if missing:
        raise IssueFormatError(
            f"{path}: field_order omits {', '.join(missing)}: those are core and every issue "
            f"must carry them, so leaving them out would make every file invalid"
        )
    sections = _toml_dict(raw, "sections")
    return Config(
        areas=tuple(str(a) for a in _toml_list(raw, "areas")),
        fields=fields,
        index=bool(raw.get("index", True)),
        date_style=style,
        require_one_of=groups,
        index_fields=tuple(str(f) for f in _toml_list(raw, "index_fields")),
        field_order=order,
        strict_fields=bool(raw.get("strict_fields", False)),
        fixed_in_on_branch=_toml_str(raw, "fixed_in_on_branch"),
        require_sections=tuple(str(s) for s in _toml_list(sections, "require")),
        sections_exempt=_toml_str(sections, "exempt"),
        check_body_shas=bool(raw.get("check_body_shas", False)),
        index_done=bool(raw.get("index_done", False)),
        index_group_by=_toml_str(raw, "index_group_by"),
        rank_by=_toml_str(raw, "rank_by"),
        closed_needs_fixed_in=bool(raw.get("closed_needs_fixed_in", True)),
        singleton_fields=tuple(str(s) for s in _toml_list(raw, "singleton_fields")),
    )


# --------------------------------------------------------------------------- #
# An issue
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class Problem:
    path: pathlib.Path
    message: str

    def __str__(self) -> str:
        return f"{self.path.name}: {self.message}"


# --------------------------------------------------------------------------- #
# Front matter: a small, deliberate YAML subset
# --------------------------------------------------------------------------- #
# Flat `key: value` scalars plus single-level block lists. That covers every issue in the repos this
# was built from and nothing more, which is why this module has no third-party dependency and stays
# fast enough to run in a pre-commit hook. If a field wants deeper structure, that is a signal it
# wants to be prose in the body instead.

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
_ITEM_RE = re.compile(r"^\s+-\s*(.*)$")


#: Plain scalars that YAML 1.1 (PyYAML's ``safe_load``) reads as a bool, null, int, or float.
#: The store reads them as strings, so ``render`` quotes them to keep both readers in agreement.
_YAML_TYPED = re.compile(
    r"""^(?:
      y|Y|yes|Yes|YES|n|N|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF
    | ~|null|Null|NULL
    | [-+]?0b[0-1_]+ | [-+]?0[0-7_]+ | [-+]?(?:0|[1-9][0-9_]*) | [-+]?0x[0-9a-fA-F_]+
    | [-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+
    | [-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)? | \.[0-9_]+(?:[eE][-+][0-9]+)?
    | [-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]* | [-+]?\.(?:inf|Inf|INF) | \.(?:nan|NaN|NAN)
    | <<
    )$""",
    re.VERBOSE,
)
#: A plain scalar may not start with one of these YAML indicators.
_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r", "/": "/", "0": "\0"}


def _unquote(raw: str) -> str | None:
    """One scalar as a string, or None for an empty or null value.

    A double-quoted value has its backslash escapes undone. A single-quoted value has ``''``
    read as one ``'``. Both follow YAML, so ``yaml.safe_load`` reads the same string.
    """
    v = raw.strip()
    if v in ("null", "~", ""):
        return None
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return re.sub(r"\\(.)", lambda m: _UNESCAPES.get(m.group(1), m.group(0)), v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def _needs_quotes(value: str) -> bool:
    """True when a plain scalar would not read back as this same string."""
    return (
        not value
        or value != value.strip()
        or value[0] in _INDICATORS
        or re.search(r"[:#\"\\]|[\x00-\x1f]", value) is not None
        or _YAML_TYPED.match(value) is not None
    )


def _quote(value: str) -> str:
    """A scalar as YAML text: plain when that reads back unchanged, else double-quoted."""
    if not _needs_quotes(value):
        return value
    return '"' + "".join(_ESCAPES.get(c, c) for c in value) + '"'


def _split_front(text: str, path: pathlib.Path) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise IssueFormatError(f"{path.name}: no YAML front matter: the file must start with `---`")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise IssueFormatError(f"{path.name}: unterminated front matter")
    return parts[1], parts[2]


def _parse_front(front: str, path: pathlib.Path) -> dict[str, str | tuple[str, ...] | None]:
    fields: dict[str, str | tuple[str, ...] | None] = {}
    key: str | None = None
    for line in front.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _ITEM_RE.match(line)
        if item is not None:
            if key is None:
                raise IssueFormatError(f"{path.name}: list item with no key: {line!r}")
            current = fields.get(key)
            got = current if isinstance(current, tuple) else ()
            fields[key] = (*got, _unquote(item.group(1)) or "")
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise IssueFormatError(f"{path.name}: front matter line is not `key: value`: {line!r}")
        key = str(m.group(1))
        inline = m.group(2).strip()
        if inline.startswith("[") and inline.endswith("]"):
            body = inline[1:-1].strip()
            fields[key] = tuple(_unquote(p) or "" for p in body.split(",")) if body else ()
        else:
            fields[key] = _unquote(inline)
    return fields


def _as_list(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    """A list field: a bare scalar is a list of one, and empty items are dropped."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(v for v in value if v)


def parse(text: str, path: pathlib.Path, config: Config = DEFAULT_CONFIG) -> Issue:
    front, body = _split_front(text, path)
    fields = _parse_front(front, path)

    def required(key: str) -> str:
        value = fields.get(key)
        if value is None or isinstance(value, tuple):
            raise IssueFormatError(f"{path.name}: front matter is missing required `{key}`")
        return value

    raw_status = required("status")
    if raw_status in FOREIGN_CLOSED:
        raise IssueFormatError(
            f"{path.name}: status {raw_status!r} is not a status here; finished work is `done` "
            "with `fixed_in` (prodc issue close <name> --fixed-in <sha>)"
        )
    if raw_status not in tuple(Status):
        raise IssueFormatError(
            f"{path.name}: unknown status {raw_status!r}: one of {', '.join(Status)}"
        )

    # `filed` is a fact the filename already carries, so a file that omits it is not malformed.
    filed = fields.get("filed")
    if not isinstance(filed, str):
        filed = config.filed_from_name(path.name) or _dt.date.today().isoformat()

    blocked = fields.get("blocked_by")
    if blocked is None:
        blocked_by: tuple[str, ...] = ()
    elif isinstance(blocked, tuple):
        blocked_by = tuple(b for b in blocked if b)
    else:
        blocked_by = (blocked,)

    fixed_in = fields.get("fixed_in")
    owner = fields.get("owner")
    needs = _as_list(fields.get("needs"))
    sources = _as_list(fields.get("sources"))
    extra: dict[str, str | tuple[str, ...]] = {
        k: v for k, v in fields.items() if k not in CORE_ORDER and v is not None
    }
    return Issue(
        path=path,
        title=required("title"),
        status=Status(raw_status),
        area=required("area"),
        filed=filed,
        owner=owner if isinstance(owner, str) else None,
        blocked_by=blocked_by,
        fixed_in=fixed_in if isinstance(fixed_in, str) else None,
        extra=extra,
        body=body,
        order=tuple(fields),
        needs=needs,
        sources=sources,
    )


def _render_value(key: str, value: str | tuple[str, ...]) -> list[str]:
    if isinstance(value, tuple):
        return [f"{key}:"] + [f"  - {_quote(v)}" for v in value]
    return [f"{key}: {_quote(value)}"]


def _core_values(issue: Issue) -> dict[str, str | tuple[str, ...] | None]:
    return {
        "title": issue.title,
        "status": str(issue.status),
        "area": issue.area,
        "owner": issue.owner,
        "filed": issue.filed,
        "blocked_by": issue.blocked_by or None,
        "fixed_in": issue.fixed_in,
        "needs": issue.needs or None,
        "sources": issue.sources or None,
    }


def render(issue: Issue, config: Config = DEFAULT_CONFIG) -> str:
    """Front matter plus body.

    With `field_order` set, exactly those keys are written, in that order, and an empty one is
    omitted rather than written as null. That is what lets a folder keep a closed schema: a tool
    that adds `filed:` on every save (a key the filename already carries) would make every write
    fail a strict check, and the agent would have no idea why.
    """
    if config.field_order:
        values = dict(_core_values(issue)) | dict(issue.extra)
        lines = ["---"]
        # needs and sources are never dropped: with strict_fields, check reports them instead.
        keys = (
            *config.field_order,
            *(k for k in ("needs", "sources") if k not in config.field_order),
        )
        for key in keys:
            value = values.get(key)
            if value is None or value == ():
                continue
            lines += (
                _render_value(key, value)
                if isinstance(value, tuple)
                else [f"{key}: {_quote(str(value))}"]
            )
        lines.append("---")
    else:
        lines = [
            "---",
            f"title: {_quote(issue.title)}",
            f"status: {issue.status}",
            f"area: {_quote(issue.area)}",
            f"owner: {_quote(issue.owner) if issue.owner else 'null'}",
            f"filed: {issue.filed}",
        ]
        if issue.blocked_by:
            lines += _render_value("blocked_by", issue.blocked_by)
        if issue.fixed_in:
            lines.append(f"fixed_in: {_quote(issue.fixed_in)}")
        if issue.needs:
            lines += _render_value("needs", issue.needs)
        if issue.sources:
            lines += _render_value("sources", issue.sources)
        for key, value in issue.extra.items():
            lines += _render_value(key, value)
        lines.append("---")
    # The newline after the closing `---` is that line's terminator, not part of the body; the
    # split that produced `body` already consumed it. Adding it back here is what makes
    # render(parse(text)) == text, so a status change is a one-line diff and not a one-line diff
    # plus a silently eaten blank line.
    return "\n".join(lines) + "\n" + issue.body


def load(path: pathlib.Path, config: Config = DEFAULT_CONFIG) -> Issue:
    return parse(path.read_text(), path, config)


def save(issue: Issue, config: Config = DEFAULT_CONFIG) -> None:
    issue.path.write_text(render(issue, config))


def load_all(
    folder: pathlib.Path, config: Config | None = None
) -> tuple[tuple[Issue, ...], tuple[Problem, ...]]:
    """Every issue in the folder, plus the files that could not be parsed. Returning both means one
    malformed file never hides the rest of the register.
    """
    config = load_config(folder) if config is None else config
    issues: list[Issue] = []
    problems: list[Problem] = []
    for path in sorted(folder.glob("*.md")):
        if path.name == README_NAME:
            continue
        try:
            issues.append(load(path, config))
        except IssueFormatError as exc:
            problems.append(Problem(path, str(exc).split(": ", 1)[-1]))
    return tuple(issues), tuple(problems)


# --------------------------------------------------------------------------- #
# What can I pick up right now
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class Waiting:
    issue: Issue
    on: tuple[str, ...]  # slugs of open issues blocking it
    reason: str


@dataclasses.dataclass(frozen=True)
class Board:
    """What is ready to pick up, and why each other open issue is not.

    A list of everything is not an answer; it is the thing that made the question hard. `ready` is
    work whose blockers are all closed and which nobody has taken. `waiting` says what each of the
    others is actually stuck behind, so the reader can go unstick one instead of guessing.
    """

    ready: tuple[Issue, ...]
    waiting: tuple[Waiting, ...]
    mine: tuple[Issue, ...]
    done: int


def newly_ready(
    folder: pathlib.Path, closed_slug: str, config: Config | None = None
) -> list[Issue]:
    """Open issues that named `closed_slug` as a blocker and now have no open blocker
    left: the work that just became pickup-able because it closed. Empty when nothing
    was waiting on it.
    """
    config = load_config(folder) if config is None else config
    found, _ = load_all(folder, config)
    open_slugs = {i.slug for i in found if i.open}
    return [
        i
        for i in found
        if i.open and closed_slug in i.blocked_by and not any(s in open_slugs for s in i.blocked_by)
    ]


def board(folder: pathlib.Path, config: Config | None = None, *, owner: str | None = None) -> Board:
    config = load_config(folder) if config is None else config
    issues, _ = load_all(folder, config)
    by_slug = {i.slug: i for i in issues}
    open_slugs = {i.slug for i in issues if i.open}

    ready: list[Issue] = []
    waiting: list[Waiting] = []
    mine: list[Issue] = []
    for issue in issues:
        if not issue.open:
            continue
        if owner is not None and issue.owner == owner:
            mine.append(issue)
            continue
        blockers = tuple(s for s in issue.blocked_by if s in open_slugs)
        if blockers:
            titles = ", ".join(by_slug[s].title for s in blockers)
            waiting.append(Waiting(issue, blockers, f"blocked by {titles}"))
        elif issue.status is Status.BLOCKED:
            who = f"@{issue.owner}" if issue.owner else "nobody named"
            waiting.append(Waiting(issue, (), f"blocked on a decision: {who} can unblock it"))
        elif issue.owner:
            waiting.append(Waiting(issue, (), f"taken by @{issue.owner}"))
        else:
            ready.append(issue)

    ready.sort(key=config.rank_key)
    mine.sort(key=config.rank_key)
    waiting.sort(key=lambda w: config.rank_key(w.issue))
    return Board(
        ready=tuple(ready),
        waiting=tuple(waiting),
        mine=tuple(mine),
        done=sum(1 for i in issues if not i.open),
    )


# --------------------------------------------------------------------------- #
# The invariants
# --------------------------------------------------------------------------- #
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_BODY_SHA_RE = re.compile(r"`([0-9a-f]{8,40})`")


# --------------------------------------------------------------------------- #
# Asking git: the checks a file alone cannot make
# --------------------------------------------------------------------------- #
# A register's claims point outward: `fixed_in` names a commit, and bodies cite shas as evidence.
# Neither can be graded by reading the folder, and both fail in the same quiet way: the sha is
# there, it looks right, and it resolves to nothing. Every helper degrades to "no opinion" when git
# is missing or the folder is not in a repo, because a guard that cannot run must not invent a
# verdict.
def _repo_root(folder: pathlib.Path) -> pathlib.Path | None:
    for base in (folder.resolve(), *folder.resolve().parents):
        if (base / ".git").exists():
            return base
    return None


class _Git:
    """Git questions about one repo, asked at most once each.

    `check` runs in a pre-commit hook over every issue in the folder, and issue bodies cite the same
    commits repeatedly: without the cache a 40-issue register would fork git a few hundred times on
    every commit.
    """

    def __init__(self, root: pathlib.Path | None):
        self.root = root
        self._cache: dict[tuple[str, str], bool] = {}

    @property
    def usable(self) -> bool:
        return self.root is not None and bool(shutil.which("git"))

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, timeout=10
        )

    def _ask(self, kind: str, sha: str, fn: Callable[[], bool]) -> bool:
        key = (kind, sha)
        if key not in self._cache:
            try:
                self._cache[key] = fn()
            except (OSError, subprocess.SubprocessError):
                self._cache[key] = True  # cannot tell → do not accuse
        return self._cache[key]

    def is_commit(self, sha: str) -> bool:
        return self._ask(
            "commit", sha, lambda: self._run("cat-file", "-t", sha).stdout.strip() == "commit"
        )

    def on_any_branch(self, sha: str) -> bool:
        return self._ask(
            "branch", sha, lambda: bool(self._run("branch", "--contains", sha).stdout.strip())
        )

    def is_ancestor(self, sha: str, branch: str) -> bool:
        return self._ask(
            f"anc:{branch}",
            sha,
            lambda: self._run("merge-base", "--is-ancestor", sha, branch).returncode == 0,
        )

    def has_ref(self, ref: str) -> bool:
        return self._ask(
            "ref", ref, lambda: self._run("rev-parse", "--verify", "--quiet", ref).returncode == 0
        )


def check(folder: pathlib.Path, config: Config | None = None) -> list[Problem]:
    """Every rule this folder's config states, enforced. Returns [] when the folder is honest.

    A declared invariant that nothing enforces reads as verified to anyone skimming it, which is
    precisely how an index drifts from its own folder for weeks without anybody noticing.
    """
    config = load_config(folder) if config is None else config
    issues, parse_problems = load_all(folder, config)
    problems = list(parse_problems)
    slugs = {i.slug for i in issues}
    open_slugs = {i.slug for i in issues if i.open}
    seen: dict[str, pathlib.Path] = {}
    git = _Git(_repo_root(folder))

    for issue in issues:
        p = issue.path
        if not config.filename_re.match(p.name):
            shape = "DD-MM-YYYY" if config.date_style == "DMY" else "YYYY-MM-DD"
            problems.append(Problem(p, f"filename must be `{shape}-short-kebab-summary.md`"))
        first = seen.get(issue.slug)
        if first is not None:
            problems.append(Problem(p, f"duplicate slug: {first.name} covers the same thing"))
        else:
            seen[issue.slug] = p

        if config.areas and issue.area not in config.areas:
            problems.append(
                Problem(p, f"unknown area {issue.area!r}: one of {', '.join(config.areas)}")
            )
        if config.closed_needs_fixed_in and issue.status is Status.DONE and not issue.fixed_in:
            problems.append(
                Problem(
                    p,
                    "status is `done` with no `fixed_in`: name the sha that pushed on the "
                    "mainline, or the folder stops being evidence of anything",
                )
            )
        if issue.status is not Status.DONE and issue.fixed_in:
            problems.append(
                Problem(
                    p,
                    f"`fixed_in: {issue.fixed_in}` on an issue that is `{issue.status}`: "
                    f"either it pushed and this is done, or the sha does not belong here",
                )
            )
        problems.extend(_fixed_in_problems(issue, config, git))
        problems.extend(_section_problems(issue, config))
        problems.extend(_body_sha_problems(issue, config, git))
        if config.field_order:
            expected = [k for k in config.field_order if k in issue.order]
            if list(issue.order) != expected and issue.order:
                problems.append(
                    Problem(
                        p,
                        f"front matter order {list(issue.order)} != {expected}",
                    )
                )
            if config.strict_fields:
                for key in issue.order:
                    if key not in config.field_order:
                        problems.append(Problem(p, f"unknown field {key!r}"))
        if issue.status is Status.IN_PROGRESS and not issue.owner:
            problems.append(Problem(p, "in-progress with no owner: say who is doing it"))
        if issue.status is Status.BLOCKED and not issue.owner and not issue.blocked_by:
            problems.append(
                Problem(
                    p,
                    "blocked with neither an owner nor a `blocked_by`: name who can "
                    "unblock it or which issue it waits on. Silence reads as an oversight",
                )
            )
        for slug in issue.blocked_by:
            if slug not in slugs:
                problems.append(
                    Problem(p, f"blocked_by names {slug!r}, which is not an issue here")
                )
        if issue.status is Status.DONE and any(s in open_slugs for s in issue.blocked_by):
            still = ", ".join(s for s in issue.blocked_by if s in open_slugs)
            problems.append(Problem(p, f"done, but still blocked_by open work: {still}"))

        for field in config.fields.values():
            for message in field.problems(issue.extra.get(field.name)):
                problems.append(Problem(p, message))
        for group in config.require_one_of:
            if not any(issue.extra.get(k) for k in group):
                problems.append(
                    Problem(
                        p,
                        f"none of {', '.join('`' + k + '`' for k in group)} is set: say which one "
                        f"applies, or why none does. Silence reads as an oversight and gets "
                        f"re-litigated",
                    )
                )
        problems.extend(_broken_links(issue, folder))

    problems.extend(_cycles(issues))
    problems.extend(_singletons(issues, config))
    problems.extend(_crossrefs(folder, issues, config))
    problems.extend(_index_problems(folder, issues, config))
    return problems


def _singletons(issues: tuple[Issue, ...], config: Config) -> list[Problem]:
    """Enforce that an exclusive field is set on at most one issue.

    A "focus of the day" flag means nothing if two issues carry it; the point of the field is that
    exactly one does. Each offender is named the others, so the fix is obvious from any one file.
    """
    out: list[Problem] = []
    for name in config.singleton_fields:
        holders = [i for i in issues if i.extra.get(name)]
        if len(holders) <= 1:
            continue
        others = ", ".join(h.path.name for h in holders)
        for issue in holders:
            out.append(
                Problem(issue.path, f"`{name}` is exclusive but is set on {len(holders)}: {others}")
            )
    return out


def _crossrefs(folder: pathlib.Path, issues: tuple[Issue, ...], config: Config) -> list[Problem]:
    """Enforce a field's two-way link with another document.

    Some registers are the record of *what is wrong*, and the issue folder holds one entry broken
    out into a task. Checking only that the issue names the register lets the register go silently
    stale; checking only the back-link lets an issue cite an entry that was never written.
    """
    out: list[Problem] = []
    for field in config.fields.values():
        if not field.crossref:
            continue
        target = (folder / field.crossref).resolve()
        if not target.exists():
            out.append(
                Problem(
                    folder / CONFIG_NAME,
                    f"fields.{field.name}.crossref points at {field.crossref}, which does not exist",
                )
            )
            continue
        text = target.read_text()
        for issue in issues:
            value = issue.extra.get(field.name)
            if not isinstance(value, str) or not value:
                continue
            if not re.search(rf"\b{re.escape(value)}\b", text):
                out.append(
                    Problem(issue.path, f"{field.name} {value} does not exist in {target.name}")
                )
            elif issue.path.name not in text:
                out.append(
                    Problem(
                        issue.path,
                        f"{target.name} does not link back to this file: without the back-link the "
                        f"task is invisible from the register that is supposed to track it",
                    )
                )
    return out


def _fixed_in_problems(issue: Issue, config: Config, git: _Git) -> list[Problem]:
    """Grade the sha a closed issue points at.

    `fixed_in` is the whole reason closing keeps the file: it is the answer to "was this fixed, and
    by what?". A sha that does not resolve, or that only resolves inside the worktree it was written
    in, answers that question wrongly and confidently: which is worse than not answering it.
    """
    branch = config.fixed_in_on_branch
    if not issue.fixed_in or not branch or not git.usable:
        return []
    sha = issue.fixed_in
    if not re.match(PATTERNS["sha"], sha):
        return [Problem(issue.path, f"fixed_in {sha!r} is not a sha")]
    if not git.is_commit(sha):
        return [Problem(issue.path, f"fixed_in {sha} is not a commit in this repo")]
    if not git.has_ref(branch):
        return []  # no such branch here (a fresh clone, a fork): no opinion
    if not git.is_ancestor(sha, branch):
        return [
            Problem(
                issue.path,
                f"fixed_in {sha} is not on {branch}: record the sha that PUSHED, not the worktree "
                f"one; the push path re-commits, and a worktree sha resolves only until it is pruned",
            )
        ]
    return []


def _section_problems(issue: Issue, config: Config) -> list[Problem]:
    """ "Define done" is a rule every one of these folders states. This is the enforced version.

    The exemption is real work, not a loophole: a hand-off records tree state and resume order for
    work already in flight, so it has no acceptance criteria of its own: it points at the issues
    that do.
    """
    if not config.require_sections:
        return []
    if "=" in config.sections_exempt:
        key, _, value = config.sections_exempt.partition("=")
        if issue.extra.get(key.strip()) == value.strip():
            return []
    headings = re.findall(r"^##+\s*(.+)$", issue.body, re.MULTILINE)
    out: list[Problem] = []
    for wanted in config.require_sections:
        rx = re.compile(wanted)
        if not any(rx.match(h.strip()) for h in headings):
            out.append(Problem(issue.path, f"no '## {wanted}' section: say how this gets closed"))
    return out


def _body_sha_problems(issue: Issue, config: Config, git: _Git) -> list[Problem]:
    """A cited commit that is on no branch dies at the next gc, and the citation reads as evidence
    right up until someone tries to follow it.
    """
    if not config.check_body_shas or not git.usable:
        return []
    out: list[Problem] = []
    for sha in sorted(set(_BODY_SHA_RE.findall(issue.body))):
        if git.is_commit(sha) and not git.on_any_branch(sha):
            out.append(
                Problem(
                    issue.path,
                    f"cites {sha}, which is on no branch: it dies at the next gc, and until then it "
                    f"reads as evidence",
                )
            )
    return out


def _cycles(issues: Iterable[Issue]) -> list[Problem]:
    """A blocked_by loop means nothing in it is ever ready, and the board goes quietly empty rather
    than loudly wrong. Cheap to detect, invisible otherwise.
    """
    graph = {i.slug: tuple(i.blocked_by) for i in issues}
    paths = {i.slug: i.path for i in issues}
    state: dict[str, int] = {}
    out: list[Problem] = []

    def walk(node: str, trail: tuple[str, ...]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            loop = " → ".join((*trail[trail.index(node) :], node))
            out.append(
                Problem(paths[node], f"blocked_by cycle: {loop}: nothing in it can be ready")
            )
            return
        state[node] = 1
        for nxt in graph.get(node, ()):
            if nxt in graph:
                walk(nxt, (*trail, node))
        state[node] = 2

    for slug in graph:
        walk(slug, ())
    # One loop is reported once per entry point; collapse to distinct messages.
    return list({p.message: p for p in out}.values())


def _broken_links(issue: Issue, folder: pathlib.Path) -> list[Problem]:
    out: list[Problem] = []
    for match in _LINK_RE.finditer(issue.body):
        target = match.group(2).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "[")):
            continue
        if not (folder / target).resolve().exists():
            out.append(Problem(issue.path, f"broken relative link: {target}"))
    return out


def _index_problems(
    folder: pathlib.Path, issues: tuple[Issue, ...], config: Config
) -> list[Problem]:
    readme = folder / README_NAME
    if not config.index or not readme.exists():
        return []
    text = readme.read_text()
    if not _has_region(text):
        return [Problem(readme, f"README has no generated-index region ({INDEX_BEGIN})")]
    fresh = _replace_region(text, _index_table(issues, config))
    if fresh != text.replace(LEGACY_INDEX_BEGIN, INDEX_BEGIN, 1):
        return [
            Problem(
                readme,
                "the generated index is stale: run `prodc issue reindex`. A follow-up that "
                "nobody can see is the failure this folder exists to prevent",
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# The generated index
# --------------------------------------------------------------------------- #
def _cell(value: str | tuple[str, ...] | None) -> str:
    if value is None:
        return "—"
    return ", ".join(value) if isinstance(value, tuple) else str(value)


def _index_table(issues: tuple[Issue, ...], config: Config = DEFAULT_CONFIG) -> str:
    live = [i for i in issues if i.open]
    if not live:
        return "_No open follow-ups._"
    heads = [
        "Issue",
        "Area",
        *(f.capitalize() for f in config.index_fields),
        "Status",
        "Waiting on",
    ]
    rows = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    open_slugs = {i.slug for i in live}
    for issue in sorted(live, key=lambda i: (i.area, i.path.name)):
        owner = f" · @{issue.owner}" if issue.owner else ""
        blockers = ", ".join(s for s in issue.blocked_by if s in open_slugs) or "—"
        extras = [_cell(issue.extra.get(f)) for f in config.index_fields]
        rows.append(
            "| "
            + " | ".join(
                [
                    f"[{issue.title}]({issue.path.name})",
                    issue.area,
                    *extras,
                    f"{issue.status}{owner}",
                    blockers,
                ]
            )
            + " |"
        )
    done = [i for i in issues if not i.open]
    if config.index_group_by:
        grouped = _index_groups(live, config.index_group_by)
        if grouped:
            rows += ["", f"**By {config.index_group_by}**", "", grouped]
    if config.index_done and done:
        rows += ["", "**Done**", "", "| Issue | Area | Fixed in |", "|---|---|---|"]
        rows += [
            f"| [{i.title}]({i.path.name}) | {i.area} | `{i.fixed_in or '?'}` |"
            for i in sorted(done, key=lambda i: (i.area, i.path.name))
        ]

    counts = ", ".join(
        f"{sum(1 for i in live if i.status is s)} {s}"
        for s in Status
        if any(i.status is s for i in live)
    )
    tail = f"{len(live)} open — {counts}" + (f"; {len(done)} done" if done else "")
    rows += ["", f"_{tail}. Generated; edit the files, then `prodc issue reindex`._"]
    return "\n".join(rows)


def _index_groups(live: list[Issue], key: str) -> str:
    """Open work grouped by a list field. Only groups of two or more: a "group" of one is the flat
    table again with extra steps, and it buries the clusters that are the point.
    """
    index: dict[str, list[Issue]] = {}
    for issue in live:
        value = issue.extra.get(key)
        for item in value if isinstance(value, tuple) else (value,) if value else ():
            index.setdefault(str(item), []).append(issue)
    shared = {k: v for k, v in index.items() if len(v) > 1}
    lines = [
        f"- **`{k}`** ({len(shared[k])}) — "
        + ", ".join(
            f"[{i.slug}]({i.path.name})" for i in sorted(shared[k], key=lambda i: i.path.name)
        )
        for k in sorted(shared, key=lambda k: (-len(shared[k]), k))
    ]
    singles = sorted(k for k in index if len(index[k]) == 1)
    if singles:
        lines += ["", "Single-use: " + ", ".join(f"`{s}`" for s in singles) + "."]
    return "\n".join(lines)


def render_index(folder: pathlib.Path, config: Config | None = None) -> str:
    config = load_config(folder) if config is None else config
    issues, _ = load_all(folder, config)
    return _index_table(issues, config)


def _has_region(text: str) -> bool:
    """True when the text has a begin marker (new or legacy) and the end marker."""
    return (INDEX_BEGIN in text or LEGACY_INDEX_BEGIN in text) and INDEX_END in text


def _replace_region(text: str, table: str) -> str:
    """The text with the index region set to ``table`` and a legacy marker made current."""
    text = text.replace(LEGACY_INDEX_BEGIN, INDEX_BEGIN, 1)
    start = text.index(INDEX_BEGIN) + len(INDEX_BEGIN)
    end = text.index(INDEX_END)
    return text[:start] + "\n" + table + "\n" + text[end:]


def reindex(folder: pathlib.Path, config: Config | None = None) -> None:
    config = load_config(folder) if config is None else config
    readme = folder / README_NAME
    if not config.index or not readme.exists():
        return
    text = readme.read_text()
    if not _has_region(text):
        raise IssueFormatError(f"{readme.name}: no generated-index region to rewrite")
    readme.write_text(_replace_region(text, render_index(folder, config)))


def _touch_index(folder: pathlib.Path, config: Config) -> None:
    """Regenerate the index after a write. A failure here is ignored so the write still stands:
    the file is the store, and the index is generated from it.
    """
    with contextlib.suppress(IssueFormatError, OSError):
        reindex(folder, config)


# --------------------------------------------------------------------------- #
# Filing and moving work
# --------------------------------------------------------------------------- #
def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "-".join(slug.split("-")[:12])


def resolve(folder: pathlib.Path, name: str) -> pathlib.Path:
    """A filename, or any unambiguous fragment of one. Ambiguity is an error rather than a guess:
    picking the first match is how an agent edits an issue nobody asked it to touch.
    """
    if name.endswith(".md") and (folder / name).exists():
        return folder / name
    matches = [p for p in folder.glob("*.md") if p.name != README_NAME and name in p.name]
    if not matches:
        raise IssueFormatError(f"no such issue: {name}")
    if len(matches) > 1:
        raise IssueFormatError(f"ambiguous: {sorted(m.name for m in matches)}")
    return matches[0]


def file_issue(
    folder: pathlib.Path,
    *,
    title: str,
    area: str,
    body: str,
    owner: str | None = None,
    status: Status = Status.OPEN,
    blocked_by: Iterable[str] = (),
    extra: Mapping[str, str | tuple[str, ...]] | None = None,
    today: str | None = None,
    config: Config | None = None,
    needs: Iterable[str] = (),
    sources: Iterable[str] = (),
) -> pathlib.Path:
    """Write a new issue file and return its path.

    ``needs`` and ``sources`` given inside ``extra`` are moved to their own fields.
    """
    config = load_config(folder) if config is None else config
    if config.areas and area not in config.areas:
        raise IssueFormatError(f"unknown area {area!r}: one of {', '.join(config.areas)}")
    filed = today or _dt.date.today().isoformat()
    path = folder / config.filename(filed, slugify(title))
    if path.exists():
        raise IssueFormatError(f"{path.name} already exists: edit it, or pick a distinct title")
    issue = Issue(
        path=path,
        title=title,
        status=status,
        area=area,
        filed=filed,
        owner=owner,
        blocked_by=tuple(blocked_by),
        extra={k: v for k, v in (extra or {}).items() if k not in ("needs", "sources")},
        body=body if body.startswith("\n") else "\n" + body,
        needs=tuple(needs) or _as_list((extra or {}).get("needs")),
        sources=tuple(sources) or _as_list((extra or {}).get("sources")),
    )
    missing = [m for f in config.fields.values() for m in f.problems(issue.extra.get(f.name))]
    if missing:
        raise IssueFormatError("; ".join(missing))
    save(issue, config)
    _touch_index(folder, config)
    return path


def update(
    folder: pathlib.Path, name: str, config: Config | None = None, **changes: object
) -> Issue:
    """Edit one issue's front matter. `extra` fields are merged, not replaced, so setting one
    project field cannot silently drop the others.
    """
    config = load_config(folder) if config is None else config
    issue = load(resolve(folder, name), config)
    raw_extra = changes.pop("extra", None)
    extra_patch: Mapping[str, str | tuple[str, ...]] = (
        cast(Mapping[str, str | tuple[str, ...]], raw_extra)
        if isinstance(raw_extra, Mapping)
        else {}
    )
    extra = dict(issue.extra) | dict(extra_patch)
    for key in ("needs", "sources"):
        if key in extra:
            changes.setdefault(key, _as_list(extra.pop(key)))
    updated = dataclasses.replace(issue, extra=extra, **changes)
    save(updated, config)
    _touch_index(folder, config)
    return updated


def claim(
    folder: pathlib.Path,
    name: str,
    *,
    owner: str,
    force: bool = False,
    config: Config | None = None,
) -> Issue:
    """Put a name on a follow-up and move it to in-progress. Refuses to steal by default: an owner
    that silently changes hands is how two agents end up doing the same work.
    """
    config = load_config(folder) if config is None else config
    issue = load(resolve(folder, name), config)
    if issue.owner and issue.owner != owner and not force:
        raise IssueFormatError(
            f"{issue.path.name} is already owned by @{issue.owner}: pass force to take it"
        )
    status = Status.IN_PROGRESS if issue.status is Status.OPEN else issue.status
    updated = dataclasses.replace(issue, owner=owner, status=status)
    save(updated, config)
    _touch_index(folder, config)
    return updated


def release(folder: pathlib.Path, name: str, config: Config | None = None) -> Issue:
    """Drop the owner and put it back on the board: the honest move when you stop, so it does not
    look taken forever.
    """
    config = load_config(folder) if config is None else config
    issue = load(resolve(folder, name), config)
    status = Status.OPEN if issue.status is Status.IN_PROGRESS else issue.status
    updated = dataclasses.replace(issue, owner=None, status=status)
    save(updated, config)
    _touch_index(folder, config)
    return updated


def close(folder: pathlib.Path, name: str, *, fixed_in: str, config: Config | None = None) -> Issue:
    """Mark it done. `fixed_in` is required because closing without naming what fixed it is how a
    register stops being evidence, and it must be the sha that pushed on the mainline, not the one
    from a worktree that will be pruned.
    """
    config = load_config(folder) if config is None else config
    if not fixed_in.strip():
        raise IssueFormatError("fixed_in is required: name the commit that pushed the fix")
    issue = load(resolve(folder, name), config)
    updated = dataclasses.replace(issue, status=Status.DONE, fixed_in=fixed_in.strip())
    save(updated, config)
    _touch_index(folder, config)
    return updated


# --------------------------------------------------------------------------- #
# Adoption: describe the folder that already exists
# --------------------------------------------------------------------------- #
STARTER_README = """\
# docs/issues: follow-ups with an owner

One file per follow-up, self-contained, with YAML front matter. This folder is for work that is
**known, scoped, and not being done right now**: what a session leaves behind when it pushes its
main change. Without a file, that work stays in a chat log nobody reads again, and nobody owns it.

**The files are the store.** No database, no second copy: an issue is markdown in git, readable and
editable by hand. The index below is generated from the files and is never the source of truth.

## The rules that make one worth writing

1. **Answerable cold.** Assume the reader has none of the author's context and no access to the
   session that found it. Concrete instances, file:line, the actual commands.
2. **Say what is MEASURED and what is INFERRED.** Separately, and in those words. An issue that
   states an inference as a finding sends the next person to fix the wrong thing, and they will
   believe you because you wrote it down.
3. **Define done.** Not "improve X", but the specific observation that will be true afterwards, and
   how to make it. `verify:` says which kind of evidence closes it, because they are different
   claims: `test` (a red-then-green test is enough), `probe` (only sensing the real thing counts),
   `inspect` (the artifact itself is the evidence).
4. **Name what you deliberately did NOT do,** with the reason. Silence reads as an oversight and
   gets re-litigated.
5. **Close by marking it done,** with `fixed_in:` naming the sha that pushed the fix. A register
   that cannot say what fixed something has stopped being evidence.

## The format

```yaml
---
title: One line, the finding, not the fix
status: open          # open | in-progress (name an owner) | blocked | done (needs fixed_in)
scope: M              # XS | S | M | L | ?
owner: null           # a handle, or null when unowned
filed: {today}     # when it was filed; it never changes
area: {area}
verify: probe         # test | probe | inspect (see rule 3)
blocked_by: null      # slug(s) of issues that must close first
fixed_in: null        # the sha on the mainline; required once status is done
needs: [N-1]          # the prodc need ids this work serves
---
```

**`blocked_by`** names the work an issue waits on; `status: blocked` names a person who can
unblock it. The board computes what is ready from `blocked_by`.

**Naming:** `DD-MM-YYYY-short-kebab-summary.md`: the date it was filed, then a slug.

## Tooling

`prodc issue` reads and writes this folder. The CLI, the prodc MCP tools, and any pre-commit gate
use one module, so they apply the same rules. `docs/issues/config.toml` holds this folder's
specifics.

```bash
prodc issue board             # what is ready, and what the rest waits on
prodc issue check             # the rules; exit 1 on problems
prodc issue reindex           # regenerate the index below
prodc issue show <slug>
```

## Open now

{begin}
_No open follow-ups._
{end}
"""


def starter_config(areas: Iterable[str] = ()) -> str:
    """A config for a folder with nothing in it yet.

    `areas` is asked for rather than defaulted. It is the one vocabulary that cannot be guessed from
    outside a repo, and a folder that accepts any area silently accepts every typo as a new one.
    """
    names = tuple(areas)
    listed = (
        "areas = [" + ", ".join(f'"{a}"' for a in names) + "]"
        if names
        else '# areas = ["backend", "frontend", "ci"]   # REQUIRED: until set, any area is accepted'
    )
    return f"""\
# docs/issues/config.toml: what this folder's issues must say.
#
# Read by `prodc issue`: the CLI, the prodc MCP tools, and any pre-commit gate use one module,
# so they apply the same rules.

date_style = "DMY"          # 03-08-2026-short-kebab-summary.md
index = true                # the generated table in README.md
index_fields = ["scope", "verify"]

# The one vocabulary that cannot be guessed from outside this repo.
{listed}

[fields.scope]
required = true
values = ["XS", "S", "M", "L", "?"]

# How "done" gets checked. The distinction is load-bearing: a green test is not the same claim as a
# sensed fact, and an issue that blurs them sends the next person to the wrong evidence.
[fields.verify]
required = true
values = ["test", "probe", "inspect"]
"""


def scaffold(
    folder: pathlib.Path, areas: Iterable[str] = (), today: str | None = None
) -> list[pathlib.Path]:
    """Start a register in an empty folder: a config and a README with an index region.

    Writes only what is missing. A folder that already has a README keeps it: the marker can be
    pasted in by hand, and silently rewriting somebody's documentation to install a tool is not a
    trade anyone agreed to.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    config = folder / CONFIG_NAME
    if not config.exists():
        config.write_text(starter_config(areas))
        written.append(config)
    readme = folder / README_NAME
    if not readme.exists():
        names = tuple(areas)
        readme.write_text(
            STARTER_README.format(
                today=today or _dt.date.today().isoformat(),
                area=names[0] if names else "<one of the areas above>",
                begin=INDEX_BEGIN,
                end=INDEX_END,
            )
        )
        written.append(readme)
    return written


class _FieldSpec(TypedDict):
    count: int
    list: bool
    values: set[str | None]


def infer_config(folder: pathlib.Path) -> str:
    """The config.toml that makes this folder valid as it stands, as TOML text.

    Adoption has to be non-destructive or nobody adopts. Writing a config from first principles
    would declare 78 existing issues malformed on day one; reading it from what is actually there
    means `check` passes immediately, and tightening a field to `required` afterwards is a decision
    taken on purpose rather than a migration forced by a tool.
    """
    issues, _ = load_all(folder, DEFAULT_CONFIG)
    areas = sorted({i.area for i in issues})
    seen: dict[str, _FieldSpec] = {}
    for issue in issues:
        for key, value in issue.extra.items():
            spec = seen.setdefault(key, {"count": 0, "list": False, "values": set()})
            spec["count"] += 1
            if isinstance(value, tuple):
                spec["list"] = True
                spec["values"].update(value)
            else:
                spec["values"].add(value)

    style = "DMY"
    for issue in issues:
        if re.match(r"^\d{4}-\d{2}-\d{2}-", issue.path.name):
            style = "YMD"
            break

    # Only claim the index if the README actually has a region to write into. A folder that keeps
    # its own summary another way is not broken, and `check` demanding a marker nobody put there is
    # the tool inventing work on first contact.
    readme = folder / README_NAME
    has_region = readme.exists() and _has_region(readme.read_text())

    lines = [
        "# docs/issues/config.toml: what this folder's issues must say.",
        "#",
        "# Written by infer_config from the files that were already here, so `check`",
        "# passes today. Tighten it deliberately: flip a field to required, or pin its values.",
        "",
        f'date_style = "{style}"',
        f"index = {'true' if has_region else 'false'}"
        + (
            ""
            if has_region
            else "   # no generated-index region in README.md; add one, then flip this"
        ),
        "",
        "# The one vocabulary that cannot be guessed from outside this repo.",
        "areas = [" + ", ".join(f'"{a}"' for a in areas) + "]",
    ]
    for key, spec in sorted(seen.items(), key=lambda kv: -kv[1]["count"]):
        values: list[str] = sorted(str(v) for v in spec["values"] if v)
        # A field with few distinct values is an enum worth pinning; free text is not.
        enum_like = 0 < len(values) <= 8 and not spec["list"]
        lines += ["", f"[fields.{key}]"]
        lines.append(
            f"required = {'true' if spec['count'] == len(issues) else 'false'}"
            f"   # on {spec['count']}/{len(issues)} issues today"
        )
        if spec["list"]:
            lines.append("list = true")
        if enum_like:
            lines.append("values = [" + ", ".join(f'"{v}"' for v in values) + "]")
    return "\n".join(lines) + "\n"


def find_folder(start: pathlib.Path) -> pathlib.Path | None:
    """This project's register, searching upward from ``start``, or None when there is none.

    The search starts at ``start`` so a command run from a subdirectory finds the register.
    ``PRODC_ISSUES_DIR`` replaces the search when set (absolute, or relative to each level
    searched); ``CABILDO_ISSUES_DIR`` is read when it is not. An absolute path that is not a
    directory gives None.

    The search stops at the repo root (the first ``.git``). Taking a register from an enclosing
    repo would file this repo's work in another project's queue.
    """
    override = (
        os.environ.get("PRODC_ISSUES_DIR", "").strip()
        or os.environ.get("CABILDO_ISSUES_DIR", "").strip()
    )
    if override:
        direct = pathlib.Path(override).expanduser()
        if direct.is_absolute():
            return direct if direct.is_dir() else None
        candidates: tuple[tuple[str, ...], ...] = (tuple(direct.parts),)
    else:
        candidates = FOLDER_CANDIDATES

    here = start.resolve()
    for base in (here, *here.parents):
        for parts in candidates:
            found = base.joinpath(*parts)
            if found.is_dir():
                return found
        if (base / ".git").exists():
            break
    return None
