"""The prodc MCP server: prodc's commands as MCP tools for any MCP client.

Every tool runs the ``prodc`` CLI with ``--json`` in a subprocess and returns its result. The
CLI stays the one implementation. A subprocess also keeps the server's stdout clean: the stdio
transport breaks on any byte that is not a protocol message, and the command handlers print.

Only the tools an agent may run are exposed. Commands that record a person's judgement
(``accept``, ``outcome``, ``attest``), product decisions (``withdraw``, ``revise``, ``add
principle``), and ``sync`` (it runs configured shell commands) stay on the CLI. ``capture``
here refuses the ``primary`` kind: a primary source is a person's own words, added by hand.

Needs the ``mcp`` extra: ``pip install 'prodc[mcp]'``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__

INSTRUCTIONS = """\
prodc keeps product needs as YAML in the repo. Each need has sources (evidence) and proofs (tests).
Rules:
- A need with no external evidence is an opinion. "Done" means a passing test proof.
- Never record a primary source. Primary is a real person's own words; a person adds it by
  editing the YAML. capture accepts only secondary and assumption.
- Do not invent sources. Capture what was observed, with who and when.
- Every write returns a diff and sha_before/sha_after. To chain writes safely, pass the last
  sha_after as expect_sha.
- Exit code 1 means a gate failed (for example lint found errors). It is a result, not a crash.
Run the `playbook` prompt for the full guide.
"""

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def project_root(explicit: str | None = None) -> Path:
    """The project the server acts on: ``-C DIR``, else ``CLAUDE_PROJECT_DIR``, else the cwd."""
    return Path(explicit or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def run_cli(root: Path, argv: list[str]) -> dict[str, Any]:
    """Run ``prodc -C root <argv> --json`` and return ``{exit_code, data, notices}``.

    ``data`` is the parsed JSON (or the raw text when the command printed none). ``notices``
    is stderr: deprecations and errors land there.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "prodc.cli", "-C", str(root), *argv, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data: Any = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        data = proc.stdout
    return {"exit_code": proc.returncode, "data": data, "notices": proc.stderr.strip()}


def _flag(argv: list[str], name: str, value: object) -> None:
    """Append ``--name value`` (or a bare ``--name`` for True) when the value is set."""
    if value is None or value is False:
        return
    argv.append(f"--{name}")
    if value is not True:
        argv.append(str(value))


def _write_flags(argv: list[str], dry_run: bool, expect_sha: str | None) -> list[str]:
    _flag(argv, "dry-run", dry_run)
    _flag(argv, "expect-sha", expect_sha)
    return argv


