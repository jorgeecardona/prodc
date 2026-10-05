"""Write-back: let an agent record its decisions as need YAML, safely (#24).

The one dangerous thing prodc does is edit files, so every edit goes through one gate:
mutate a copy of the target file, write it, re-run :func:`~prodc.loader.load` as the schema,
and revert if the model no longer loads. PyYAML's dumper reflows style and drops comments, so
an edit reformats the whole file it touches — kept to one file per edit, always shown as a diff.
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
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
        "who",
        "label",
        "must",
        "importance",
        "claim",
        "goal",
        "release",
        "variant_of",
        "client",
    }
)
_LIST_FIELDS = frozenset({"proofs", "children"})


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
    """Write ``new_text``, re-load the model as the schema, and revert on failure or dry-run."""
    _guard_target(config, path)
    path.write_text(new_text, encoding="utf-8")
    try:
        load(config)
    except BaseException as exc:  # revert on ANY failure, then re-raise
        path.write_text(old_text, encoding="utf-8")
        if isinstance(exc, LoaderError):
            raise WriteError(f"edit rejected: {exc}") from exc
        raise
    if dry_run:
        path.write_text(old_text, encoding="utf-8")
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
    return _validated(config, path, old_text, _dump(doc), dry_run)


def add_need(
    config: Config,
    need_id: str,
    text: str,
    *,
    who: str,
    kind: str,
    file: str,
    expect_sha: str | None,
    dry_run: bool,
) -> Edit:
    """Create a new need in ``file`` with an agent-provenance source (never a silent opinion).

    An agent-authored need must carry a source — and never ``interview``, which only a real
    user signal earns. ``kind`` is restricted to ``proxy``/``internal`` for that reason.
    """
    if kind not in ("proxy", "internal"):
        raise WriteError(f"agent-authored need source must be proxy or internal, not {kind!r}")
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
    needs.append(
        {
            "id": need_id,
            "text": text,
            "sources": [{"kind": kind, "who": who, "date": today}],
        }
    )
    return _validated(config, target, old_text, _dump(doc), dry_run)
