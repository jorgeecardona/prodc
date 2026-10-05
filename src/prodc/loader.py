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
from .model import Attestation, Goal, Model, Need, Source, SourceKind


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


def _attestation(raw: object, where: str) -> Attestation | None:
    if raw is None:
        return None
    tbl = _as_mapping(raw, where)
    who = _opt_str(tbl.get("who"), f"{where}.who")
    date = _opt_str(tbl.get("date"), f"{where}.date")
    if not who or not date:
        raise LoaderError(f"{where}: an attestation needs both 'who' and 'date'")
    return Attestation(who=who, date=date)


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
    claim = _opt_str(tbl.get("claim"), f"{where}.claim")
    attestation = _attestation(tbl.get("attested"), f"{where}.attested")
    goal = _opt_str(tbl.get("goal"), f"{where}.goal")

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
        claim=claim,
        attestation=attestation,
        goal=goal,
    )


def _goal(raw: object, where: str) -> Goal:
    tbl = _as_mapping(raw, where)
    return Goal(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
        metric=_opt_str(tbl.get("metric"), f"{where}.metric"),
    )


def _load_file(
    path: Path, need_seen: dict[str, Path], goal_seen: dict[str, Path]
) -> tuple[list[Need], list[Goal]]:
    """Parse one prodc file for every noun list it carries (``needs:``, ``goals:``)."""
    where = path.name
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LoaderError(f"{where}: invalid YAML: {exc}") from exc
    if doc is None:
        return [], []
    tbl = _as_mapping(doc, where)
    file_who = _opt_str(tbl.get("who"), f"{where}.who")
    file_label = _opt_str(tbl.get("label"), f"{where}.label")
    file_client = _opt_str(tbl.get("client"), f"{where}.client")

    needs: list[Need] = []
    for i, raw in enumerate(_as_list(tbl.get("needs"), f"{where}.needs")):
        need = _need(raw, f"{where}.needs[{i}]", file_who, file_label, file_client)
        prior = need_seen.get(need.id)
        if prior is not None:
            raise LoaderError(f"duplicate need id {need.id!r} in {where} and {prior.name}")
        need_seen[need.id] = path
        needs.append(need)

    goals: list[Goal] = []
    for i, raw in enumerate(_as_list(tbl.get("goals"), f"{where}.goals")):
        goal = _goal(raw, f"{where}.goals[{i}]")
        prior = goal_seen.get(goal.id)
        if prior is not None:
            raise LoaderError(f"duplicate goal id {goal.id!r} in {where} and {prior.name}")
        goal_seen[goal.id] = path
        goals.append(goal)
    return needs, goals


def load(config: Config) -> Model:
    """Read every prodc file once into a :class:`~prodc.model.Model`, then validate cross-refs.

    One loader for every noun: ids are unique within their kind, and each string reference
    (``variant_of``, ``children``, ``goal``) is checked here as a hard error — a dangling
    reference to something declared in these files is a typo you own, not a runtime unknown.
    """
    needs: list[Need] = []
    goals: list[Goal] = []
    need_seen: dict[str, Path] = {}
    goal_seen: dict[str, Path] = {}
    for pattern in config.need_globs:
        for path in sorted(config.root.glob(pattern)):
            file_needs, file_goals = _load_file(path, need_seen, goal_seen)
            needs.extend(file_needs)
            goals.extend(file_goals)
    _check_variants(needs)
    _check_children(needs)
    _check_goal_refs(needs, goals)
    return Model(needs=tuple(needs), goals=tuple(goals))


def load_needs(config: Config) -> list[Need]:
    """Convenience: just the needs from :func:`load`."""
    return list(load(config).needs)


def _check_goal_refs(needs: list[Need], goals: list[Goal]) -> None:
    """Every ``need.goal`` must name a known goal id."""
    known = {g.id for g in goals}
    for need in needs:
        if need.goal is not None and need.goal not in known:
            raise LoaderError(f"need {need.id!r}: goal {need.goal!r} is not a known goal id")


def _check_children(needs: list[Need]) -> None:
    """Every id in a need's ``children`` must name a known need."""
    known = {n.id for n in needs}
    for need in needs:
        for cid in need.children:
            if cid not in known:
                raise LoaderError(f"need {need.id!r}: child {cid!r} is not a known need id")


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
