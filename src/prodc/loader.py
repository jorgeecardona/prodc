"""Load need files (YAML) into :class:`~prodc.model.Need` objects.

A file-level ``who``/``client`` default every need in it; a need may override either.
IDs are globally unique (children reference ids across files), so a duplicate is a
:class:`LoaderError`. A flow (need with ``children``) must not also carry ``proofs``.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import yaml

from .config import Config
from .model import (
    Answer,
    Attestation,
    AttestationKind,
    Child,
    Decision,
    Goal,
    Model,
    Need,
    NeedPath,
    Outcome,
    Principle,
    Release,
    Role,
    Source,
    SourceKind,
    Verdict,
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
    # A bare ``date: 2026-09-20`` parses as a date, not a string. Accept it.
    if isinstance(value, datetime.date):
        return value.isoformat()
    return _as_str(value, where)


def _opt_importance(value: object, where: str) -> int | None:
    if value is None:
        return None
    # bool is a subclass of int. Reject it so ``importance: true`` is not read as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise LoaderError(f"{where}: expected a positive integer ordinal")
    if value < 1:
        raise LoaderError(f"{where}: expected a positive integer ordinal, got {value}")
    return value


def _as_bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise LoaderError(f"{where}: expected a boolean")
    return value


def _outcome(raw: object, where: str) -> Outcome | None:
    if raw is None:
        return None
    tbl = _as_mapping(raw, where)
    if "landed" not in tbl:
        raise LoaderError(f"{where}: an outcome needs 'landed: true' or 'landed: false'")
    date = _opt_str(tbl.get("date"), f"{where}.date")
    who = _opt_str(tbl.get("who"), f"{where}.who")
    if not date or not who:
        raise LoaderError(f"{where}: an outcome needs both 'who' and 'date'")
    return Outcome(
        landed=_as_bool(tbl["landed"], f"{where}.landed"),
        date=date,
        who=who,
        evidence=_opt_str(tbl.get("evidence"), f"{where}.evidence"),
    )


def _need_path(raw: object, where: str) -> NeedPath | None:
    if raw is None:
        return None
    tbl = _as_mapping(raw, where)
    max_clicks = tbl.get("max_clicks")
    if max_clicks is not None and (
        isinstance(max_clicks, bool) or not isinstance(max_clicks, int) or max_clicks < 0
    ):
        raise LoaderError(f"{where}.max_clicks: expected a whole number >= 0, got {max_clicks!r}")
    return NeedPath(
        start=_as_str(tbl.get("start"), f"{where}.start"),
        outcome=_as_str(tbl.get("outcome"), f"{where}.outcome"),
        max_clicks=max_clicks,
        proof=_opt_str(tbl.get("proof"), f"{where}.proof"),
    )


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
    verdict_name = _opt_str(tbl.get("verdict"), f"{where}.verdict")
    verdict: Verdict | None = None
    if verdict_name is not None:
        try:
            verdict = Verdict(verdict_name)
        except ValueError:
            verdicts = "|".join(v.value for v in Verdict)
            raise LoaderError(
                f"{where}.verdict: unknown verdict {verdict_name!r} ({verdicts})"
            ) from None
    return Attestation(
        who=who,
        date=date,
        kind=kind,
        verdict=verdict,
        comment=_opt_str(tbl.get("comment"), f"{where}.comment"),
    )


def _answer(raw: object, where: str) -> Answer | None:
    """Parse ``answer: yes|no|inconclusive`` into an :class:`Answer`, validated like other enums.

    The direction a settled research question resolved; absent on a product need. Same
    ``Enum(name) except ValueError`` pattern as ``SourceKind`` so an unknown value is
    a :class:`LoaderError` the author owns, not silent junk.

    YAML 1.1 reads a bare ``yes``/``no`` as a boolean, so ``answer: no`` arrives as ``False``.
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

    ``reason`` and ``date`` are required when the key is present. A decision against a need must
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
    of = _opt_str(tbl.get("of"), f"{where}.of")
    return Withdrawal(reason=reason, date=date, kind=kind, principle=principle, of=of)


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
        anchor=_opt_str(tbl.get("anchor"), f"{where}.anchor"),
    )


