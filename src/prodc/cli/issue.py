"""``prodc issue``: read and write the issue register (``docs/issues/*.md``).

The store is :mod:`prodc.issue_store`. Claiming an issue is not here: a claim is a lease between
running agents, which cabildo's bus owns. ``update --status in-progress`` records the state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .. import issue_store as store
from ..config import Config, ConfigError
from ..loader import LoaderError, load
from ..model import NeedState
from ..status import resolve as resolve_needs
from .render import render_issues
from .serialize import issue_payload


def add_issue_parser(ip: argparse.ArgumentParser) -> None:
    """Fill ``prodc issue {board,list,show,file,update,close,check,reindex}``."""

    def bare(_args: argparse.Namespace) -> int:
        ip.print_help(sys.stderr)
        return 2

    ip.set_defaults(func=bare)
    isub = ip.add_subparsers(dest="issue_command")

    def sub(name: str, help: str) -> argparse.ArgumentParser:
        p = isub.add_parser(name, help=help)
        p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    bd = sub("board", "what is ready to pick up, and what the rest waits on")
    bd.add_argument("--status", default=None, help="flat list filtered by status")
    bd.add_argument("--area", default=None, help="flat list filtered by area")
    bd.add_argument("--owner", default=None, help="flat list filtered by owner ('none': unowned)")
    bd.set_defaults(func=cmd_issue_board)

    ls = sub("list", "every issue with the needs it serves and their state")
    ls.add_argument("--need", default=None, metavar="ID", help="only issues serving this need")
    ls.add_argument("--config", default=None, help="path to prodc.toml (default: found upward)")
    ls.set_defaults(func=cmd_issue_list)

    sh = sub("show", "print one issue file")
    sh.add_argument("name", help="a filename or an unambiguous part of the slug")
    sh.set_defaults(func=cmd_issue_show)

    fi = sub("file", "file a new issue")
    fi.add_argument("--title", required=True)
    fi.add_argument("--area", required=True)
    fi.add_argument("--body", required=True, help="markdown body ('-' reads stdin)")
    fi.add_argument("--blocked-by", action="append", default=[], metavar="SLUG")
    fi.add_argument(
        "--need",
        action="append",
        default=[],
        metavar="ID",
        help="a need this issue serves; repeat for more. An unknown id is refused",
    )
    fi.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a field the folder's config.toml declares; repeat KEY for a list",
    )
    fi.set_defaults(func=cmd_issue_file)

    up = sub("update", "change an issue's front matter; only what you pass changes")
    up.add_argument("name")
    up.add_argument("--title", default=None)
    up.add_argument("--status", choices=[s.value for s in store.Status], default=None)
    up.add_argument("--area", default=None)
    up.add_argument("--owner", default=None, help="who is doing it ('none' clears it)")
    up.add_argument("--blocked-by", action="append", default=None, metavar="SLUG")
    up.add_argument("--clear-blocked-by", action="store_true")
    up.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    up.set_defaults(func=cmd_issue_update)

    cl = sub("close", "mark an issue done; the file stays, carrying fixed_in")
    cl.add_argument("name")
    cl.add_argument("--fixed-in", required=True, metavar="SHA", help="the sha on the mainline")
    cl.set_defaults(func=cmd_issue_close)

    ck = sub("check", "grade the folder against its config.toml (exit 1 on problems)")
    ck.set_defaults(func=cmd_issue_check)

    ri = sub("reindex", "rewrite the README index table")
    ri.set_defaults(func=cmd_issue_reindex)


def _folder() -> Path:
    found = store.find_folder(Path.cwd())
    if found is None:
        raise store.IssueFormatError(f"no docs/issues/ at or above {Path.cwd()}")
    return found


def _board_config() -> Config | None:
    """The ``prodc.toml`` at or above the working directory, up to the repo root."""
    here = Path.cwd().resolve()
    for base in (here, *here.parents):
        if (base / "prodc.toml").is_file():
            try:
                return Config.load(base / "prodc.toml")
            except ConfigError as exc:
                raise store.IssueFormatError(str(exc)) from exc
        if (base / ".git").exists():
            break
    return None


def _need_ids() -> set[str]:
    """Every need id on the board; refuses when there is no board to check against."""
    cfg = _board_config()
    if cfg is None:
        raise store.IssueFormatError("--need needs a prodc.toml at or above this directory")
    try:
        return {n.id for n in load(cfg).needs}
    except LoaderError as exc:
        raise store.IssueFormatError(str(exc)) from exc


def _need_states(ids: tuple[str, ...]) -> dict[str, NeedState | None]:
    """The state of each named need; None for an id the board does not have."""
    cfg = _board_config() if ids else None
    if cfg is None:
        return {}
    try:
        model = load(cfg)
    except LoaderError as exc:
        raise store.IssueFormatError(str(exc)) from exc
    results = {
        r.need.id: r.state
        for r in resolve_needs(list(model.needs), cfg.adapters, cfg.source_adapters)
    }
    return {n: results.get(n) for n in ids}


def _fields(pairs: list[str]) -> dict[str, str | tuple[str, ...]]:
    """``KEY=VALUE`` pairs to front-matter fields; a repeated key becomes a list."""
    out: dict[str, list[str]] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise store.IssueFormatError(f"--field wants KEY=VALUE, got {pair!r}")
        out.setdefault(key, []).append(value)
    return {k: v[0] if len(v) == 1 else tuple(v) for k, v in out.items()}


def _row(issue: store.Issue) -> dict[str, Any]:
    return {
        "slug": issue.slug,
        "file": issue.path.name,
        "title": issue.title,
        "status": issue.status.value,
        "area": issue.area,
        "owner": issue.owner,
        "blocked_by": list(issue.blocked_by),
        "fixed_in": issue.fixed_in,
        "needs": list(issue.needs),
        "sources": list(issue.sources),
        "fields": {k: list(v) if isinstance(v, tuple) else v for k, v in issue.extra.items()},
    }


def _line(issue: store.Issue) -> str:
    owner = f" @{issue.owner}" if issue.owner else ""
    return f"  {issue.slug}  [{issue.status.value}{owner}] {issue.area}: {issue.title}"


def _emit(as_json: bool, data: object, text: str) -> None:
    print(json.dumps(data, indent=2) if as_json else text)


def _guard(func: Any) -> Any:
    def run(args: argparse.Namespace) -> int:
        try:
            return int(func(args))
        except (store.IssueFormatError, OSError) as exc:
            print(f"prodc: {exc}", file=sys.stderr)
            return 2

    return run


@_guard
def cmd_issue_board(args: argparse.Namespace) -> int:
    """Ready, waiting, done; or a flat list when a filter is given."""
    folder = _folder()
    if args.status or args.area or args.owner:
        found, _ = store.load_all(folder)
        rows = [
            i
            for i in found
            if (args.status == "done" or i.open)
            and (not args.status or i.status == args.status)
            and (not args.area or i.area == args.area)
            and (not args.owner or (i.owner or "none") == args.owner)
        ]
        _emit(args.json, [_row(i) for i in rows], "\n".join(_line(i) for i in rows) or "(none)")
        return 0
    b = store.board(folder)
    data = {
        "ready": [_row(i) for i in b.ready],
        "waiting": [{**_row(w.issue), "reason": w.reason} for w in b.waiting],
        "done": b.done,
    }
    lines = [f"READY ({len(b.ready)}):", *(_line(i) for i in b.ready)]
    lines += [f"WAITING ({len(b.waiting)}):", *(f"  {w.issue.slug}: {w.reason}" for w in b.waiting)]
    lines.append(f"{b.done} done")
    _emit(args.json, data, "\n".join(lines))
    return 0


def cmd_issue_list(args: argparse.Namespace) -> int:
    """List the issues with the state of each need they serve (#36).

    The issues come from ``[prodc].issues`` globs when set, else from the register
    :func:`prodc.issue_store.find_folder` finds. Exit 2 when there is no board or no register.
    """
    try:
        cfg = Config.load(Path(args.config)) if args.config else _board_config()
        if cfg is None:
            raise store.IssueFormatError("no prodc.toml at or above this directory")
        model = load(cfg)
    except (ConfigError, LoaderError, store.IssueFormatError, OSError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    if not cfg.issue_globs and store.find_folder(cfg.root) is None:
        print(
            "prodc: no issue register: set [prodc].issues (for example docs/issues/*.md) "
            "or create docs/issues/",
            file=sys.stderr,
        )
        return 2
    results = resolve_needs(list(model.needs), cfg.adapters, cfg.source_adapters)
    by_state = {r.need.id: r.state.value.upper() for r in results}
    issues = [i for i in model.issues if args.need is None or args.need in i.needs]
    if args.json:
        rows = [
            {**issue_payload(i), "need_states": {n: by_state.get(n, "UNKNOWN") for n in i.needs}}
            for i in issues
        ]
        print(json.dumps(rows, indent=2))
    else:
        print(render_issues(issues, by_state))
    return 0


@_guard
def cmd_issue_show(args: argparse.Namespace) -> int:
    """Print one issue file."""
    path = store.resolve(_folder(), args.name)
    text = path.read_text(encoding="utf-8")
    _emit(args.json, {"file": path.name, "text": text}, text.rstrip("\n"))
    return 0


@_guard
def cmd_issue_file(args: argparse.Namespace) -> int:
    """File a new issue and print its filename."""
    needs = tuple(dict.fromkeys(args.need))
    if needs:
        unknown = [n for n in needs if n not in _need_ids()]
        if unknown:
            raise store.IssueFormatError(f"no such need: {', '.join(unknown)}")
    body = sys.stdin.read() if args.body == "-" else args.body
    path = store.file_issue(
        _folder(),
        title=args.title,
        area=args.area,
        body=body,
        blocked_by=tuple(args.blocked_by),
        extra=_fields(args.field),
        needs=needs,
    )
    warnings = [] if needs else ["issue serves no need: pass --need ID, or question why it exists"]
    for w in warnings:
        print(f"prodc: warning: {w}", file=sys.stderr)
    _emit(
        args.json,
        {"file": path.name, "needs": list(needs), "warnings": warnings},
        f"filed {path.name}",
    )
    return 0


@_guard
def cmd_issue_update(args: argparse.Namespace) -> int:
    """Change only the front-matter keys passed."""
    changes: dict[str, Any] = {}
    if args.title:
        changes["title"] = args.title
    if args.status:
        changes["status"] = store.Status(args.status)
    if args.area:
        changes["area"] = args.area
    if args.owner:
        changes["owner"] = None if args.owner == "none" else args.owner
    if args.clear_blocked_by:
        changes["blocked_by"] = ()
    elif args.blocked_by is not None:
        changes["blocked_by"] = tuple(args.blocked_by)
    if args.field:
        changes["extra"] = _fields(args.field)
    if not changes:
        print("prodc: nothing to change", file=sys.stderr)
        return 2
    updated = store.update(_folder(), args.name, **changes)
    _emit(args.json, _row(updated), f"updated {updated.path.name}\n{_line(updated)}")
    return 0


@_guard
def cmd_issue_close(args: argparse.Namespace) -> int:
    """Mark done with ``fixed_in``; report what it unblocked."""
    folder = _folder()
    updated = store.close(folder, args.name, fixed_in=args.fixed_in)
    unblocked = [i.slug for i in store.newly_ready(folder, updated.slug)]
    text = f"closed {updated.path.name} (fixed_in {updated.fixed_in})"
    if unblocked:
        text += "; unblocked: " + ", ".join(unblocked)
    states = _need_states(updated.needs)
    shown = {n: (s.value.upper() if s else "UNKNOWN") for n, s in states.items()}
    text += "".join(f"\n  serves {n}: {state}" for n, state in shown.items())
    warnings = [
        f"closed but unproven: {n} is {shown[n]}"
        for n, s in states.items()
        if s is not NeedState.DELIVERED
    ]
    for w in warnings:
        print(f"prodc: warning: {w}", file=sys.stderr)
    data = {**_row(updated), "unblocked": unblocked, "need_states": shown, "warnings": warnings}
    _emit(args.json, data, text)
    return 0


@_guard
def cmd_issue_check(args: argparse.Namespace) -> int:
    """Grade the folder; exit 1 when it has problems."""
    folder = _folder()
    problems = store.check(folder)
    data = [{"file": p.path.name, "problem": p.message} for p in problems]
    _emit(args.json, data, "\n".join(str(p) for p in problems) or f"{folder}: clean")
    return 1 if problems else 0


@_guard
def cmd_issue_reindex(args: argparse.Namespace) -> int:
    """Rewrite the README index table."""
    folder = _folder()
    store.reindex(folder)
    _emit(args.json, {"folder": str(folder)}, f"reindexed {folder}")
    return 0
