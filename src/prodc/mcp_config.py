"""Register the prodc MCP server in an MCP client's project config (``prodc mcp install``).

The write touches only the ``prodc`` entry, keeps every other server and key in order, and
refuses a file it cannot parse (for example JSON with comments) instead of overwriting it.
Codex (TOML) and user-scope configs are not written: prodc prints the client's own command.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

ClientName = Literal["claude", "cursor", "vscode", "codex"]

DEFAULT_COMMAND = 'uvx --from "prodc[mcp]" prodc mcp serve'
"""The command written by default: runs the latest prodc[mcp] in its own isolated env."""


@dataclass(frozen=True)
class ClientConfig:
    """Where one client keeps its project MCP config and how an entry looks there."""

    path: str  # relative to the project root
    key: str  # the top-level object that holds the servers
    needs_type: bool  # the client requires "type": "stdio"


CLIENTS: dict[str, ClientConfig] = {
    "claude": ClientConfig(".mcp.json", "mcpServers", needs_type=False),
    "cursor": ClientConfig(".cursor/mcp.json", "mcpServers", needs_type=True),
    "vscode": ClientConfig(".vscode/mcp.json", "servers", needs_type=True),
}


class McpConfigError(Exception):
    """The config file exists but cannot be safely rewritten."""


def entry(client: ClientName, command: str = DEFAULT_COMMAND) -> dict[str, Any]:
    """The server entry for ``client``: ``{command, args}`` plus ``type`` where required."""
    cmd, *args = shlex.split(command)
    out: dict[str, Any] = {}
    if CLIENTS[client].needs_type:
        out["type"] = "stdio"
    out["command"] = cmd
    out["args"] = args
    return out


def manual_instructions(client: ClientName, scope: str, command: str = DEFAULT_COMMAND) -> str:
    """The client's own command for what prodc does not write (Codex, user scope)."""
    if client == "codex":
        cmd, *args = shlex.split(command)
        toml_args = ", ".join(json.dumps(a) for a in args)
        return (
            f"codex mcp add prodc -- {command}\n\nor add to ~/.codex/config.toml:\n\n"
            f'[mcp_servers.prodc]\ncommand = "{cmd}"\nargs = [{toml_args}]\n'
        )
    if client == "claude":
        return f"claude mcp add --scope {scope} prodc -- {command}\n"
    if client == "vscode":
        return f"code --add-mcp '{json.dumps({'name': 'prodc', **entry(client, command)})}'\n"
    return f"add to ~/.cursor/mcp.json under mcpServers:\n{json.dumps({'prodc': entry(client, command)}, indent=2)}\n"


@dataclass(frozen=True)
class ConfigEdit:
    """A proposed change to one client config file."""

    path: Path
    old_text: str  # "" when the file does not exist
    new_text: str  # "" when the file should be deleted

    @property
    def changed(self) -> bool:
        return self.old_text != self.new_text


def _load(path: Path) -> tuple[str, dict[str, Any]]:
    if not path.exists():
        return "", {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return text, {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"{path} is not plain JSON ({exc.msg}, line {exc.lineno}); prodc will not rewrite it. "
            "Add the entry by hand."
        ) from exc
    if not isinstance(data, dict):
        raise McpConfigError(f"{path}: the top level is not a JSON object")
    return text, cast(dict[str, Any], data)


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def install(root: Path, client: ClientName, command: str = DEFAULT_COMMAND) -> ConfigEdit:
    """Return the edit that adds or updates the ``prodc`` entry. Writes nothing."""
    cc = CLIENTS[client]
    path = root / cc.path
    old, data = _load(path)
    raw = data.get(cc.key, {})
    if not isinstance(raw, dict):
        raise McpConfigError(f"{path}: {cc.key!r} is not a JSON object")
    servers = cast(dict[str, Any], raw)
    new_servers = dict(servers)
    new_servers["prodc"] = entry(client, command)
    new = dict(data)
    new[cc.key] = new_servers
    return ConfigEdit(path, old, old if new == data else _dump(new))


def uninstall(root: Path, client: ClientName) -> ConfigEdit:
    """Return the edit that removes only the ``prodc`` entry. Writes nothing.

    The file is deleted only when nothing but an empty servers object would be left.
    """
    cc = CLIENTS[client]
    path = root / cc.path
    old, data = _load(path)
    raw = data.get(cc.key)
    if not isinstance(raw, dict) or "prodc" not in raw:
        return ConfigEdit(path, old, old)
    servers = cast(dict[str, Any], raw)
    new_servers = {k: v for k, v in servers.items() if k != "prodc"}
    new: dict[str, Any] = {**data, cc.key: new_servers}
    if new == {cc.key: {}}:
        return ConfigEdit(path, old, "")
    return ConfigEdit(path, old, _dump(new))


def apply(edit: ConfigEdit) -> None:
    """Write (or delete) the file the edit describes."""
    if not edit.changed:
        return
    if edit.new_text == "":
        edit.path.unlink()
        return
    edit.path.parent.mkdir(parents=True, exist_ok=True)
    edit.path.write_text(edit.new_text, encoding="utf-8")
