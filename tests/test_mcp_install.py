"""prodc mcp install / uninstall: touch only the prodc entry, refuse what cannot be parsed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main


@pytest.fixture(autouse=True)
def _in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _read(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_bare_mcp_prints_help_and_exits_2() -> None:
    assert main(["mcp"]) == 2


def test_install_writes_a_new_claude_config() -> None:
    assert main(["mcp", "install"]) == 0
    assert _read(".mcp.json") == {
        "mcpServers": {
            "prodc": {"command": "uvx", "args": ["--from", "prodc[mcp]", "prodc", "mcp", "serve"]}
        }
    }


def test_install_keeps_other_servers_and_keys() -> None:
    Path(".mcp.json").write_text(
        json.dumps({"mcpServers": {"gitlab": {"command": "g"}}, "other": 1}), encoding="utf-8"
    )
    assert main(["mcp", "install"]) == 0
    data = _read(".mcp.json")
    assert data["other"] == 1
    assert list(data["mcpServers"]) == ["gitlab", "prodc"]  # type: ignore[arg-type]


def test_install_twice_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    main(["mcp", "install"])
    capsys.readouterr()
    main(["mcp", "install"])
    assert "unchanged" in capsys.readouterr().out


def test_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mcp", "install", "--dry-run"]) == 0
    assert not Path(".mcp.json").exists()
    assert "would edit" in capsys.readouterr().out


def test_invalid_json_is_refused_not_overwritten(capsys: pytest.CaptureFixture[str]) -> None:
    text = '{\n  // a comment\n  "mcpServers": {}\n}\n'
    Path(".mcp.json").write_text(text, encoding="utf-8")
    assert main(["mcp", "install"]) == 2
    assert Path(".mcp.json").read_text(encoding="utf-8") == text
    assert "by hand" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("client", "path", "key", "typed"),
    [
        ("cursor", ".cursor/mcp.json", "mcpServers", True),
        ("vscode", ".vscode/mcp.json", "servers", True),
    ],
)
def test_each_client_gets_its_own_file_and_key(
    client: str, path: str, key: str, typed: bool
) -> None:
    assert main(["mcp", "install", "--client", client]) == 0
    entry = _read(path)[key]["prodc"]  # type: ignore[index]
    assert (entry.get("type") == "stdio") is typed  # type: ignore[union-attr]


def test_codex_and_user_scope_print_and_write_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mcp", "install", "--client", "codex"]) == 0
    assert main(["mcp", "install", "--scope", "user"]) == 0
    out = capsys.readouterr().out
    assert "[mcp_servers.prodc]" in out and "claude mcp add --scope user prodc" in out
    assert not any(Path().iterdir())


def test_custom_command() -> None:
    assert main(["mcp", "install", "--command", "uv run prodc mcp serve"]) == 0
    entry = _read(".mcp.json")["mcpServers"]["prodc"]  # type: ignore[index]
    assert entry == {"command": "uv", "args": ["run", "prodc", "mcp", "serve"]}


def test_uninstall_leaves_other_servers() -> None:
    Path(".mcp.json").write_text(json.dumps({"mcpServers": {"gitlab": {"command": "g"}}}))
    main(["mcp", "install"])
    assert main(["mcp", "uninstall"]) == 0
    assert _read(".mcp.json") == {"mcpServers": {"gitlab": {"command": "g"}}}


def test_uninstall_deletes_a_file_only_prodc_used() -> None:
    main(["mcp", "install"])
    assert main(["mcp", "uninstall"]) == 0
    assert not Path(".mcp.json").exists()


def test_serve_without_the_extra_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "prodc.mcp_server", None)
    assert main(["mcp", "serve"]) == 2
    assert "prodc[mcp]" in capsys.readouterr().err
