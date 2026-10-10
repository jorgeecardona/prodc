"""Lifecycle callbacks: run a command when a need changes state (#71).

The signal that a need is done already lives in prodc — its proof resolving to DELIVERED. This
lets a team act on that event: when a need's state changes, prodc runs a command from the project
config with the affected need (and board context) as JSON on **stdin**. Same trust model as the
command hook (#70): the command comes only from the config, never from need data; the need data is
piped as data, never executed.

A state change needs the *previous* state, which prodc (stateless per run — it re-reads every file)
does not otherwise keep. So a small ledger (``state_file``) records each need's last-seen state;
`prodc sync` resolves the board, diffs it against the ledger, fires the matching callbacks, and
writes the ledger forward. The first run records a baseline and fires nothing (everything would
look new). A callback that fails is reported, never silent, and its need is *not* advanced in the
ledger, so the next sync retries it.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .model import Need

#: The only event implemented today; others from #71 (capture/report/pre_gate) are follow-ups.
STATE_CHANGE = "state_change"

#: Runs an argv (no shell) with a JSON payload on stdin, returning (ok, short reason). Injected in
#: tests so no process spawns; :func:`_invoke` is the real subprocess default.
Invoker = Callable[[tuple[str, ...], str, Path, float], tuple[bool, str]]


@dataclass(frozen=True)
class Callback:
    """One configured lifecycle callback: an event, a command, and optional transition filters."""

    event: str
    command: tuple[str, ...]
    timeout: float = 30.0
    on_from: frozenset[str] = frozenset()  # empty = any source state
    on_to: frozenset[str] = frozenset()  # empty = any target state

    def matches(self, frm: str, to: str) -> bool:
        """Whether this callback fires for a transition ``frm -> to``."""
        if self.on_from and frm not in self.on_from:
            return False
        return not (self.on_to and to not in self.on_to)


@dataclass(frozen=True)
class Transition:
    """A need whose resolved state changed since the last sync."""

    need_id: str
    frm: str
    to: str


@dataclass(frozen=True)
class Fired:
    """The outcome of running one callback for one transition."""

    transition: Transition
    command: tuple[str, ...]
    ok: bool
    detail: str


def read_ledger(path: Path) -> dict[str, str] | None:
    """The last-seen state per need id, or ``None`` when no ledger exists yet (first run)."""
    if not path.exists():
        return None
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    return {str(k): str(v) for k, v in cast("dict[object, object]", raw).items()}


def write_ledger(path: Path, states: dict[str, str]) -> None:
    """Persist the current state per need id (keys sorted for a stable, reviewable file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({k: states[k] for k in sorted(states)}, indent=2) + "\n"
    path.write_text(body, encoding="utf-8")


def transitions(ledger: dict[str, str], current: dict[str, str]) -> list[Transition]:
    """Needs whose state differs from the ledger.

    A need absent from the ledger is *new*, not a transition — it is baselined silently and never
    fired on, so adding a need does not masquerade as a state change.
    """
    out = [
        Transition(nid, ledger[nid], state)
        for nid, state in current.items()
        if nid in ledger and ledger[nid] != state
    ]
    out.sort(key=lambda t: t.need_id)
    return out


def fire(
    trans: list[Transition],
    callbacks: list[Callback],
    *,
    context: dict[str, Need],
    board: dict[str, object],
    cwd: Path,
    invoke: Invoker | None = None,
) -> list[Fired]:
    """Run every callback matching each transition, piping the need + board as JSON on stdin.

    ``context`` maps a need id to its :class:`~prodc.model.Need` (for the payload). Returns one
    :class:`Fired` per (transition, matching callback) actually run, in transition then config
    order.
    """
    run = invoke or _invoke
    state_cbs = [c for c in callbacks if c.event == STATE_CHANGE]
    out: list[Fired] = []
    for t in trans:
        need = context.get(t.need_id)
        payload = json.dumps(
            {
                "event": STATE_CHANGE,
                "from": t.frm,
                "to": t.to,
                "need": _need_json(need, t.to) if need else {"id": t.need_id, "state": t.to},
                "board": board,
            },
            ensure_ascii=False,
        )
        for cb in state_cbs:
            if cb.matches(t.frm, t.to):
                ok, detail = run(cb.command, payload, cwd, cb.timeout)
                out.append(Fired(t, cb.command, ok, detail))
    return out


def advance_ledger(
    current: dict[str, str], ledger: dict[str, str], fired: list[Fired]
) -> dict[str, str]:
    """The ledger to persist: every need at its current state, except a need whose callback failed
    — that one keeps its prior state so the next sync retries it."""
    failed = {f.transition.need_id for f in fired if not f.ok}
    new = dict(current)
    for nid in failed:
        if nid in ledger:  # do not advance a need whose callback failed; retry next sync
            new[nid] = ledger[nid]
    return new


def _invoke(command: tuple[str, ...], payload: str, cwd: Path, timeout: float) -> tuple[bool, str]:
    """Run ``command`` (no shell) with ``payload`` on stdin; report ok and a short reason.

    Never raises: a spawn failure, a timeout, or a non-zero exit all come back as ``ok=False`` with
    a reason, so a broken callback is reported, never silent and never fatal to the sync itself.
    """
    try:
        proc = subprocess.run(
            list(command),
            input=payload,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:g}s"
    except OSError as exc:
        return False, f"could not run ({exc})"
    if proc.returncode == 0:
        return True, "ok"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, f"exit {proc.returncode}" + (f": {tail[-1]}" if tail else "")


def _need_json(need: Need, state: str) -> dict[str, object]:
    strongest = need.strongest_kind
    return {
        "id": need.id,
        "text": need.text,
        "state": state,
        "who": need.who,
        "client": need.client,
        "must": need.must,
        "goal": need.goal,
        "release": need.release,
        "warrant": strongest.value if strongest is not None else "opinion",
    }
