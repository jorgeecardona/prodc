"""Load need files (YAML) into :class:`~prodc.model.Need` objects.

A file-level ``who``/``label`` default every need in it; a need may override either.
IDs are globally unique (children reference ids across files), so a duplicate is a
:class:`LoaderError`. A flow (need with ``children``) must not also carry ``proofs``.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import cast

import yaml

from .config import Config
from .model import Need, Source, SourceKind


class LoaderError(Exception):
    pass


def _as_mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LoaderError(f"{where}: expected a mapping")
    return cast("dict[str, object]", value)


def _as_list(value: object, where: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LoaderError(f"{where}: expected a list")
    return cast("list[object]", value)


def _as_str(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise LoaderError(f"{where}: expected a string")
    return value


def _opt_str(value: object, where: str) -> str | None:
    if value is None:
        return None
    # A bare ``date: 2026-09-20`` parses as a date, not a string — accept it.
    if isinstance(value, datetime.date):
        return value.isoformat()
    return _as_str(value, where)


def _opt_importance(value: object, where: str) -> int | None:
    if value is None:
        return None
    # bool is a subclass of int — reject it so `importance: true` is not read as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise LoaderError(f"{where}: expected a positive integer ordinal")
    if value < 1:
        raise LoaderError(f"{where}: expected a positive integer ordinal, got {value}")
    return value


def _as_bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise LoaderError(f"{where}: expected a boolean")
    return value


def _source(raw: object, where: str) -> Source:
    tbl = _as_mapping(raw, where)
    kind_name = _opt_str(tbl.get("kind"), f"{where}.kind") or SourceKind.INTERNAL.value
    try:
        kind = SourceKind(kind_name)
    except ValueError:
        kinds = "|".join(k.value for k in SourceKind)
        raise LoaderError(f"{where}.kind: unknown kind {kind_name!r} ({kinds})") from None
    return Source(
        kind=kind,
        who=_opt_str(tbl.get("who"), f"{where}.who"),
        date=_opt_str(tbl.get("date"), f"{where}.date"),
        quote=_opt_str(tbl.get("quote"), f"{where}.quote"),
        locator=_opt_str(tbl.get("locator"), f"{where}.locator"),
    )


def _need(
    raw: object,
    where: str,
    file_who: str | None,
    file_label: str | None,
    file_client: str | None,
) -> Need:
    tbl = _as_mapping(raw, where)
    nid = _as_str(tbl.get("id"), f"{where}.id")
    text = _as_str(tbl.get("text"), f"{where}.text")
    must = _as_bool(tbl["must"], f"{where}.must") if "must" in tbl else False
    who = _opt_str(tbl.get("who"), f"{where}.who") or file_who
    label = _opt_str(tbl.get("label"), f"{where}.label") or file_label
    client = _opt_str(tbl.get("client"), f"{where}.client") or file_client
    variant_of = _opt_str(tbl.get("variant_of"), f"{where}.variant_of")
    importance = _opt_importance(tbl.get("importance"), f"{where}.importance")

    sources = tuple(
        _source(s, f"{where}.sources[{i}]")
        for i, s in enumerate(_as_list(tbl.get("sources"), f"{where}.sources"))
    )
    proofs = tuple(
        _as_str(p, f"{where}.proofs[{i}]")
        for i, p in enumerate(_as_list(tbl.get("proofs"), f"{where}.proofs"))
    )
    children = tuple(
        _as_str(c, f"{where}.children[{i}]")
        for i, c in enumerate(_as_list(tbl.get("children"), f"{where}.children"))
    )
    if children and proofs:
        raise LoaderError(f"{where} ({nid}): a flow (need with children) must not carry proofs")

    return Need(
        id=nid,
        text=text,
        who=who,
        must=must,
        sources=sources,
        proofs=proofs,
        children=children,
        label=label,
        client=client,
        variant_of=variant_of,
        importance=importance,
    )


def _load_file(path: Path, seen: dict[str, Path]) -> list[Need]:
    where = path.name
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LoaderError(f"{where}: invalid YAML: {exc}") from exc
    if doc is None:
        return []
    tbl = _as_mapping(doc, where)
    file_who = _opt_str(tbl.get("who"), f"{where}.who")
    file_label = _opt_str(tbl.get("label"), f"{where}.label")
    file_client = _opt_str(tbl.get("client"), f"{where}.client")

    out: list[Need] = []
    for i, raw in enumerate(_as_list(tbl.get("needs"), f"{where}.needs")):
        need = _need(raw, f"{where}.needs[{i}]", file_who, file_label, file_client)
        prior = seen.get(need.id)
        if prior is not None:
            raise LoaderError(f"duplicate need id {need.id!r} in {where} and {prior.name}")
        seen[need.id] = path
        out.append(need)
    return out


def load_needs(config: Config) -> list[Need]:
    """Resolve every need glob in ``config`` to a flat, id-unique list of needs."""
    needs: list[Need] = []
    seen: dict[str, Path] = {}
    for pattern in config.need_globs:
        for path in sorted(config.root.glob(pattern)):
            needs.extend(_load_file(path, seen))
    _check_variants(needs)
    return needs


def _check_variants(needs: list[Need]) -> None:
    """Every ``variant_of`` must point at a known baseline need (one that is not itself a variant)."""
    by_id = {n.id: n for n in needs}
    for need in needs:
        if need.variant_of is None:
            continue
        base = by_id.get(need.variant_of)
        if base is None:
            raise LoaderError(
                f"need {need.id!r}: variant_of {need.variant_of!r} is not a known need id"
            )
        if base.is_variant:
            raise LoaderError(
                f"need {need.id!r}: variant_of {need.variant_of!r} is itself a variant "
                "(variants cannot chain)"
            )
