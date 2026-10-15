"""Load need files (YAML) into :class:`~prodc.model.Need` objects.

A file-level ``who``/``label`` default every need in it; a need may override either.
IDs are globally unique (children reference ids across files), so a duplicate is a
:class:`LoaderError`. A flow (need with ``children``) must not also carry ``proofs``.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import yaml

from .config import Config
from .model import (
    Answer,
    ArgKind,
    ArgNode,
    Attestation,
    AttestationKind,
    Goal,
    Model,
    Need,
    Principle,
    Release,
    Role,
    Source,
    SourceKind,
    Withdrawal,
    WithdrawalKind,
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


def _answer(raw: object, where: str) -> Answer | None:
    """Parse ``answer: yes|no|inconclusive`` into an :class:`Answer`, validated like other enums.

    The direction a settled research question resolved; absent on a product need. Same
    ``Enum(name) except ValueError`` pattern as ``SourceKind``/``ArgKind`` so an unknown value is
    a :class:`LoaderError` the author owns, not silent junk.

    YAML 1.1 reads a bare ``yes``/``no`` as a boolean, so ``answer: no`` arrives as ``False`` —
    coerced back to the string here, the same way ``_opt_str`` accepts a bare ``date:`` that
    parsed as a date. ``inconclusive`` is a plain string and needs no coercion.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        raw = "yes" if raw else "no"
    name = _as_str(raw, where)
    try:
        return Answer(name)
    except ValueError:
        answers = "|".join(a.value for a in Answer)
        raise LoaderError(f"{where}: unknown answer {name!r} ({answers})") from None


