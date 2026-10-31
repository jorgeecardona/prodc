"""Write-back: let an agent record its decisions as need YAML, safely (#24).

The one dangerous thing prodc does is edit files, so every edit goes through one gate:
mutate a copy of the target file, write it, re-run :func:`~prodc.loader.load` as the schema,
and revert if the model no longer loads. An in-place edit splices only the changed need's block
back into the original text (#53), so the file header and every other need keep their comments
and formatting. Inside the edited need, only the keys whose value changed are re-dumped (#98);
an unrecognised shape falls back to a full PyYAML re-dump. One file per edit, always shown as a diff.
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from .config import Config

if TYPE_CHECKING:
    from .model import Source
from .loader import LoaderError, load, yaml_error_message

# Fields an agent may `set` on a need. Unknown keys are silently ignored by the loader, so the
# write path allowlists instead. A typo'd key is an error here, not junk written to disk.
_SCALAR_FIELDS = frozenset(
    {
        "text",
        "description",
        "who",
        "role",
        "must",
        "importance",
        "claim",
        "goal",
        "release",
        "expects",
        "variant_of",
        "client",
        "product",
        "draft",
    }
)
_LIST_FIELDS = frozenset({"proofs", "children", "contradicts", "tags"})

# Source-kind aliases accepted on write (old names → the primary/secondary/assumption ladder),
# normalised so new files use the current vocabulary even when an author types the old kind.
# Mirrors the loader's read-side aliases.
_SOURCE_KIND_ALIASES = {
    "interview": "primary",
    "artifact": "secondary",
    "proxy": "assumption",
    "internal": "assumption",
}
_SOURCE_KINDS = ("primary", "secondary", "assumption")


def _canonical_kind(kind: str) -> str:
    """Normalise a source kind (accepting old aliases) to its canonical ladder value."""
    k = _SOURCE_KIND_ALIASES.get(kind, kind)
    if k not in _SOURCE_KINDS:
        raise WriteError(f"source kind must be one of {', '.join(_SOURCE_KINDS)}, not {kind!r}")
    return k


class WriteError(Exception):
    pass


@dataclass(frozen=True)
class Edit:
    """A proposed single-file change: enough to show a diff and to commit or discard it."""

    path: Path
    old_text: str
    new_text: str

    @property
    def diff(self) -> str:
        rel = self.path.name
        return "".join(
            difflib.unified_diff(
                self.old_text.splitlines(keepends=True),
                self.new_text.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(doc: dict[str, object]) -> str:
    # sort_keys=False keeps authored key order; the file is still reflowed (comments lost).
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _need_block_span(lines: list[str], need_id: str) -> tuple[int, int, int] | None:
    """Line span [start, end) and item indent of the `needs:` item whose id is ``need_id``."""
    return _block_span(lines, "needs", need_id)


def _scan_list(lines: list[str], key: str) -> tuple[list[tuple[int, str | None]], int, int] | None:
    """Scan the top-level ``key:`` list; returns ``(item_starts, region_end, item_indent)`` or None.

    ``item_starts`` is ``(start_line, id)`` per list item, ``region_end`` is the line index just
    past the list (before trailing blanks/comments are trimmed), and ``item_indent`` is the ``- ``
    indent. Line-based and deliberately conservative: it understands the common prodc layout (a
    top-level list key (``needs:``, ``principles:``) whose items are ``- `` at a fixed indent, and
    returns None for anything it is not sure about, so the caller can fall back to a full re-dump.
    The single scanner behind both the edit splice (:func:`_block_span`) and the append (#85).
    """
    key_line = re.compile(rf"^{re.escape(key)}:\s*(#.*)?$")
    key_at = next((i for i, ln in enumerate(lines) if key_line.match(ln)), None)
    if key_at is None:
        return None
    item_re = None
    item_indent = -1
    i = key_at + 1
    starts: list[tuple[int, str | None]] = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^(\s*)-\s", line)
        if item_re is None:
            if m is None:
                return None  # first non-blank line under the key isn't a list item: unknown shape
            item_indent = len(m.group(1))
            item_re = re.compile(rf"^\s{{{item_indent}}}-\s")
        if indent < item_indent and m is None:
            break  # dedented past the list: end of the key's region
        if item_re.match(line):
            starts.append((i, _item_id(lines, i, item_indent)))
        elif indent <= item_indent and m is None:
            break
        i += 1
    return starts, i, item_indent


def _block_span(lines: list[str], key: str, item_id: str) -> tuple[int, int, int] | None:
    """Line span [start, end) and item indent of the top-level ``key:`` list item ``item_id``.

    Trailing blank and comment lines are left out of the span, so a comment that introduces the
    *next* item is never swallowed. None when the key is absent, the shape is unrecognised, or no
    item carries ``item_id``. The caller then falls back to a full re-dump.
    """
    scanned = _scan_list(lines, key)
    if scanned is None:
        return None
    starts, region_end, item_indent = scanned
    # close each span at the start of the next item (or `region_end`, the end of the list region)
    bounds = [s[0] for s in starts] + [region_end]
    for idx, (start, iid) in enumerate(starts):
        if iid != item_id:
            continue
        end = bounds[idx + 1]
        while end - 1 > start and (
            lines[end - 1].strip() == "" or lines[end - 1].strip().startswith("#")
        ):
            end -= 1
        return start, end, item_indent
    return None


def _item_id(lines: list[str], start: int, item_indent: int) -> str | None:
    """The id of the list item beginning at ``lines[start]`` (inline or on a child line)."""
    first = re.match(r"^\s*-\s+id:\s*(\S+)\s*$", lines[start])
    if first:
        return first.group(1).strip("\"'")
    key_re = re.compile(rf"^\s{{{item_indent + 2}}}id:\s*(\S+)\s*$")
    j = start + 1
    while j < len(lines):
        indent = len(lines[j]) - len(lines[j].lstrip(" "))
        if lines[j].strip() and indent <= item_indent:
            break
        km = key_re.match(lines[j])
        if km:
            return km.group(1).strip("\"'")
        j += 1
    return None


def _normalize_answer(doc: dict[str, object]) -> None:
    """Rewrite a need's ``answer`` back to its yes/no string before re-dump.

    YAML 1.1 reads a bare ``answer: no`` as the boolean ``False``, so the raw dict carries a
    bool; dumping it as-is would write ``answer: false``. Loads fine (the loader coerces it),
    but a reader sees ``false``, not the authored ``no``. Canonicalise here so the on-disk text
    stays the research vocabulary, the same spirit as ``_canonical_kind`` for source kinds.
    """
    needs = doc.get("needs")
    if not isinstance(needs, list):
        return
    for raw in cast("list[object]", needs):
        if isinstance(raw, dict):
            need = cast("dict[str, object]", raw)
            if isinstance(need.get("answer"), bool):
                need["answer"] = "yes" if need["answer"] else "no"


def _render_edit(old_text: str, doc: dict[str, object], need_id: str) -> str:
    """Re-render after an in-place edit, splicing only the changed need to keep comments (#53).

    Dumps just the edited need's block and replaces its span in the original text, so the file
    header and every other need stay byte-for-byte. Falls back to a full re-dump (the old
    behaviour) when the file's shape is anything the splice isn't sure of. The reload gate in
    :func:`_validated` guards correctness either way.
    """
    _normalize_answer(doc)
    return _render_item_edit(old_text, doc, "needs", need_id)


def _render_item_edit(old_text: str, doc: dict[str, object], key: str, item_id: str) -> str:
    """Splice the edited ``key:`` list item ``item_id`` back into ``old_text``, comments intact.

    The general form of :func:`_render_edit` (which adds the needs-only ``answer``
    normalisation): any top-level list noun (``needs:``, ``principles:``) is spliced the same way,
    with the same full re-dump fallback when the shape is not one the splice is sure of.
    """
    lines = old_text.splitlines(keepends=True)
    span = _block_span(lines, key, item_id)
    items = doc.get(key)
    if span is None or not isinstance(items, list):
        return _dump(doc)
    start, end, indent = span
    item = next(
        (
            cast("dict[str, object]", n)
            for n in cast("list[object]", items)
            if isinstance(n, dict) and cast("dict[str, object]", n).get("id") == item_id
        ),
        None,
    )
    if item is None:
        return _dump(doc)
    block = _splice_item_keys(lines[start:end], item, indent)
    if block is None:
        dumped = yaml.safe_dump(
            [item], sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        pad = " " * indent
        block = "".join(pad + ln if ln.strip() else ln for ln in dumped.splitlines(keepends=True))
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _indented_dump(value: object, indent: int) -> list[str]:
    """``value`` dumped as block YAML, every non-blank line shifted right by ``indent``."""
    dumped = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, default_flow_style=False)
    pad = " " * indent
    return [pad + ln if ln.strip() else ln for ln in dumped.splitlines(keepends=True)]


def _splice_item_keys(block: list[str], new_item: dict[str, object], indent: int) -> str | None:
    """Re-render one list item key by key, keeping every unchanged key's original text (#98).

    A key whose value did not change keeps its lines byte-for-byte: quoting, folded ``>``
    blocks, list indentation and comments. A changed key is re-dumped alone; a list that only
    grew at the end (a captured source, an added proof) keeps its old items and gets the new
    ones appended at the old item indent. Keys removed from the item are dropped, new keys go
    at the end. Returns None when the block is not the plain ``- key: ...`` shape, so the
    caller falls back to dumping the whole item.
    """
    try:
        parsed = yaml.safe_load("".join(block))
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, list) or len(cast("list[object]", parsed)) != 1:
        return None
    first = cast("list[object]", parsed)[0]
    if not isinstance(first, dict):
        return None
    old_item = cast("dict[str, object]", first)
    _normalize_answer({"needs": [old_item]})
    key_indent = indent + 2
    head = re.match(rf"^ {{{indent}}}- ([A-Za-z_][\w-]*):(\s|$)", block[0])
    key_re = re.compile(rf"^ {{{key_indent}}}([A-Za-z_][\w-]*):(\s|$)")
    if head is None:
        return None
    # (key, lines) per top-level key of the item; the first key sits on the `- ` line
    segments: list[tuple[str, list[str]]] = [(head.group(1), [block[0]])]
    for line in block[1:]:
        m = key_re.match(line)
        if m:
            segments.append((m.group(1), [line]))
        else:
            segments[-1][1].append(line)
    if [k for k, _ in segments] != list(old_item):
        return None
    out: list[str] = []
    for key, seg in segments:
        if key not in new_item:
            continue
        old, new = old_item[key], new_item[key]
        if old == new:
            out.extend(seg)
            continue
        body, tail = seg, cast("list[str]", [])
        while len(body) > 1 and (body[-1].strip() == "" or body[-1].strip().startswith("#")):
            body, tail = body[:-1], [body[-1], *tail]
        out.extend(_render_changed_key(key, old, new, body, key_indent))
        out.extend(tail)
    for key, value in new_item.items():
        if key not in old_item:
            out.extend(_indented_dump({key: value}, key_indent))
    if not out:
        return None
    if out[0].startswith(" " * key_indent) and not out[0].startswith(" " * indent + "- "):
        out[0] = " " * indent + "- " + out[0][key_indent:]
    for i, line in enumerate(out[:-1]):
        if not line.endswith("\n"):
            out[i] = line + "\n"
    return "".join(out)


def _render_changed_key(
    key: str, old: object, new: object, body: list[str], key_indent: int
) -> list[str]:
    """The lines for one changed key: old items kept when a list only grew at the end."""
    if isinstance(old, list) and isinstance(new, list):
        old_l, new_l = cast("list[object]", old), cast("list[object]", new)
        grown: object = new_l[len(old_l) :]
        dash = next((re.match(r"^(\s*)- ", ln) for ln in body[1:] if re.match(r"^\s*- ", ln)), None)
        if old_l and len(new_l) > len(old_l) and new_l[: len(old_l)] == old_l and dash:
            kept = [ln if ln.endswith("\n") else ln + "\n" for ln in body]
            return kept + _indented_dump(grown, len(dash.group(1)))
    single: dict[str, object] = {key: new}
    return _indented_dump(single, key_indent)


def _render_item_append(old_text: str, doc: dict[str, object], key: str, item_id: str) -> str:
    """Append the new ``key:`` list item ``item_id`` to ``old_text``, every comment intact (#85).

    The insert mirror of :func:`_render_item_edit`: dump only the new item and splice it in after
    the last existing item of the list, so the header, the other items, and their comments stay
    byte-for-byte. Falls back to a full re-dump when the file has no recognised ``key:`` list to
    append to (a brand-new file or key, where there are no in-list comments to lose); the reload
    gate in :func:`_validated` guards correctness either way.
    """
    lines = old_text.splitlines(keepends=True)
    scanned = _scan_list(lines, key)
    items = doc.get(key)
    if scanned is None or not isinstance(items, list):
        return _dump(doc)
    starts, region_end, item_indent = scanned
    if not starts:  # the key exists but holds no recognised item: re-dump rather than guess indent
        return _dump(doc)
    item = next(
        (
            cast("dict[str, object]", n)
            for n in cast("list[object]", items)
            if isinstance(n, dict) and cast("dict[str, object]", n).get("id") == item_id
        ),
        None,
    )
    if item is None:
        return _dump(doc)
    # insert after the last item's content, before any trailing blank/comment lines of the section
    insert_at = region_end
    first_start = starts[0][0]
    while insert_at - 1 >= first_start and (
        lines[insert_at - 1].strip() == "" or lines[insert_at - 1].strip().startswith("#")
    ):
        insert_at -= 1
    dumped = yaml.safe_dump([item], sort_keys=False, allow_unicode=True, default_flow_style=False)
    pad = " " * item_indent
    block = "".join(pad + ln if ln.strip() else ln for ln in dumped.splitlines(keepends=True))
    if insert_at > 0 and not lines[insert_at - 1].endswith("\n"):
        block = "\n" + block  # the item before the insert point had no trailing newline
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def _render_delete(old_text: str, doc: dict[str, object], need_id: str) -> str:
    """Re-render after removing a need, excising only its block to keep every other comment (#60).

    The mirror of :func:`_render_edit`: find the need's span and drop it from the original text,
    so the file header and the surrounding needs stay byte-for-byte. Falls back to a full re-dump
    of ``doc`` (with the need already removed) when the file's shape is anything the splice isn't
    sure of; the reload gate in :func:`_validated` guards correctness either way.
    """
    lines = old_text.splitlines(keepends=True)
    span = _need_block_span(lines, need_id)
    if span is None:
        return _dump(doc)
    start, end = span[0], span[1]
    return "".join(lines[:start]) + "".join(lines[end:])


def _read_doc(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WriteError(yaml_error_message(path.name, text, exc)) from exc
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise WriteError(f"{path.name}: top level is not a mapping")
    return cast("dict[str, object]", doc), text


def _need_list(doc: dict[str, object], path: Path) -> list[object]:
    raw = doc.setdefault("needs", [])
    if not isinstance(raw, list):
        raise WriteError(f"{path.name}: 'needs' is not a list")
    return cast("list[object]", raw)


def _proof_list(need: dict[str, object], path: Path) -> list[object]:
    """A fresh copy of a need's ``proofs`` list, erroring if the field is present but not a list."""
    current = need.get("proofs", [])
    if not isinstance(current, list):
        raise WriteError(f"{path.name}: 'proofs' is not a list")
    return list(cast("list[object]", current))


def _locate(config: Config, need_id: str) -> tuple[Path, dict[str, object]]:
    """Find the file and the raw need mapping for ``need_id``."""
    for path in config.prodc_files():
        doc, _ = _read_doc(path)
        for raw in _need_list(doc, path):
            if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
                return path, cast("dict[str, object]", raw)
    raise WriteError(f"no need {need_id!r} in any prodc file")


def _coerce(value: str) -> object:
    """Read a CLI value as a YAML scalar, so `must=true`→bool and `importance=2`→int."""
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def _child_item(raw: str) -> object:
    """Parse a ``children+=`` value into a flow edge: ``id`` stays a bare string, ``id@step`` a map.

    Mirrors the loader's dual shape (#90): ``children+=US-050`` appends the bare id (unstepped),
    ``children+=US-052@execute`` appends ``{id: US-052, step: execute}``. A bare id keeps the file's
    existing plain-string style; the ``@`` suffix mirrors the ``need:A@yes`` proof-locator idiom.
    """
    head, sep, step = raw.partition("@")
    if not sep:
        return raw
    return {"id": head.strip(), "step": step.strip()}


def _apply_assignment(need: dict[str, object], assignment: str, path: Path) -> None:
    if "+=" in assignment:
        key, _, raw = assignment.partition("+=")
        key = key.strip()
        if key not in _LIST_FIELDS:
            raise WriteError(
                f"cannot append to {key!r} (list fields: {', '.join(sorted(_LIST_FIELDS))})"
            )
        current = need.get(key, [])
        if not isinstance(current, list):
            raise WriteError(f"{path.name}: {key!r} is not a list")
        items = cast("list[object]", current)
        items.append(_child_item(raw.strip()) if key == "children" else raw.strip())
        need[key] = items
        return
    key, sep, raw = assignment.partition("=")
    key = key.strip()
    if not sep:
        raise WriteError(f"expected key=value or key+=value, got {assignment!r}")
    if key not in _SCALAR_FIELDS:
        raise WriteError(f"cannot set {key!r} (fields: {', '.join(sorted(_SCALAR_FIELDS))})")
    need[key] = _coerce(raw.strip())


def _guard_target(config: Config, path: Path) -> None:
    """Refuse to write outside the configured globs or through a symlink."""
    if path.is_symlink():
        raise WriteError(f"{path.name} is a symlink; refusing to write through it")
    try:
        rel = path.resolve().relative_to(config.root.resolve())
    except ValueError:
        raise WriteError(f"{path} is outside the project root") from None
    if not any(rel.match(pattern) for pattern in config.need_globs):
        raise WriteError(f"{path.name} does not match any [prodc].files glob")


def _validated(config: Config, path: Path, old_text: str, new_text: str, dry_run: bool) -> Edit:
    """Write ``new_text``, re-load the model as the schema, and revert on failure or dry-run.

    Reverting restores the prior state exactly: a file that did not exist before (a first `add`
    into a new file) is removed again rather than left as an empty file, so a rejected or
    dry-run write leaves the tree untouched.
    """
    _guard_target(config, path)
    existed = path.exists()

    def _restore() -> None:
        if existed:
            path.write_text(old_text, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)

    path.write_text(new_text, encoding="utf-8")
    try:
        load(config)
    except BaseException as exc:  # revert on ANY failure, then re-raise
        _restore()
        if isinstance(exc, LoaderError):
            raise WriteError(f"edit rejected: {exc}") from exc
        raise
    if dry_run:
        _restore()
    return Edit(path=path, old_text=old_text, new_text=new_text)


def _edit_one_need(
    config: Config,
    need_id: str,
    *,
    expect_sha: str | None,
    dry_run: bool,
    mutate: Callable[[dict[str, object], Path], None],
) -> Edit:
    """Run ``mutate`` on one existing need's raw mapping, comment-safe and reload-gated (#82).

    The shared skeleton of every single-need writer: locate the file → read it → check the
    optimistic lock → find the need by id → apply ``mutate`` (the only part that differs) → splice
    just that need's block back (#53) → re-load as the schema and revert on failure (:func:`_validated`).
    ``mutate`` receives the need's mapping and the file path (for field-level errors) and edits the
    mapping in place; raising :class:`WriteError` from it aborts before anything is written.
    """
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            mutate(cast("dict[str, object]", raw), path)
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def set_field(
    config: Config, need_id: str, assignment: str, *, expect_sha: str | None, dry_run: bool
) -> Edit:
    """Set or list-append one field on an existing need, validated against the loader."""
    return _edit_one_need(
        config,
        need_id,
        expect_sha=expect_sha,
        dry_run=dry_run,
        mutate=lambda need, path: _apply_assignment(need, assignment, path),
    )


def set_importance(
    config: Config, need_id: str, level: int, when: str, *, expect_sha: str | None, dry_run: bool
) -> Edit:
    """Set a need's importance and record ``importance_set_at`` in one edit (#59).

    The level is already resolved against the rubric by the caller; this just writes both fields
    together so ranking never refines on a number nobody has revisited.
    """

    def _mutate(need: dict[str, object], _path: Path) -> None:
        need["importance"] = level
        need["importance_set_at"] = when

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def capture_source(
    config: Config,
    need_id: str,
    *,
    kind: str,
    who: str | None,
    role: str | None = None,
    date: str | None,
    quote: str | None,
    locator: str | None,
    observed_at: str | None = None,
    anchor: str | None = None,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Append a Source to an existing need: the near-zero-friction capture of #24.

    Records evidence as given; the loader's soft hygiene checks (a primary source wants a who and a
    quote-or-locator, a secondary source wants a locator) still apply on the next read.
    ``observed_at`` dates when the evidence was recorded, so the board can flag stale needs (#58).
    ``anchor`` points at an exact place inside ``locator`` (#57).
    ``role`` records which declared role the ``who`` spoke as (validated against ``roles:`` on the
    next load): whose signal it is, orthogonal to the evidence tier (#52 follow-up).
    """
    kind = _canonical_kind(kind)
    source: dict[str, object] = {"kind": kind}
    for key, value in (
        ("who", who),
        ("role", role),
        ("date", date),
        ("quote", quote),
        ("locator", locator),
        ("anchor", anchor),
        ("observed_at", observed_at),
    ):
        if value is not None:
            source[key] = value

    def _mutate(need: dict[str, object], path: Path) -> None:
        current = need.get("sources", [])
        if not isinstance(current, list):
            raise WriteError(f"{path.name}: 'sources' is not a list")
        sources = cast("list[object]", current)
        sources.append(source)
        need["sources"] = sources

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def attest(
    config: Config,
    need_id: str,
    *,
    who: str,
    date: str,
    kind: str,
    verdict: str | None,
    comment: str | None,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Record a human or AI review that a need's proofs establish its claim (#13).

    ``who`` is a person's name or a model id; ``kind`` is ``human`` or ``ai``. The verdict and
    comment are kept on the need as the review's register. Replaces any existing attestation.
    """
    if kind not in ("human", "ai"):
        raise WriteError(f"attestation kind must be human or ai, not {kind!r}")
    att: dict[str, object] = {"who": who, "date": date, "kind": kind}
    if verdict is not None:
        att["verdict"] = verdict
    if comment is not None:
        att["comment"] = comment
    return _edit_one_need(
        config,
        need_id,
        expect_sha=expect_sha,
        dry_run=dry_run,
        mutate=lambda need, _path: need.__setitem__("attestation", att),
    )


def record_outcome(
    config: Config,
    need_id: str,
    *,
    landed: bool,
    who: str,
    date: str,
    evidence: str | None,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Record whether a delivered need moved its goal (#97). Replaces any earlier outcome."""
    outcome: dict[str, object] = {"landed": landed, "date": date, "who": who}
    if evidence is not None:
        outcome["evidence"] = evidence
    return _edit_one_need(
        config,
        need_id,
        expect_sha=expect_sha,
        dry_run=dry_run,
        mutate=lambda need, _path: need.__setitem__("outcome", outcome),
    )


def withdraw(
    config: Config,
    need_id: str,
    *,
    reason: str,
    date: str,
    kind: str = "wont_do",
    principle: str | None = None,
    of: str | None = None,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Record a decision against a need: withdrawn / won't-do (#74).

    Writes a ``withdrawn: {reason, date, kind?, principle?}`` mapping onto the need, which takes it off
    the active board and out of coverage; the record stays as its durable trace. ``kind`` says
    *why* (``wont_do`` default, ``out_of_scope``, ``duplicate``) and is written only when it is not
    the default, to keep the common case clean. ``principle`` names the Principle the decision rests on
    (the reload gate rejects an unknown id), so revising that principle later flags this decision for
    re-review. Replaces any existing withdrawal (re-withdrawing updates it). Reinstate with
    :func:`reinstate`.
    """
    mark: dict[str, object] = {"reason": reason, "date": date}
    if kind != "wont_do":
        mark["kind"] = kind
    if principle is not None:
        mark["principle"] = principle
    if of is not None:
        mark["of"] = of
    return _edit_one_need(
        config,
        need_id,
        expect_sha=expect_sha,
        dry_run=dry_run,
        mutate=lambda need, _path: need.__setitem__("withdrawn", mark),
    )


def reinstate(config: Config, need_id: str, *, expect_sha: str | None, dry_run: bool) -> Edit:
    """Remove a need's ``withdrawn`` mark, putting it back on the active board (#74).

    Errors if the need is not currently withdrawn. Reinstating a live need is a mistake worth
    surfacing, not a silent no-op.
    """

    def _mutate(need: dict[str, object], _path: Path) -> None:
        if "withdrawn" not in need:
            raise WriteError(f"need {need_id!r} is not withdrawn")
        del need["withdrawn"]

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def _locate_decision(config: Config, decision_id: str) -> tuple[Path, dict[str, object], str]:
    """The file holding ``decision_id``, its parsed doc, and its raw text."""
    for path in config.prodc_files():
        doc, text = _read_doc(path)
        raw = doc.get("decisions")
        if not isinstance(raw, list):
            continue
        for d in cast("list[object]", raw):
            if isinstance(d, dict) and cast("dict[str, object]", d).get("id") == decision_id:
                return path, doc, text
    raise WriteError(f"no decision {decision_id!r} in any prodc file")


def _edit_one_decision(
    config: Config,
    decision_id: str,
    *,
    expect_sha: str | None,
    dry_run: bool,
    mutate: Callable[[dict[str, object]], None],
) -> Edit:
    """The decision counterpart of :func:`_edit_one_need`: locate, lock-check, mutate, splice.

    Comment-safe: only the decision's own block is spliced back, and the reload gate validates it.
    """
    path, doc, old_text = _locate_decision(config, decision_id)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in cast("list[object]", doc["decisions"]):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == decision_id:
            mutate(cast("dict[str, object]", raw))
            break
    new_text = _render_item_edit(old_text, doc, "decisions", decision_id)
    return _validated(config, path, old_text, new_text, dry_run)


def withdraw_decision(
    config: Config,
    decision_id: str,
    *,
    reason: str,
    date: str,
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Supersede/retire a decision: write a ``withdrawn: {reason, date}`` mark onto it.

    The decision's lifecycle reuses the Need verbs (no status enum): this is how a superseded
    decision leaves the in-force set while its record stays (e.g. ``--reason "superseded by D-7"``).
    Reinstate with :func:`reinstate_decision`.
    """

    def _mutate(d: dict[str, object]) -> None:
        d["withdrawn"] = {"reason": reason, "date": date}

    return _edit_one_decision(
        config, decision_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate
    )


def reinstate_decision(
    config: Config, decision_id: str, *, expect_sha: str | None = None, dry_run: bool
) -> Edit:
    """Remove a decision's ``withdrawn`` mark, putting it back in force. Errors if not withdrawn."""

    def _mutate(d: dict[str, object]) -> None:
        if "withdrawn" not in d:
            raise WriteError(f"decision {decision_id!r} is not withdrawn")
        del d["withdrawn"]

    return _edit_one_decision(
        config, decision_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate
    )


def set_decision_awaits(
    config: Config, decision_id: str, assignment: str, *, expect_sha: str | None, dry_run: bool
) -> Edit:
    """``awaits+=REF`` adds the research a decision waits on; ``awaits-=REF`` drops it (#93).

    ``REF`` is ``<need-id>`` or ``<need-id>@yes|no|inconclusive``; the reload gate checks it
    names a known need, a valid direction, and not a need the decision already serves. Dropping
    the last entry removes the key, so a decision that waits on nothing reads as before.
    """
    for op in ("+=", "-="):
        key, sep, raw = assignment.partition(op)
        if sep:
            break
    else:
        raise WriteError(f"expected awaits+=REF or awaits-=REF, got {assignment!r}")
    if key.strip() != "awaits":
        raise WriteError(f"a decision only supports awaits+= / awaits-= here, got {key.strip()!r}")
    ref = raw.strip()

    def _mutate(d: dict[str, object]) -> None:
        current = d.get("awaits", [])
        if not isinstance(current, list):
            raise WriteError(f"decision {decision_id!r}: 'awaits' is not a list")
        items = [str(x) for x in cast("list[object]", current)]
        if op == "+=":
            if ref in items:
                raise WriteError(f"decision {decision_id!r} already awaits {ref!r}")
            items.append(ref)
        else:
            if ref not in items:
                raise WriteError(f"decision {decision_id!r} does not await {ref!r}")
            items.remove(ref)
        if items:
            d["awaits"] = items
        else:
            d.pop("awaits", None)

    return _edit_one_decision(
        config, decision_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate
    )


def delete_need(
    config: Config, need_id: str, *, expect_sha: str | None = None, dry_run: bool
) -> Edit:
    """Remove a need from its file entirely: the hard-delete write path (#60).

    Unlike :func:`withdraw` (which keeps the need as a dated decision-against record), this erases
    it. The reload gate makes it referentially safe: a need still pointed at by another's
    ``children``/``variant_of`` or a ``need:`` proof fails to load after the excision, so the write
    is reverted and refused rather than leaving a dangling reference. Comment-safe (the #53 splice,
    reversed): only the deleted need's block leaves the file.
    """
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    needs = _need_list(doc, path)
    kept: list[object] = [
        raw
        for raw in needs
        if not (isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id)
    ]
    doc["needs"] = kept
    return _validated(config, path, old_text, _render_delete(old_text, doc, need_id), dry_run)


def accept(
    config: Config,
    need_id: str,
    *,
    who: str,
    date: str,
    revoke: bool,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Record (or revoke) a human acceptance pass as an ``accept:<who>@<date>`` proof (#46).

    Some needs are proven by a person looking, not a test. This makes recording that a
    one-liner instead of a hand edit. Idempotent: re-accepting the same who/date is a no-op.
    """
    locator = f"accept:{who}@{date}"

    def _mutate(need: dict[str, object], path: Path) -> None:
        proofs = _proof_list(need, path)
        if revoke:
            need["proofs"] = [p for p in proofs if p != locator]
        else:
            if locator not in proofs:
                proofs.append(locator)
            need["proofs"] = proofs

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def add_proof(
    config: Config, need_id: str, locator: str, *, expect_sha: str | None = None, dry_run: bool
) -> Edit:
    """Append a proof locator to an existing need, idempotently: the write path for ``suggest --apply``.

    A thin single-field edit (same splice as :func:`set_field` `proofs+=`), factored out so the
    batch apply can call it per need and show each need's diff. Re-adding a locator already on the
    need is a no-op, so applying the same suggestion twice does not duplicate it (#54).
    """

    def _mutate(need: dict[str, object], path: Path) -> None:
        proofs = _proof_list(need, path)
        if locator not in proofs:
            proofs.append(locator)
        need["proofs"] = proofs

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def relink_proof(
    config: Config,
    need_id: str,
    old_locator: str,
    new_locator: str,
    *,
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Replace one (broken) proof locator with a proposed one, in place: the relink of #54.

    The write path for ``suggest --relink --apply``: a renamed test keeps its adapter kind but
    gets a new id, so this swaps ``old_locator`` for ``new_locator`` on the need and de-duplicates
    (if the replacement already sits on the need, the broken one is simply dropped). Errors if the
    old locator is not actually on the need. One reload-gated single-file splice, like
    :func:`add_proof`.
    """

    def _mutate(need: dict[str, object], path: Path) -> None:
        proofs = _proof_list(need, path)
        if old_locator not in proofs:
            raise WriteError(f"{old_locator!r} is not a proof on {need_id!r}")
        swapped = [new_locator if p == old_locator else p for p in proofs]
        deduped: list[object] = []
        for p in swapped:
            if p not in deduped:
                deduped.append(p)
        need["proofs"] = deduped

    return _edit_one_need(config, need_id, expect_sha=expect_sha, dry_run=dry_run, mutate=_mutate)


def add_need(
    config: Config,
    need_id: str,
    text: str,
    *,
    who: str,
    kind: str,
    file: str,
    draft: bool = False,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Create a new need in ``file`` with an agent-provenance source (never a silent opinion).

    An agent-authored need must carry a source, and never ``primary``, which only a real user
    signal earns. ``kind`` is restricted to ``assumption`` (the agent's own guess) or ``secondary``
    (citing an existing document). A ``draft`` need is staged: it loads but is kept off the counted
    board until promoted (#60). The need is appended with the comment-preserving splice (#85), so
    existing needs and their comments stay byte-for-byte; a brand-new file is dumped fresh.
    """
    kind = _SOURCE_KIND_ALIASES.get(kind, kind)
    if kind not in ("assumption", "secondary"):
        raise WriteError(
            f"agent-authored need source must be assumption or secondary, not {kind!r} "
            "(never primary: that is earned by a real user signal)"
        )
    target = config.root / file
    if target.exists():
        doc, old_text = _read_doc(target)
    else:
        doc, old_text = {}, ""
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{target.name} changed since it was read (optimistic lock)")
    needs = _need_list(doc, target)
    if any(
        isinstance(n, dict) and cast("dict[str, object]", n).get("id") == need_id for n in needs
    ):
        raise WriteError(f"need {need_id!r} already exists in {target.name}")
    today = datetime.date.today().isoformat()
    new_need: dict[str, object] = {
        "id": need_id,
        "text": text,
        "sources": [{"kind": kind, "who": who, "date": today}],
    }
    if draft:
        new_need["draft"] = True
        new_need["draft_added"] = today  # stamped so a lint age-gate can fire later (#60)
    needs.append(new_need)
    new_text = _render_item_append(old_text, doc, "needs", need_id)
    return _validated(config, target, old_text, new_text, dry_run)


def add_role(
    config: Config,
    role_id: str,
    text: str,
    *,
    file: str,
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Declare a new Role in ``file``'s top-level ``roles:`` list (#52 follow-up).

    The dedicated write-back for a role, so a roster entry is a one-liner instead of a hand
    edit. Like :func:`add_need`, the new role is appended with the comment-preserving splice (#85),
    so an existing file's comments stay byte-for-byte and only a brand-new file is dumped fresh;
    the reload gate still rejects anything that does not load. A duplicate role id is refused.
    """
    target = config.root / file
    if target.exists():
        doc, old_text = _read_doc(target)
    else:
        doc, old_text = {}, ""
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{target.name} changed since it was read (optimistic lock)")
    raw = doc.setdefault("roles", [])
    if not isinstance(raw, list):
        raise WriteError(f"{target.name}: 'roles' is not a list")
    roles = cast("list[object]", raw)
    if any(
        isinstance(r, dict) and cast("dict[str, object]", r).get("id") == role_id for r in roles
    ):
        raise WriteError(f"role {role_id!r} already exists in {target.name}")
    roles.append({"id": role_id, "text": text})
    new_text = _render_item_append(old_text, doc, "roles", role_id)
    return _validated(config, target, old_text, new_text, dry_run)


def _source_dict(s: Source) -> dict[str, object]:
    """Serialise a :class:`~prodc.model.Source` back to a YAML mapping, dropping empty fields."""
    out: dict[str, object] = {"kind": s.kind.value}
    for key, value in (
        ("who", s.who),
        ("role", s.role),
        ("date", s.date),
        ("quote", s.quote),
        ("locator", s.locator),
        ("anchor", s.anchor),
        ("observed_at", s.observed_at),
    ):
        if value is not None:
            out[key] = value
    return out


def add_principle(
    config: Config,
    principle_id: str,
    text: str,
    *,
    file: str,
    revised_at: str,
    scope: str = "product",
    implemented_in: str | None = None,
    proofs: tuple[str, ...] = (),
    sources: tuple[Source, ...] = (),
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Declare a new Principle in ``file``'s top-level ``principles:`` list, stamped ``revised_at``.

    Mirrors :func:`add_role`: the new principle is appended with the comment-preserving splice (#85),
    the reload gate rejects anything that does not load (including an id already declared in another
    file), and a duplicate id in this file is refused. ``revised_at`` is stamped at creation so the first
    revision has something to ripple against. ``sources`` carry the provenance that surfaced the
    principle. The signals (often a client) a ``--from-need`` promotion copies across, so the
    discovery history stays honest: the principle was discovered, not decreed.
    """
    target = config.root / file
    if target.exists():
        doc, old_text = _read_doc(target)
    else:
        doc, old_text = {}, ""
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{target.name} changed since it was read (optimistic lock)")
    raw = doc.setdefault("principles", [])
    if not isinstance(raw, list):
        raise WriteError(f"{target.name}: 'principles' is not a list")
    principles = cast("list[object]", raw)
    if any(
        isinstance(a, dict) and cast("dict[str, object]", a).get("id") == principle_id
        for a in principles
    ):
        raise WriteError(f"principle {principle_id!r} already exists in {target.name}")
    entry: dict[str, object] = {"id": principle_id, "text": text}
    if scope != "product":
        entry["scope"] = scope  # written only when non-default, to keep the common case clean
    entry["revised_at"] = revised_at
    if implemented_in is not None:
        entry["implemented_in"] = implemented_in
    if proofs:
        entry["proofs"] = list(proofs)
    if sources:
        entry["sources"] = [_source_dict(s) for s in sources]
    principles.append(entry)
    new_text = _render_item_append(old_text, doc, "principles", principle_id)
    return _validated(config, target, old_text, new_text, dry_run)


def _locate_principle(config: Config, principle_id: str) -> tuple[Path, dict[str, object], str]:
    """The file holding ``principle_id``, its parsed doc, and its raw text."""
    for path in config.prodc_files():
        doc, text = _read_doc(path)
        raw = doc.get("principles")
        if not isinstance(raw, list):
            continue
        for a in cast("list[object]", raw):
            if isinstance(a, dict) and cast("dict[str, object]", a).get("id") == principle_id:
                return path, doc, text
    raise WriteError(f"no principle {principle_id!r} in any prodc file")


def revise_principle(
    config: Config,
    principle_id: str,
    *,
    text: str | None,
    revised_at: str,
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Revise a principle in place: optionally new ``text``, always a new ``revised_at``.

    Stamping ``revised_at`` is the point. It is what makes the ripple fire: every need withdrawn
    citing this principle with an earlier date comes back up for re-review. Comment-safe: only the
    principle's own block is spliced (:func:`_render_item_edit`), the rest of the file is untouched.
    """
    path, doc, old_text = _locate_principle(config, principle_id)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in cast("list[object]", doc["principles"]):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == principle_id:
            principle = cast("dict[str, object]", raw)
            if text is not None:
                principle["text"] = text
            principle["revised_at"] = revised_at
            break
    new_text = _render_item_edit(old_text, doc, "principles", principle_id)
    return _validated(config, path, old_text, new_text, dry_run)


def add_decision(
    config: Config,
    decision_id: str,
    text: str,
    *,
    file: str,
    needs: tuple[str, ...],
    decided_at: str,
    alternatives: tuple[str, ...] = (),
    consequences: str | None = None,
    principles: tuple[str, ...] = (),
    draft: bool = False,
    expect_sha: str | None = None,
    dry_run: bool,
) -> Edit:
    """Declare a new Decision (the solution chosen for ``needs``) in ``file``'s ``decisions:`` list.

    Mirrors :func:`add_principle` (comment-preserving append #85, reload-gated, duplicate id refused). ``needs``
    is required. The loader rejects a decision that serves none, and the reload gate rejects an id
    that is not a known need. Empty optional lists are omitted so the written block stays clean.
    """
    target = config.root / file
    if target.exists():
        doc, old_text = _read_doc(target)
    else:
        doc, old_text = {}, ""
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{target.name} changed since it was read (optimistic lock)")
    raw = doc.setdefault("decisions", [])
    if not isinstance(raw, list):
        raise WriteError(f"{target.name}: 'decisions' is not a list")
    decisions = cast("list[object]", raw)
    if any(
        isinstance(d, dict) and cast("dict[str, object]", d).get("id") == decision_id
        for d in decisions
    ):
        raise WriteError(f"decision {decision_id!r} already exists in {target.name}")
    entry: dict[str, object] = {"id": decision_id, "text": text, "needs": list(needs)}
    if alternatives:
        entry["alternatives"] = list(alternatives)
    if consequences is not None:
        entry["consequences"] = consequences
    if principles:
        entry["principles"] = list(principles)
    entry["decided_at"] = decided_at
    if draft:
        entry["draft"] = True
    decisions.append(entry)
    new_text = _render_item_append(old_text, doc, "decisions", decision_id)
    return _validated(config, target, old_text, new_text, dry_run)


def _snapshot(paths: list[Path]) -> dict[Path, str | None]:
    """Current text of each path, or None when it does not exist: a point to roll back to."""
    return {p: (p.read_text(encoding="utf-8") if p.exists() else None) for p in paths}


def _restore(snapshot: dict[Path, str | None]) -> None:
    """Put every file back exactly as :func:`_snapshot` found it (absent files removed again)."""
    for path, text in snapshot.items():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")


def _write_baseline(config: Config, need_id: str, text: str, file: str) -> Edit:
    """Write a new client-less baseline need {id, text} into ``file`` (no reload/commit gate).

    Unlike :func:`add_need`, it attaches no source. A recurrence baseline is a structural roll-up
    the author evidences later, so it loads flagged as an opinion rather than carrying a fabricated
    one. Raw write (the caller's transaction validates the whole model once and rolls back on any
    failure); still refuses a target outside the globs or a duplicate id.
    """
    _guard_target(config, config.root / file)
    target = config.root / file
    doc, old_text = _read_doc(target) if target.exists() else ({}, "")
    needs = _need_list(doc, target)
    if any(
        isinstance(n, dict) and cast("dict[str, object]", n).get("id") == need_id for n in needs
    ):
        raise WriteError(f"baseline id {need_id!r} already exists in {target.name}")
    needs.append({"id": need_id, "text": text})
    new_text = _dump(doc)
    target.write_text(new_text, encoding="utf-8")
    return Edit(path=target, old_text=old_text, new_text=new_text)


def link_variant_group(
    config: Config,
    *,
    member_ids: list[str],
    baseline_id: str,
    create_baseline: bool,
    baseline_text: str | None = None,
    baseline_file: str | None = None,
    dry_run: bool,
) -> list[Edit]:
    """Point a recurrence group at one shared baseline, atomically across files (#56).

    When ``create_baseline``, a new client-less need (``baseline_id``, ``baseline_text``) is written
    into ``baseline_file`` first so the members' ``variant_of`` resolves; otherwise ``baseline_id``
    is an existing client-less member reused in place. Every id in ``member_ids`` then gets
    ``variant_of=baseline_id`` (a comment-preserving per-need splice). All touched files are
    snapshotted up front; any rejection (or ``dry_run``) restores every one, so the group is
    linked all-or-nothing.
    """
    touched = config.prodc_files()
    if create_baseline:
        if not baseline_file or baseline_text is None:
            raise WriteError("creating a baseline needs both a file and text")
        touched = [*touched, config.root / baseline_file]
    snapshot = _snapshot(sorted(set(touched)))
    edits: list[Edit] = []
    try:
        if create_baseline:
            assert baseline_file is not None and baseline_text is not None
            edits.append(_write_baseline(config, baseline_id, baseline_text, baseline_file))
        for mid in member_ids:
            edits.append(
                set_field(config, mid, f"variant_of={baseline_id}", expect_sha=None, dry_run=False)
            )
        load(config)  # whole-model gate: variant_of resolves, no variant-of-a-variant chains
    except BaseException as exc:  # any failure -> roll the whole group back
        _restore(snapshot)
        if isinstance(exc, (WriteError, LoaderError)):
            raise WriteError(f"recurrence --apply rejected: {exc}") from exc
        raise
    if dry_run:
        _restore(snapshot)
    return edits
