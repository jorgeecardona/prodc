"""``prodc mcp``: run the MCP server, or register it in an MCP client's project config."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import cast

from ..mcp_config import (
    CLIENTS,
    DEFAULT_COMMAND,
    ClientName,
    McpConfigError,
    apply,
    install,
    manual_instructions,
    uninstall,
)


def add_mcp_parser(mp: argparse.ArgumentParser) -> None:
    """Fill ``prodc mcp {serve,install,uninstall}``. A bare ``prodc mcp`` prints help, exit 2."""

    def bare(_args: argparse.Namespace) -> int:
        mp.print_help(sys.stderr)
        return 2

    mp.set_defaults(func=bare)
    msub = mp.add_subparsers(dest="mcp_command")

    sv = msub.add_parser("serve", help="run the MCP server on stdio (the client starts this)")
    sv.set_defaults(func=cmd_mcp_serve)

    for name, func, verb in (
        ("install", cmd_mcp_install, "add the prodc server to"),
        ("uninstall", cmd_mcp_uninstall, "remove the prodc server from"),
    ):
        p = msub.add_parser(name, help=f"{verb} an MCP client's project config")
        p.add_argument(
            "--client",
            choices=["claude", "cursor", "vscode", "codex"],
            default="claude",
            help="which client's config (default: claude, .mcp.json)",
        )
        p.add_argument(
            "--scope",
            choices=["project", "user"],
            default="project",
            help="project writes the repo's config file; user prints the client's own command",
        )
        p.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "install":
            p.add_argument(
                "--command",
                default=None,
                metavar="CMD",
                help='the server command to write (default: uvx --from "prodc[mcp]" prodc mcp '
                "serve). Use 'uv run prodc mcp serve' when the project pins prodc",
            )
        p.set_defaults(func=func)


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Run the stdio server. Needs the ``mcp`` extra."""
    try:
        from ..mcp_server import serve
    except ImportError:
        print("prodc: install prodc[mcp] to run the MCP server", file=sys.stderr)
        return 2
    serve(args.chdir)
    return 0


def _report(edit_path: Path, old: str, new: str, dry_run: bool, as_json: bool) -> None:
    changed = old != new
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{edit_path}",
            tofile=f"b/{edit_path}",
        )
    )
    if as_json:
        print(
            json.dumps(
                {"file": str(edit_path), "changed": changed, "dry_run": dry_run, "diff": diff},
                indent=2,
            )
        )
        return
    if not changed:
        print(f"{edit_path}: unchanged")
        return
    print(f"{'would edit' if dry_run else 'edited'} {edit_path}")
    print(diff, end="")


def _run(args: argparse.Namespace, installing: bool) -> int:
    client = cast(ClientName, args.client)
    command: str = getattr(args, "command", None) or DEFAULT_COMMAND
    if client not in CLIENTS or args.scope == "user":
        # prodc does not write user-scope files (~/.claude.json is live client state) or TOML.
        if installing:
            print(manual_instructions(client, args.scope, command), end="")
        else:
            print(f"remove the 'prodc' server with {client}'s own MCP command or config")
        return 0
    root = Path.cwd()
    try:
        edit = install(root, client, command) if installing else uninstall(root, client)
    except McpConfigError as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    if not args.dry_run:
        apply(edit)
    _report(edit.path.relative_to(root), edit.old_text, edit.new_text, args.dry_run, args.json)
    return 0


def cmd_mcp_install(args: argparse.Namespace) -> int:
    """Add or update the ``prodc`` entry in the client's project config."""
    return _run(args, installing=True)


def cmd_mcp_uninstall(args: argparse.Namespace) -> int:
    """Remove the ``prodc`` entry from the client's project config."""
    return _run(args, installing=False)