def _withdrawal(raw: object, where: str) -> Withdrawal | None:
    """Parse ``withdrawn: {reason, date, kind?, principle?}`` into a :class:`Withdrawal` (#74).

    ``reason`` and ``date`` are required when the key is present — a decision against a need must
    say why and when, the same way an attestation needs who and when. ``kind`` is optional and
    defaults to ``wont_do``; it is validated with the same ``Enum(name) except ValueError`` pattern
    as ``SourceKind``, so an unknown kind is a :class:`LoaderError` the author owns. ``principle`` is
    an optional Principle id, checked against the declared principles once every file is loaded.
    """
    if raw is None:
        return None
    tbl = _as_mapping(raw, where)
    reason = _opt_str(tbl.get("reason"), f"{where}.reason")
    date = _opt_str(tbl.get("date"), f"{where}.date")
    if not reason or not date:
        raise LoaderError(f"{where}: a withdrawal needs both 'reason' and 'date'")
    kind_name = _opt_str(tbl.get("kind"), f"{where}.kind") or WithdrawalKind.WONT_DO.value
    try:
        kind = WithdrawalKind(kind_name)
    except ValueError:
        kinds = "|".join(k.value for k in WithdrawalKind)
        raise LoaderError(
            f"{where}.kind: unknown withdrawal kind {kind_name!r} ({kinds})"
        ) from None
    principle = _opt_str(tbl.get("principle"), f"{where}.principle")
    return Withdrawal(reason=reason, date=date, kind=kind, principle=principle)


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
        role=_opt_str(tbl.get("role"), f"{where}.role"),
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
    draft_added = _opt_str(tbl.get("draft_added"), f"{where}.draft_added")
    withdrawn = _withdrawal(tbl.get("withdrawn"), f"{where}.withdrawn")
    answer = _answer(tbl.get("answer"), f"{where}.answer")

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
    contradicts = tuple(
        _as_str(c, f"{where}.contradicts[{i}]")
        for i, c in enumerate(_as_list(tbl.get("contradicts"), f"{where}.contradicts"))
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
        contradicts=contradicts,
        importance_set_at=importance_set_at,
        draft=draft,
        draft_added=draft_added,
        withdrawn=withdrawn,
        answer=answer,
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


def _principle(raw: object, where: str) -> Principle:
    """Parse one ``principles:`` entry — a product commitment with its provenance."""
    tbl = _as_mapping(raw, where)
    return Principle(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
        revised_at=_opt_str(tbl.get("revised_at"), f"{where}.revised_at"),
        sources=tuple(
            _source(s, f"{where}.sources[{i}]")
            for i, s in enumerate(_as_list(tbl.get("sources"), f"{where}.sources"))
        ),
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
    principles: list[Principle] = field(default_factory=list[Principle])
    argument: list[ArgNode] = field(default_factory=list[ArgNode])


def _load_file(path: Path, seen: dict[str, dict[str, Path]]) -> _Loaded:
    """Parse one prodc file for every noun list it carries (``needs:``/``goals:``/``principles:``/…)."""
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
    for i, raw in enumerate(_as_list(tbl.get("principles"), f"{where}.principles")):
        principle = _principle(raw, f"{where}.principles[{i}]")
        _unique("principle", principle.id)
        out.principles.append(principle)
    for i, raw in enumerate(_as_list(tbl.get("argument"), f"{where}.argument")):
        node = _arg_node(raw, f"{where}.argument[{i}]")
        _unique("argument node", node.id)
        out.argument.append(node)
    return out


def load(config: Config) -> Model:
    """Read every prodc file once into a :class:`~prodc.model.Model`, then validate cross-refs.

    One loader for every noun: ids are unique within their kind, and each string reference
    (``variant_of``, ``children``, ``goal``, ``release``, ``role``, a withdrawal's ``principle``) is
    checked here as a hard error — a dangling reference to something declared in these files is a
    typo you own, not a runtime unknown. ``role`` is checked unconditionally like
    ``goal``/``release``: it is a new field, so (unlike free-text ``who``) there is no migration
    reason to make it lax.
    """
    acc = _Loaded()
    seen: dict[str, dict[str, Path]] = {
        "need": {},
        "goal": {},
        "release": {},
        "role": {},
        "principle": {},
        "argument node": {},
    }
    for pattern in config.need_globs:
        for path in sorted(config.root.glob(pattern)):
            f = _load_file(path, seen)
            acc.needs.extend(f.needs)
            acc.goals.extend(f.goals)
            acc.releases.extend(f.releases)
            acc.roles.extend(f.roles)
            acc.principles.extend(f.principles)
            acc.argument.extend(f.argument)
    _check_variants(acc.needs)
    _check_children(acc.needs)
    _check_contradicts(acc.needs)
    _check_ref(acc.needs, "goal", lambda n: n.goal, {g.id for g in acc.goals})
    _check_ref(acc.needs, "release", lambda n: n.release, {r.id for r in acc.releases})
    _check_ref(acc.needs, "role", lambda n: n.role, {p.id for p in acc.roles})
    _check_ref(
        acc.needs,
        "principle",
        lambda n: n.withdrawn.principle if n.withdrawn else None,
        {a.id for a in acc.principles},
    )
    _check_source_roles(acc.needs, acc.principles, {p.id for p in acc.roles})
    _check_argument(acc.argument)
    acc.needs = _symmetrize_contradicts(acc.needs)
    return Model(
        needs=tuple(acc.needs),
        goals=tuple(acc.goals),
        releases=tuple(acc.releases),
        roles=tuple(acc.roles),
        principles=tuple(acc.principles),
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


def _check_source_roles(needs: list[Need], principles: list[Principle], known: set[str]) -> None:
    """Every ``source.role`` that is set must name a declared role id (like ``need.role``, #52).

    Validated unconditionally, on a need's sources and a principle's alike: ``role`` is a new, opt-in
    field, so there is no migration reason to be lax — a dangling role on a source is a typo the
    author owns, surfaced at load, not a silent unknown that only shows as missing provenance later.
    """
    owners = [("need", n.id, n.sources) for n in needs] + [
        ("principle", a.id, a.sources) for a in principles
    ]
    for noun, oid, sources in owners:
        for i, s in enumerate(sources):
            if s.role is not None and s.role not in known:
                raise LoaderError(
                    f"{noun} {oid!r}: source[{i}] role {s.role!r} is not a known role id"
                )


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


def _check_contradicts(needs: list[Need]) -> None:
    """Every id in a need's ``contradicts`` must name a known need, and never the need itself."""
    known = {n.id for n in needs}
    for need in needs:
        for cid in need.contradicts:
            if cid == need.id:
                raise LoaderError(f"need {need.id!r}: contradicts itself")
            if cid not in known:
                raise LoaderError(f"need {need.id!r}: contradicts {cid!r} is not a known need id")


def _symmetrize_contradicts(needs: list[Need]) -> list[Need]:
    """Close the ``contradicts`` relation symmetrically: if A declares B, B contradicts A too.

    The file stays single-declaration — declare the edge once, so the comment-safe writer never has
    to touch two needs — but the loaded model carries the full symmetric neighbour set on both
    needs, so every reader (show, lint, the JSON payload) sees the one relation. Run after
    :func:`_check_contradicts`, so every target id is known.
    """
    edges: dict[str, set[str]] = {n.id: set(n.contradicts) for n in needs}
    for n in needs:
        for t in n.contradicts:
            edges[t].add(n.id)
    return [
        replace(n, contradicts=tuple(sorted(edges[n.id])))
        if edges[n.id] != set(n.contradicts)
        else n
        for n in needs
    ]


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