def build_server(root: Path) -> MCPServer:
    """Return the prodc MCP server bound to one project root."""
    server = MCPServer("prodc", version=__version__, instructions=INSTRUCTIONS)

    def call(argv: list[str]) -> dict[str, Any]:
        result = run_cli(root, argv)
        if result["exit_code"] == 2:
            raise RuntimeError(result["notices"] or "prodc failed (exit 2)")
        return result

    # -- read tools -------------------------------------------------------------------------

    @server.tool(annotations=_READ)
    def status(
        client: str | None = None,
        goal: str | None = None,
        tag: str | None = None,
        only_must: bool = False,
        include_drafts: bool = False,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        """The needs board: each need's state (DELIVERED, HOLE, BROKEN, ...) and the coverage."""
        argv = ["status"]
        _flag(argv, "client", client)
        _flag(argv, "goal", goal)
        _flag(argv, "tag", tag)
        _flag(argv, "only-must", only_must)
        _flag(argv, "include-drafts", include_drafts)
        _flag(argv, "stale", stale_days)
        return call(argv)

    @server.tool(annotations=_READ)
    def show(id: str) -> dict[str, Any]:
        """One need, principle or decision in full: text, sources, proofs and their results."""
        return call(["show", id])

    @server.tool(annotations=_READ)
    def plan(include_drafts: bool = False, revisit_days: int | None = None) -> dict[str, Any]:
        """What to work on next, ordered: must-have holes first."""
        argv = ["plan"]
        _flag(argv, "include-drafts", include_drafts)
        _flag(argv, "revisit", revisit_days)
        return call(argv)

    @server.tool(annotations=_READ)
    def lint(strict: bool = False) -> dict[str, Any]:
        """Check the board. Exit code 1 means errors were found."""
        argv = ["lint"]
        _flag(argv, "strict", strict)
        return call(argv)

    @server.tool(annotations=_READ)
    def inbox() -> dict[str, Any]:
        """Needs and sources that wait for a person's action."""
        return call(["inbox"])

    @server.tool(annotations=_READ)
    def brief(client: str) -> dict[str, Any]:
        """The meeting agenda for one client: its opinions and holes."""
        return call(["brief", client])

    @server.tool(annotations=_READ)
    def issues(need: str | None = None) -> dict[str, Any]:
        """The issue files ([prodc].issues) against the needs they serve."""
        argv = ["issues"]
        _flag(argv, "need", need)
        return call(argv)

    @server.tool(annotations=_READ)
    def suggest(id: str | None = None, relink: bool = False) -> dict[str, Any]:
        """Suggest test proofs for needs (or one need). Never applies them."""
        argv = ["suggest"]
        if id is not None:
            argv.append(id)
        _flag(argv, "relink", relink)
        return call(argv)

    @server.tool(annotations=_READ)
    def review() -> dict[str, Any]:
        """List the draft needs waiting for review."""
        return call(["review"])

    @server.tool(annotations=_READ)
    def dupes() -> dict[str, Any]:
        """Needs whose text looks like another need's."""
        return call(["dupes"])

    # -- write tools ------------------------------------------------------------------------

    @server.tool(annotations=_WRITE)
    def add_need(
        id: str,
        text: str,
        file: str,
        who: str | None = None,
        kind: Literal["secondary", "assumption"] | None = None,
        draft: bool = False,
        dry_run: bool = False,
        expect_sha: str | None = None,
    ) -> dict[str, Any]:
        """Add a need to a YAML file. ``kind`` records where it came from; never primary."""
        argv = ["add", "need", id, "--text", text, "--file", file]
        _flag(argv, "who", who)
        _flag(argv, "kind", kind)
        _flag(argv, "draft", draft)
        return call(_write_flags(argv, dry_run, expect_sha))

    @server.tool(annotations=_WRITE)
    def add_decision(
        id: str,
        text: str,
        needs: list[str],
        file: str,
        alternatives: list[str] | None = None,
        consequences: str | None = None,
        principles: list[str] | None = None,
        dry_run: bool = False,
        expect_sha: str | None = None,
    ) -> dict[str, Any]:
        """Record how a need will be built, and the alternatives that were rejected."""
        argv = ["add", "decision", id, "--text", text, "--file", file, "--needs", ",".join(needs)]
        for alt in alternatives or []:
            argv += ["--alternative", alt]
        _flag(argv, "consequences", consequences)
        if principles:
            argv += ["--principles", ",".join(principles)]
        return call(_write_flags(argv, dry_run, expect_sha))

    @server.tool(annotations=_WRITE)
    def set(
        id: str, assignment: str, dry_run: bool = False, expect_sha: str | None = None
    ) -> dict[str, Any]:
        """Set one field on a need, as ``key=value`` (for example ``must=true``)."""
        return call(_write_flags(["set", id, assignment], dry_run, expect_sha))

    @server.tool(annotations=_WRITE)
    def capture(
        id: str,
        kind: Literal["secondary", "assumption"],
        who: str | None = None,
        date: str | None = None,
        quote: str | None = None,
        locator: str | None = None,
        role: str | None = None,
        dry_run: bool = False,
        expect_sha: str | None = None,
    ) -> dict[str, Any]:
        """Add a source to a need. Only secondary or assumption: primary is added by a person."""
        argv = ["capture", id, "--kind", kind]
        _flag(argv, "who", who)
        _flag(argv, "date", date)
        _flag(argv, "quote", quote)
        _flag(argv, "locator", locator)
        _flag(argv, "role", role)
        return call(_write_flags(argv, dry_run, expect_sha))

    @server.tool(annotations=_WRITE)
    def promote(ids: list[str], dry_run: bool = False) -> dict[str, Any]:
        """Promote reviewed draft needs onto the board."""
        argv = ["review", "--promote", *ids]
        _flag(argv, "dry-run", dry_run)
        return call(argv)

    # -- the issue register (docs/issues) --------------------------------------------------

    def _field_args(fields: dict[str, str | list[str]] | None) -> list[str]:
        out: list[str] = []
        for key, value in (fields or {}).items():
            for v in value if isinstance(value, list) else [value]:
                out += ["--field", f"{key}={v}"]
        return out

    @server.tool(annotations=_READ)
    def issue_board(
        status: str | None = None, area: str | None = None, owner: str | None = None
    ) -> dict[str, Any]:
        """Start here for engineering work: issues ready to pick up, and what the rest waits on.

        Any filter (status open/in-progress/blocked/done, area, owner; 'none' for unowned)
        returns a flat list instead.
        """
        argv = ["issue", "board"]
        _flag(argv, "status", status)
        _flag(argv, "area", area)
        _flag(argv, "owner", owner)
        return call(argv)

    @server.tool(annotations=_READ)
    def issue_show(name: str) -> dict[str, Any]:
        """One issue file in full. ``name`` is a filename or an unambiguous part of the slug."""
        return call(["issue", "show", name])

    @server.tool(annotations=_READ)
    def issue_check() -> dict[str, Any]:
        """Grade docs/issues against its config.toml. Exit code 1 means problems were found."""
        return call(["issue", "check"])

    @server.tool(annotations=_WRITE)
    def issue_file(
        title: str,
        area: str,
        body: str,
        blocked_by: list[str] | None = None,
        fields: dict[str, str | list[str]] | None = None,
    ) -> dict[str, Any]:
        """File an issue: work that is known, scoped, and not being done now.

        The body must make sense to a reader with no context: concrete instances, file:line,
        what was measured vs inferred, and "done" stated as an observation. ``fields`` holds
        what the folder's config.toml requires (scope, verify, ...); a list field takes a list.
        """
        argv = ["issue", "file", "--title", title, "--area", area, "--body", body]
        for slug in blocked_by or []:
            argv += ["--blocked-by", slug]
        return call(argv + _field_args(fields))

    @server.tool(annotations=_WRITE)
    def issue_update(
        name: str,
        title: str | None = None,
        status: Literal["open", "in-progress", "blocked", "done"] | None = None,
        area: str | None = None,
        blocked_by: list[str] | None = None,
        fields: dict[str, str | list[str]] | None = None,
    ) -> dict[str, Any]:
        """Change an issue's front matter; only what you pass changes. ``blocked_by=[]`` clears
        the blockers; leaving it out keeps them. Close with ``issue_close``, not status=done."""
        argv = ["issue", "update", name]
        _flag(argv, "title", title)
        _flag(argv, "status", status)
        _flag(argv, "area", area)
        if blocked_by is not None:
            if blocked_by:
                for slug in blocked_by:
                    argv += ["--blocked-by", slug]
            else:
                argv.append("--clear-blocked-by")
        return call(argv + _field_args(fields))

    @server.tool(annotations=_WRITE)
    def issue_close(name: str, fixed_in: str) -> dict[str, Any]:
        """Mark an issue done. The file stays, carrying ``fixed_in``: the sha on the mainline."""
        return call(["issue", "close", name, "--fixed-in", fixed_in])

    # -- the playbook -----------------------------------------------------------------------

    def _playbook() -> str:
        return files("prodc").joinpath("agent.md").read_text(encoding="utf-8")

    @server.prompt(name="playbook", description="The prodc agent playbook: how to act as the PM.")
    def playbook() -> str:
        return _playbook()

    @server.resource("prodc://playbook", name="playbook", mime_type="text/markdown")
    def playbook_resource() -> str:
        return _playbook()

    return server


def serve(root: str | None = None) -> None:
    """Run the server on stdio until the client disconnects."""
    build_server(project_root(root)).run("stdio")
