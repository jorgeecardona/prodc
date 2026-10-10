"""Load need files (YAML) into :class:`~prodc.model.Need` objects.

A file-level ``who``/``label`` default every need in it; a need may override either.
IDs are globally unique (children reference ids across files), so a duplicate is a
:class:`LoaderError`. A flow (need with ``children``) must not also carry ``proofs``.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from .config import Config
from .model import (
    ArgKind,
    ArgNode,
    Attestation,
    AttestationKind,
    Goal,
    Model,
    Need,
    Release,
    Role,
    Source,
    SourceKind,
    Withdrawal,
)


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
    kind_name = _opt_str(tbl.get("kind"), f"{where}.kind") or AttestationKind.HUMAN.value
    try:
        kind = AttestationKind(kind_name)
    except ValueError:
        kinds = "|".join(k.value for k in AttestationKind)
        raise LoaderError(f"{where}.kind: unknown kind {kind_name!r} ({kinds})") from None
    return Attestation(
        who=who,
        date=date,
        kind=kind,
        verdict=_opt_str(tbl.get("verdict"), f"{where}.verdict"),
        comment=_opt_str(tbl.get("comment"), f"{where}.comment"),
    )


def _withdrawal(raw: object, where: str) -> Withdrawal | None:
    """Parse ``withdrawn: {reason, date}`` into a :class:`Withdrawal` (#74).

    Both fields are required when the key is present — a decision against a need must say why
    and when, the same way an attestation needs who and when.
    """
    if raw is None:
        return None
    tbl = _as_mapping(raw, where)
    reason = _opt_str(tbl.get("reason"), f"{where}.reason")
    date = _opt_str(tbl.get("date"), f"{where}.date")
    if not reason or not date:
        raise LoaderError(f"{where}: a withdrawal needs both 'reason' and 'date'")
    return Withdrawal(reason=reason, date=date)


# Old source-kind names (pre-0.3.58) mapped to the primary/secondary/assumption ladder, so
# existing need files keep loading. `interview` was live user contact (primary); `artifact` was a
# cited document (secondary); `proxy`/`internal` were both unevidenced guesses (assumption).
_SOURCE_KIND_ALIASES = {
    "interview": SourceKind.PRIMARY,
    "artifact": SourceKind.SECONDARY,
    "proxy": SourceKind.ASSUMPTION,
    "internal": SourceKind.ASSUMPTION,
}


def _source(raw: object, where: str) -> Source:
    tbl = _as_mapping(raw, where)
    kind_name = _opt_str(tbl.get("kind"), f"{where}.kind") or SourceKind.ASSUMPTION.value
    kind = _SOURCE_KIND_ALIASES.get(kind_name)
    if kind is None:
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
        observed_at=_opt_str(tbl.get("observed_at"), f"{where}.observed_at"),
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
    description = _opt_str(tbl.get("description"), f"{where}.description")
    must = _as_bool(tbl["must"], f"{where}.must") if "must" in tbl else False
    who = _opt_str(tbl.get("who"), f"{where}.who") or file_who
    role = _opt_str(tbl.get("role"), f"{where}.role")
    label = _opt_str(tbl.get("label"), f"{where}.label") or file_label
    client = _opt_str(tbl.get("client"), f"{where}.client") or file_client
    variant_of = _opt_str(tbl.get("variant_of"), f"{where}.variant_of")
    importance = _opt_importance(tbl.get("importance"), f"{where}.importance")
    importance_set_at = _opt_str(tbl.get("importance_set_at"), f"{where}.importance_set_at")
    claim = _opt_str(tbl.get("claim"), f"{where}.claim")
    attestation = _attestation(tbl.get("attestation"), f"{where}.attestation")
    goal = _opt_str(tbl.get("goal"), f"{where}.goal")
    release = _opt_str(tbl.get("release"), f"{where}.release")
    product = _as_bool(tbl["product"], f"{where}.product") if "product" in tbl else True
    draft = _as_bool(tbl["draft"], f"{where}.draft") if "draft" in tbl else False
    withdrawn = _withdrawal(tbl.get("withdrawn"), f"{where}.withdrawn")

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
    seam = tuple(
        _as_str(s, f"{where}.seam[{i}]")
        for i, s in enumerate(_as_list(tbl.get("seam"), f"{where}.seam"))
    )
    not_duplicate_of = tuple(
        _as_str(d, f"{where}.not_duplicate_of[{i}]")
        for i, d in enumerate(_as_list(tbl.get("not_duplicate_of"), f"{where}.not_duplicate_of"))
    )
    not_variant_of = tuple(
        _as_str(d, f"{where}.not_variant_of[{i}]")
        for i, d in enumerate(_as_list(tbl.get("not_variant_of"), f"{where}.not_variant_of"))
    )
    if children and proofs:
        raise LoaderError(
            f"{where} ({nid}): a flow (need with children) proves its steps via the "
            "children's proofs and its between-steps behaviour via 'seam', not 'proofs'"
        )
    if seam and not children:
        raise LoaderError(f"{where} ({nid}): 'seam' is for a flow; a leaf need uses 'proofs'")

    return Need(
        id=nid,
        text=text,
        description=description,
        who=who,
        role=role,
        must=must,
        sources=sources,
        proofs=proofs,
        children=children,
        seam=seam,
        label=label,
        client=client,
        variant_of=variant_of,
        importance=importance,
        claim=claim,
        attestation=attestation,
        goal=goal,
        release=release,
        product=product,
        not_duplicate_of=not_duplicate_of,
        not_variant_of=not_variant_of,
        importance_set_at=importance_set_at,
        draft=draft,
        withdrawn=withdrawn,
    )


def _goal(raw: object, where: str) -> Goal:
    tbl = _as_mapping(raw, where)
    return Goal(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
        metric=_opt_str(tbl.get("metric"), f"{where}.metric"),
    )


def _release(raw: object, where: str) -> Release:
    tbl = _as_mapping(raw, where)
    return Release(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
    )


def _role(raw: object, where: str) -> Role:
    tbl = _as_mapping(raw, where)
    return Role(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
    )


def _arg_node(raw: object, where: str) -> ArgNode:
    tbl = _as_mapping(raw, where)
    kind_name = _as_str(tbl.get("kind"), f"{where}.kind")
    try:
        kind = ArgKind(kind_name)
    except ValueError:
        kinds = "|".join(k.value for k in ArgKind)
        raise LoaderError(f"{where}.kind: unknown kind {kind_name!r} ({kinds})") from None
    return ArgNode(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        kind=kind,
        text=_as_str(tbl.get("text"), f"{where}.text"),
        supported_by=tuple(
            _as_str(x, f"{where}.supported_by[{i}]")
            for i, x in enumerate(_as_list(tbl.get("supported_by"), f"{where}.supported_by"))
        ),
        in_context_of=tuple(
            _as_str(x, f"{where}.in_context_of[{i}]")
            for i, x in enumerate(_as_list(tbl.get("in_context_of"), f"{where}.in_context_of"))
        ),
        about=_opt_str(tbl.get("about"), f"{where}.about"),
    )


@dataclass
class _Loaded:
    """One file's nouns, accumulated across the glob into the final :class:`Model`."""

    needs: list[Need] = field(default_factory=list[Need])
    goals: list[Goal] = field(default_factory=list[Goal])
    releases: list[Release] = field(default_factory=list[Release])
    roles: list[Role] = field(default_factory=list[Role])
    argument: list[ArgNode] = field(default_factory=list[ArgNode])


def _load_file(path: Path, seen: dict[str, dict[str, Path]]) -> _Loaded:
    """Parse one prodc file for every noun list it carries (``needs:``/``goals:``/``releases:``)."""
    where = path.name
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LoaderError(f"{where}: invalid YAML: {exc}") from exc
    out = _Loaded()
    if doc is None:
        return out
    tbl = _as_mapping(doc, where)
    file_who = _opt_str(tbl.get("who"), f"{where}.who")
    file_label = _opt_str(tbl.get("label"), f"{where}.label")
    file_client = _opt_str(tbl.get("client"), f"{where}.client")

    def _unique(kind: str, nid: str) -> None:
        prior = seen[kind].get(nid)
        if prior is not None:
            raise LoaderError(f"duplicate {kind} id {nid!r} in {where} and {prior.name}")
        seen[kind][nid] = path

    for i, raw in enumerate(_as_list(tbl.get("needs"), f"{where}.needs")):
        need = _need(raw, f"{where}.needs[{i}]", file_who, file_label, file_client)
        _unique("need", need.id)
        out.needs.append(need)
    for i, raw in enumerate(_as_list(tbl.get("goals"), f"{where}.goals")):
        goal = _goal(raw, f"{where}.goals[{i}]")
        _unique("goal", goal.id)
        out.goals.append(goal)
    for i, raw in enumerate(_as_list(tbl.get("releases"), f"{where}.releases")):
        release = _release(raw, f"{where}.releases[{i}]")
        _unique("release", release.id)
        out.releases.append(release)
    for i, raw in enumerate(_as_list(tbl.get("roles"), f"{where}.roles")):
        role = _role(raw, f"{where}.roles[{i}]")
        _unique("role", role.id)
        out.roles.append(role)
    for i, raw in enumerate(_as_list(tbl.get("argument"), f"{where}.argument")):
        node = _arg_node(raw, f"{where}.argument[{i}]")
        _unique("argument node", node.id)
        out.argument.append(node)
    return out


def load(config: Config) -> Model:
    """Read every prodc file once into a :class:`~prodc.model.Model`, then validate cross-refs.

    One loader for every noun: ids are unique within their kind, and each string reference
    (``variant_of``, ``children``, ``goal``, ``release``, ``role``) is checked here as a hard
    error — a dangling reference to something declared in these files is a typo you own, not a
    runtime unknown. ``role`` is checked unconditionally like ``goal``/``release``: it is a new
    field, so (unlike free-text ``who``) there is no migration reason to make it lax.
    """
    acc = _Loaded()
    seen: dict[str, dict[str, Path]] = {
        "need": {},
        "goal": {},
        "release": {},
        "role": {},
        "argument node": {},
    }
    for pattern in config.need_globs:
        for path in sorted(config.root.glob(pattern)):
            f = _load_file(path, seen)
            acc.needs.extend(f.needs)
            acc.goals.extend(f.goals)
            acc.releases.extend(f.releases)
            acc.roles.extend(f.roles)
            acc.argument.extend(f.argument)
    _check_variants(acc.needs)
    _check_children(acc.needs)
    _check_ref(acc.needs, "goal", lambda n: n.goal, {g.id for g in acc.goals})
    _check_ref(acc.needs, "release", lambda n: n.release, {r.id for r in acc.releases})
    _check_ref(acc.needs, "role", lambda n: n.role, {p.id for p in acc.roles})
    _check_argument(acc.argument)
    return Model(
        needs=tuple(acc.needs),
        goals=tuple(acc.goals),
        releases=tuple(acc.releases),
        roles=tuple(acc.roles),
        argument=tuple(acc.argument),
    )


def load_needs(config: Config) -> list[Need]:
    """Convenience: just the needs from :func:`load`."""
    return list(load(config).needs)


def _check_ref(
    needs: list[Need], role: str, pick: Callable[[Need], str | None], known: set[str]
) -> None:
    """Every ``need.<role>`` that is set must name a declared id of that kind."""
    for need in needs:
        ref = pick(need)
        if ref is not None and ref not in known:
            raise LoaderError(f"need {need.id!r}: {role} {ref!r} is not a known {role} id")


def _check_argument(argument: list[ArgNode]) -> None:
    """Every ``supported_by``/``in_context_of`` link must name a known argument node.

    Only the intra-graph links are hard errors here; ``about`` may cite a proof locator that
    is not declared in these files, so it is left to resolve at status time. Soft defects (an
    unsupported claim, a dangling assumption) are reported by :func:`~prodc.status.argument_defects`.
    """
    known = {n.id for n in argument}
    for node in argument:
        for ref in (*node.supported_by, *node.in_context_of):
            if ref not in known:
                raise LoaderError(
                    f"argument node {node.id!r}: link {ref!r} is not a known argument node id"
                )


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
