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


def add_issue_parser(ip: argparse.ArgumentParser) -> None:
    """Fill ``prodc issue {board,show,file,update,close,check,reindex}``."""

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

    sh = sub("show", "print one issue file")
    sh.add_argument("name", help="a filename or an unambiguous part of the slug")
    sh.set_defaults(func=cmd_issue_show)

    fi = sub("file", "file a new issue")
    fi.add_argument("--title", required=True)
    fi.add_argument("--area", required=True)
    fi.add_argument("--body", required=True, help="markdown body ('-' reads stdin)")
    fi.add_argument("--blocked-by", action="append", default=[], metavar="SLUG")
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
    body = sys.stdin.read() if args.body == "-" else args.body
    path = store.file_issue(
        _folder(),
        title=args.title,
        area=args.area,
        body=body,
        blocked_by=tuple(args.blocked_by),
        extra=_fields(args.field),
    )
    _emit(args.json, {"file": path.name}, f"filed {path.name}")
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
    _emit(args.json, {**_row(updated), "unblocked": unblocked}, text)
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