def _child(raw: object, where: str) -> Child:
    """Parse one flow edge: a bare id string, or a ``{id, step}`` mapping (#90).

    A bare ``US-050`` stays valid (``Child("US-050")`` with no step), so existing flows load
    unchanged; a mapping adds the optional ``step`` the edge plays in the journey.
    """
    if isinstance(raw, str):
        return Child(id=raw)
    tbl = _as_mapping(raw, where)
    return Child(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        step=_opt_str(tbl.get("step"), f"{where}.step"),
    )


def _need(
    raw: object,
    where: str,
    file_who: str | None,
    file_client: str | None,
    file_role: str | None = None,
    notices: list[str] | None = None,
) -> Need:
    tbl = _as_mapping(raw, where)
    if "label" in tbl and notices is not None:
        notices.append(_label_notice(where, tbl.get("who") or file_who, tbl["label"]))
    nid = _as_str(tbl.get("id"), f"{where}.id")
    text = _as_str(tbl.get("text"), f"{where}.text")
    description = _opt_str(tbl.get("description"), f"{where}.description")
    must = _as_bool(tbl["must"], f"{where}.must") if "must" in tbl else False
    who = _opt_str(tbl.get("who"), f"{where}.who") or file_who
    role = _opt_str(tbl.get("role"), f"{where}.role") or file_role
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
    path = _need_path(tbl.get("path"), f"{where}.path")
    outcome = _outcome(tbl.get("outcome"), f"{where}.outcome")
    if outcome is not None and answer is not None:
        raise LoaderError(
            f"{where} ({nid}): 'outcome' is for a delivered product need; a research question "
            "settles with 'answer', it has no delivery outcome"
        )

    sources = tuple(
        _source(s, f"{where}.sources[{i}]")
        for i, s in enumerate(_as_list(tbl.get("sources"), f"{where}.sources"))
    )
    proofs = tuple(
        _as_str(p, f"{where}.proofs[{i}]")
        for i, p in enumerate(_as_list(tbl.get("proofs"), f"{where}.proofs"))
    )
    children = tuple(
        _child(c, f"{where}.children[{i}]")
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
    tags = tuple(
        _as_str(t, f"{where}.tags[{i}]")
        for i, t in enumerate(_as_list(tbl.get("tags"), f"{where}.tags"))
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
        tags=tags,
        path=path,
        outcome=outcome,
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
        description=_opt_str(tbl.get("description"), f"{where}.description"),
        target=_opt_str(tbl.get("target"), f"{where}.target"),
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
    """Parse one ``principles:`` entry: a product commitment with its provenance and guards."""
    tbl = _as_mapping(raw, where)
    pid = _as_str(tbl.get("id"), f"{where}.id")
    proofs = tuple(
        _as_str(p, f"{where}.proofs[{i}]")
        for i, p in enumerate(_as_list(tbl.get("proofs"), f"{where}.proofs"))
    )
    for p in proofs:
        if p.split(":", 1)[0] == "need":
            raise LoaderError(
                f"principle {pid!r}: proof {p!r} is a need reference; a principle guards the "
                "code, it does not wait on a need to settle (that inverts the OST)"
            )
    return Principle(
        id=pid,
        text=_as_str(tbl.get("text"), f"{where}.text"),
        scope=_opt_str(tbl.get("scope"), f"{where}.scope") or "product",
        revised_at=_opt_str(tbl.get("revised_at"), f"{where}.revised_at"),
        sources=tuple(
            _source(s, f"{where}.sources[{i}]")
            for i, s in enumerate(_as_list(tbl.get("sources"), f"{where}.sources"))
        ),
        implemented_in=_opt_str(tbl.get("implemented_in"), f"{where}.implemented_in"),
        proofs=proofs,
    )


def _decision(raw: object, where: str) -> Decision:
    """Parse one ``decisions:`` entry: the solution chosen for a need, and what was rejected.

    ``needs`` is required and must be non-empty: a decision with no need it serves is engineering
    with no product reason, refused here rather than nagged at by a soft lint. ``withdrawn`` reuses
    the Need withdrawal (a superseded decision keeps its record).
    """
    tbl = _as_mapping(raw, where)
    needs = tuple(
        _as_str(n, f"{where}.needs[{i}]")
        for i, n in enumerate(_as_list(tbl.get("needs"), f"{where}.needs"))
    )
    if not needs:
        raise LoaderError(f"{where}: a decision must serve at least one need (needs: [...])")
    return Decision(
        id=_as_str(tbl.get("id"), f"{where}.id"),
        text=_as_str(tbl.get("text"), f"{where}.text"),
        needs=needs,
        alternatives=tuple(
            _as_str(a, f"{where}.alternatives[{i}]")
            for i, a in enumerate(_as_list(tbl.get("alternatives"), f"{where}.alternatives"))
        ),
        consequences=_opt_str(tbl.get("consequences"), f"{where}.consequences"),
        principles=tuple(
            _as_str(p, f"{where}.principles[{i}]")
            for i, p in enumerate(_as_list(tbl.get("principles"), f"{where}.principles"))
        ),
        decided_at=_opt_str(tbl.get("decided_at"), f"{where}.decided_at"),
        draft=_as_bool(tbl["draft"], f"{where}.draft") if "draft" in tbl else False,
        withdrawn=_withdrawal(tbl.get("withdrawn"), f"{where}.withdrawn"),
        awaits=tuple(
            _as_str(a, f"{where}.awaits[{i}]")
            for i, a in enumerate(_as_list(tbl.get("awaits"), f"{where}.awaits"))
        ),
    )


@dataclass
class _Loaded:
    """One file's nouns, accumulated across the glob into the final :class:`Model`."""

    needs: list[Need] = field(default_factory=list[Need])
    goals: list[Goal] = field(default_factory=list[Goal])
    releases: list[Release] = field(default_factory=list[Release])
    roles: list[Role] = field(default_factory=list[Role])
    principles: list[Principle] = field(default_factory=list[Principle])
    decisions: list[Decision] = field(default_factory=list[Decision])
    notices: list[str] = field(default_factory=list[str])


def _label_notice(where: str, who: object, label: object) -> str:
    """The 0.3 ``label:`` tombstone as a notice that shows the exact 0.4 YAML to write (#96).

    A notice, not a :class:`LoaderError`: a load failure would also block every write, so the
    board could not be fixed with ``prodc add role``. ``lint`` still exits 1 on it. The value
    stays in the file (the writer never touches it); only the model ignores it.
    """
    rid = who if isinstance(who, str) and who else "<role-id>"
    text = str(label)[:80]
    return (
        f"{where}: 'label' was removed in 0.4 and is ignored. Write it as a role:\n"
        f"    roles:\n      - id: {rid}\n        text: {text}\n"
        f"  then bind the needs with `role: {rid}` (per need, or once at the top of the file)"
        " and delete `label:`.\n"
        f'  Or: prodc add role {rid} --text "{text}" --file <file>'
    )


def yaml_error_message(where: str, text: str, exc: yaml.YAMLError) -> str:
    """Turn a raw PyYAML parse error into a prodc message naming the file, line and nearest need (#84).

    PyYAML points at ``"<unicode string>", line N`` with no file or need id; on a 200-line board that
    leaves the author hunting by hand. We name the file and line, scan back to the nearest ``id:`` so
    the offending need is identified, and (for the common ``": "``-in-prose case) spells out the fix.
    """
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or "invalid YAML"
    if mark is None:
        return f"{where}: invalid YAML: {exc}"
    lines = text.splitlines()
    loc = f"{where}: line {mark.line + 1}"
    nid: str | None = None
    for j in range(min(mark.line, len(lines) - 1), -1, -1):
        m = re.match(r"^\s*-?\s*id:\s*(\S+)", lines[j])
        if m:
            nid = m.group(1).strip("\"'")
            break
    if nid is not None:
        loc += f" (need {nid!r})"
    msg = f"{loc}: {problem}"
    if "mapping values are not allowed here" in problem:
        msg += (
            " (a ': ' in an unquoted claim/text reads as a nested mapping; "
            "quote the value in single quotes or rephrase)"
        )
    return msg


def _load_file(path: Path, seen: dict[str, dict[str, Path]]) -> _Loaded:
    """Parse one prodc file for every noun list it carries (``needs:``/``goals:``/``principles:``/…)."""
    where = path.name
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LoaderError(yaml_error_message(where, text, exc)) from exc
    out = _Loaded()
    if doc is None:
        return out
    tbl = _as_mapping(doc, where)
    file_who = _opt_str(tbl.get("who"), f"{where}.who")
    file_client = _opt_str(tbl.get("client"), f"{where}.client")
    # A file may name one role for all its needs, like `who`/`client` (#96); validated at load.
    file_role = _opt_str(tbl.get("role"), f"{where}.role")
    if "label" in tbl:
        out.notices.append(_label_notice(where, file_who, tbl["label"]))

    def _unique(kind: str, nid: str) -> None:
        prior = seen[kind].get(nid)
        if prior is not None:
            raise LoaderError(f"duplicate {kind} id {nid!r} in {where} and {prior.name}")
        seen[kind][nid] = path

    for i, raw in enumerate(_as_list(tbl.get("needs"), f"{where}.needs")):
        need = _need(raw, f"{where}.needs[{i}]", file_who, file_client, file_role, out.notices)
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
    for i, raw in enumerate(_as_list(tbl.get("decisions"), f"{where}.decisions")):
        decision = _decision(raw, f"{where}.decisions[{i}]")
        _unique("decision", decision.id)
        out.decisions.append(decision)
    if "argument" in tbl:
        # Tombstone (0.4): the GSN ``argument`` graph was removed. A notice, not an error, so the
        # writer can still edit the board while the author migrates (#96). Removed for good in 0.5.
        out.notices.append(
            f"{where}: 'argument:' was removed in 0.4 and is ignored. State the warrant as "
            "need.claim, prove it with proofs, and review it with `prodc attest`"
        )
    return out


def load(config: Config) -> Model:
    """Read every prodc file once into a :class:`~prodc.model.Model`, then validate cross-refs.

    One loader for every noun: ids are unique within their kind, and each string reference
    (``variant_of``, ``children``, ``goal``, ``release``, ``role``, a withdrawal's ``principle``) is
    checked here as a hard error. A dangling reference to something declared in these files is a
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
        "decision": {},
    }
    for path in config.prodc_files():
        f = _load_file(path, seen)
        acc.needs.extend(f.needs)
        acc.goals.extend(f.goals)
        acc.releases.extend(f.releases)
        acc.roles.extend(f.roles)
        acc.principles.extend(f.principles)
        acc.decisions.extend(f.decisions)
        acc.notices.extend(f.notices)
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
    _check_withdrawal_of(acc.needs)
    _check_source_roles(acc.needs, acc.principles, {p.id for p in acc.roles})
    _check_decisions(acc.decisions, {n.id for n in acc.needs}, {p.id for p in acc.principles})
    _check_principle_scopes(acc.principles, config.principle_scopes)
    _check_flow_steps(acc.needs, config.flow_steps)
    acc.needs = _symmetrize_contradicts(acc.needs)
    return Model(
        needs=tuple(acc.needs),
        goals=tuple(acc.goals),
        releases=tuple(acc.releases),
        roles=tuple(acc.roles),
        principles=tuple(acc.principles),
        decisions=tuple(acc.decisions),
        notices=tuple(acc.notices),
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
    field, so there is no migration reason to be lax. A dangling role on a source is a typo the
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


def _check_children(needs: list[Need]) -> None:
    """Every id in a need's ``children`` must name a known need."""
    known = {n.id for n in needs}
    for need in needs:
        for c in need.children:
            if c.id not in known:
                raise LoaderError(f"need {need.id!r}: child {c.id!r} is not a known need id")


def _check_principle_scopes(principles: list[Principle], allowed: tuple[str, ...]) -> None:
    """Every principle's ``scope`` must be one declared in ``[principles].scopes`` (#88)."""
    allowed_set = set(allowed)
    for p in principles:
        if p.scope not in allowed_set:
            raise LoaderError(
                f"principle {p.id!r}: scope {p.scope!r} is not declared in "
                f"[principles].scopes ({', '.join(allowed)})"
            )


def _check_flow_steps(needs: list[Need], allowed: tuple[str, ...]) -> None:
    """Every flow edge's ``step`` must be one declared in ``[flows].steps`` (#90).

    Membership is integrity, not judgment. A mis-spelled step (``conlcude``) is a typo, the
    same severity as an undeclared principle scope, so it is a hard load error. Because the
    writer re-loads and reverts on ``LoaderError``, this also refuses to *write* a bad step.
    Skipped entirely when no vocabulary is declared: a bare step stays free text, as it was
    before this. Order and completeness are the lint's job, not the loader's.
    """
    if not allowed:
        return
    allowed_set = set(allowed)
    for need in needs:
        for c in need.children:
            if c.step is not None and c.step not in allowed_set:
                raise LoaderError(
                    f"need {need.id!r}: child {c.id!r} step {c.step!r} is not declared in "
                    f"[flows].steps ({', '.join(allowed)})"
                )


def _check_withdrawal_of(needs: list[Need]) -> None:
    """A withdrawal's ``of`` must name a known need (never itself); required when kind is duplicate.

    ``of`` is the need this one duplicates. A ``duplicate`` withdrawal that names no target is a
    reason string, not data the board can roll up, so it is refused at load (0.4).
    """
    known = {n.id for n in needs}
    for need in needs:
        w = need.withdrawn
        if w is None:
            continue
        if w.kind is WithdrawalKind.DUPLICATE and w.of is None:
            raise LoaderError(
                f"need {need.id!r}: a duplicate withdrawal must name 'of' (the original)"
            )
        if w.of is not None:
            if w.of == need.id:
                raise LoaderError(f"need {need.id!r}: withdrawn 'of' cannot be itself")
            if w.of not in known:
                raise LoaderError(
                    f"need {need.id!r}: withdrawn 'of' {w.of!r} is not a known need id"
                )


def _check_decisions(
    decisions: list[Decision], known_needs: set[str], known_principles: set[str]
) -> None:
    """Every ``needs`` / ``principles`` id on a decision must name a known need / principle.

    ``needs`` is already guaranteed non-empty by :func:`_decision`; here each id is checked to
    exist, the same hard-error treatment the other cross-references get. A superseded decision's
    ``withdrawn.principle`` is checked too, so a stale citation cannot hide on a retired record.
    """
    for d in decisions:
        for nid in d.needs:
            if nid not in known_needs:
                raise LoaderError(f"decision {d.id!r}: needs {nid!r} is not a known need id")
        for pid in d.principles:
            if pid not in known_principles:
                raise LoaderError(
                    f"decision {d.id!r}: principle {pid!r} is not a known principle id"
                )
        if d.withdrawn and d.withdrawn.principle and d.withdrawn.principle not in known_principles:
            raise LoaderError(
                f"decision {d.id!r}: withdrawn principle {d.withdrawn.principle!r} "
                "is not a known principle id"
            )
        for ref in d.awaits:
            nid, sep, direction = ref.partition("@")
            if nid not in known_needs:
                raise LoaderError(f"decision {d.id!r}: awaits {nid!r} is not a known need id")
            if sep and direction not in {a.value for a in Answer}:
                answers = "|".join(a.value for a in Answer)
                raise LoaderError(
                    f"decision {d.id!r}: awaits {ref!r} has unknown answer {direction!r} ({answers})"
                )
            if nid in d.needs:
                raise LoaderError(
                    f"decision {d.id!r}: {nid!r} is in both needs (serves) and awaits (waits on)"
                )


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

    The file stays single-declaration: declare the edge once, so the comment-safe writer never has
    to touch two needs. The loaded model carries the full symmetric neighbour set on both
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
