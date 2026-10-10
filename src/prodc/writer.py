"""Write-back: let an agent record its decisions as need YAML, safely (#24).

The one dangerous thing prodc does is edit files, so every edit goes through one gate:
mutate a copy of the target file, write it, re-run :func:`~prodc.loader.load` as the schema,
and revert if the model no longer loads. An in-place edit splices only the changed need's block
back into the original text (#53), so the file header and every other need keep their comments
and formatting; only the edited need's own block is reflowed, and an unrecognised file shape
falls back to a full PyYAML re-dump. One file per edit, always shown as a diff.
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from .config import Config
from .loader import LoaderError, load

# Fields an agent may `set` on a need. Unknown keys are silently ignored by the loader, so the
# write path allowlists instead — a typo'd key is an error here, not junk written to disk.
_SCALAR_FIELDS = frozenset(
    {
        "text",
        "description",
        "who",
        "role",
        "label",
        "must",
        "importance",
        "claim",
        "goal",
        "release",
        "variant_of",
        "client",
        "product",
        "draft",
    }
)
_LIST_FIELDS = frozenset({"proofs", "children"})

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
    """Line span [start, end) and item indent of the `needs:` item whose id is ``need_id``.

    Line-based and deliberately conservative: it understands the common prodc layout (a
    top-level ``needs:`` key whose items are ``- `` at a fixed indent) and returns None for
    anything it is not sure about, so the caller can fall back to a full re-dump. Trailing
    blank and comment lines are left out of the span, so a comment that introduces the *next*
    need is never swallowed.
    """
    needs_at = next((i for i, ln in enumerate(lines) if re.match(r"^needs:\s*(#.*)?$", ln)), None)
    if needs_at is None:
        return None
    item_re = None
    item_indent = -1
    i = needs_at + 1
    spans: list[tuple[int, int, int, str | None]] = []  # start, end, indent, id
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
                return None  # first non-blank line under needs: isn't a list item — unknown shape
            item_indent = len(m.group(1))
            item_re = re.compile(rf"^\s{{{item_indent}}}-\s")
        if indent < item_indent and m is None:
            break  # dedented past the list — end of needs:
        if item_re.match(line):
            spans.append((i, i, item_indent, _item_id(lines, i, item_indent)))
        elif indent <= item_indent and m is None:
            break
        i += 1
    # close each span at the start of the next item (or `i`, the end of the list region)
    bounds = [s[0] for s in spans] + [i]
    for idx, (start, _e, indent, iid) in enumerate(spans):
        if iid != need_id:
            continue
        end = bounds[idx + 1]
        while end - 1 > start and (
            lines[end - 1].strip() == "" or lines[end - 1].strip().startswith("#")
        ):
            end -= 1
        return start, end, indent
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
    bool; dumping it as-is would write ``answer: false`` — loads fine (the loader coerces it),
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
    behaviour) when the file's shape is anything the splice isn't sure of — the reload gate in
    :func:`_validated` guards correctness either way.
    """
    _normalize_answer(doc)
    lines = old_text.splitlines(keepends=True)
    span = _need_block_span(lines, need_id)
    needs = doc.get("needs")
    if span is None or not isinstance(needs, list):
        return _dump(doc)
    start, end, indent = span
    need = next(
        (
            cast("dict[str, object]", n)
            for n in cast("list[object]", needs)
            if isinstance(n, dict) and cast("dict[str, object]", n).get("id") == need_id
        ),
        None,
    )
    if need is None:
        return _dump(doc)
    dumped = yaml.safe_dump([need], sort_keys=False, allow_unicode=True, default_flow_style=False)
    pad = " " * indent
    block = "".join(pad + ln if ln.strip() else ln for ln in dumped.splitlines(keepends=True))
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _read_doc(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WriteError(f"{path.name}: invalid YAML: {exc}") from exc
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


def _config_files(config: Config) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in config.need_globs:
        for path in sorted(config.root.glob(pattern)):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _locate(config: Config, need_id: str) -> tuple[Path, dict[str, object]]:
    """Find the file and the raw need mapping for ``need_id``."""
    for path in _config_files(config):
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
        items.append(raw.strip())
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
        raise WriteError(f"{path.name} does not match any [prodc].needs glob")


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


def set_field(
    config: Config, need_id: str, assignment: str, *, expect_sha: str | None, dry_run: bool
) -> Edit:
    """Set or list-append one field on an existing need, validated against the loader."""
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            _apply_assignment(cast("dict[str, object]", raw), assignment, path)
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def set_importance(
    config: Config, need_id: str, level: int, when: str, *, expect_sha: str | None, dry_run: bool
) -> Edit:
    """Set a need's importance and record ``importance_set_at`` in one edit (#59).

    The level is already resolved against the rubric by the caller; this just writes both fields
    together so ranking never refines on a number nobody has revisited.
    """
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            need = cast("dict[str, object]", raw)
            need["importance"] = level
            need["importance_set_at"] = when
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def capture_source(
    config: Config,
    need_id: str,
    *,
    kind: str,
    who: str | None,
    date: str | None,
    quote: str | None,
    locator: str | None,
    observed_at: str | None = None,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Append a Source to an existing need — the near-zero-friction capture of #24.

    Records evidence as given; the loader's soft hygiene checks (a primary source wants a who and a
    quote-or-locator, a secondary source wants a locator) still apply on the next read.
    ``observed_at`` dates when the evidence was recorded, so the board can flag stale needs (#58).
    """
    kind = _canonical_kind(kind)
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    source: dict[str, object] = {"kind": kind}
    for key, value in (
        ("who", who),
        ("date", date),
        ("quote", quote),
        ("locator", locator),
        ("observed_at", observed_at),
    ):
        if value is not None:
            source[key] = value
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            need = cast("dict[str, object]", raw)
            current = need.get("sources", [])
            if not isinstance(current, list):
                raise WriteError(f"{path.name}: 'sources' is not a list")
            sources = cast("list[object]", current)
            sources.append(source)
            need["sources"] = sources
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


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
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            cast("dict[str, object]", raw)["attestation"] = att
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def withdraw(
    config: Config,
    need_id: str,
    *,
    reason: str,
    date: str,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Record a decision against a need — withdrawn / won't-do (#74).

    Writes a ``withdrawn: {reason, date}`` mapping onto the need, which takes it off the active
    board and out of coverage; the record stays as its durable trace. Replaces any existing
    withdrawal (re-withdrawing updates the reason/date). Reinstate with :func:`reinstate`.
    """
    mark: dict[str, object] = {"reason": reason, "date": date}
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            cast("dict[str, object]", raw)["withdrawn"] = mark
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def reinstate(config: Config, need_id: str, *, expect_sha: str | None, dry_run: bool) -> Edit:
    """Remove a need's ``withdrawn`` mark, putting it back on the active board (#74).

    Errors if the need is not currently withdrawn — reinstating a live need is a mistake worth
    surfacing, not a silent no-op.
    """
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            need = cast("dict[str, object]", raw)
            if "withdrawn" not in need:
                raise WriteError(f"need {need_id!r} is not withdrawn")
            del need["withdrawn"]
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


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

    Some needs are proven by a person looking, not a test — this makes recording that a
    one-liner instead of a hand edit. Idempotent: re-accepting the same who/date is a no-op.
    """
    locator = f"accept:{who}@{date}"
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            need = cast("dict[str, object]", raw)
            current = need.get("proofs", [])
            if not isinstance(current, list):
                raise WriteError(f"{path.name}: 'proofs' is not a list")
            proofs = [p for p in cast("list[object]", current)]
            if revoke:
                proofs = [p for p in proofs if p != locator]
            elif locator not in proofs:
                proofs.append(locator)
            need["proofs"] = proofs
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


def add_proof(
    config: Config, need_id: str, locator: str, *, expect_sha: str | None = None, dry_run: bool
) -> Edit:
    """Append a proof locator to an existing need, idempotently — the write path for `suggest --apply`.

    A thin single-field edit (same splice as :func:`set_field` `proofs+=`), factored out so the
    batch apply can call it per need and show each need's diff. Re-adding a locator already on the
    need is a no-op, so applying the same suggestion twice does not duplicate it (#54).
    """
    path, _ = _locate(config, need_id)
    doc, old_text = _read_doc(path)
    if expect_sha is not None and _sha256(old_text) != expect_sha:
        raise WriteError(f"{path.name} changed since it was read (optimistic lock)")
    for raw in _need_list(doc, path):
        if isinstance(raw, dict) and cast("dict[str, object]", raw).get("id") == need_id:
            need = cast("dict[str, object]", raw)
            current = need.get("proofs", [])
            if not isinstance(current, list):
                raise WriteError(f"{path.name}: 'proofs' is not a list")
            proofs = list(cast("list[object]", current))
            if locator not in proofs:
                proofs.append(locator)
            need["proofs"] = proofs
            break
    return _validated(config, path, old_text, _render_edit(old_text, doc, need_id), dry_run)


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

    An agent-authored need must carry a source — and never ``primary``, which only a real user
    signal earns. ``kind`` is restricted to ``assumption`` (the agent's own guess) or ``secondary``
    (citing an existing document). A ``draft`` need is staged: it loads but is kept off the counted
    board until promoted (#60).
    """
    kind = _SOURCE_KIND_ALIASES.get(kind, kind)
    if kind not in ("assumption", "secondary"):
        raise WriteError(
            f"agent-authored need source must be assumption or secondary, not {kind!r} "
            "(never primary — that is earned by a real user signal)"
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
    needs.append(new_need)
    return _validated(config, target, old_text, _dump(doc), dry_run)


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
    edit. Like :func:`add_need`, a new/edited file is re-dumped whole (comments in that file are
    not preserved — use `set` on an existing need for a comment-safe splice); the reload gate
    still rejects anything that does not load. A duplicate role id is refused.
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
    return _validated(config, target, old_text, _dump(doc), dry_run)


def _snapshot(paths: list[Path]) -> dict[Path, str | None]:
    """Current text of each path, or None when it does not exist — a point to roll back to."""
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

    Unlike :func:`add_need`, it attaches no source — a recurrence baseline is a structural roll-up
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
    snapshotted up front; any rejection — or ``dry_run`` — restores every one, so the group is
    linked all-or-nothing.
    """
    touched = _config_files(config)
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
