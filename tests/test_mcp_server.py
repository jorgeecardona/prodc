"""The MCP server: tools run the real CLI, primary is refused, writes chain by sha."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from prodc.cli.app import build_parser
from prodc.mcp_server import INSTRUCTIONS, build_server

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "quickstart"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def board(tmp_path: Path) -> Path:
    shutil.copytree(EXAMPLE, tmp_path / "b")
    return tmp_path / "b"


def _result(res: Any) -> dict[str, Any]:
    assert not res.is_error, res
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc)
    return json.loads(res.content[0].text)


async def test_tools_are_the_agent_safe_set(board: Path) -> None:
    async with Client(build_server(board)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
    assert names == {
        "status", "show", "plan", "lint", "inbox", "brief", "suggest", "review",
        "dupes", "add_need", "add_decision", "set", "capture", "promote",
        "issue_board", "issue_next", "issue_list", "issue_show", "issue_check", "issue_file", "issue_update", "issue_close",
    }  # fmt: skip
    for forbidden in ("accept", "attest", "outcome", "withdraw", "sync"):
        assert forbidden not in names


async def test_read_tools_are_marked_read_only(board: Path) -> None:
    async with Client(build_server(board)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert tools["status"].annotations and tools["status"].annotations.read_only_hint
    assert tools["set"].annotations and tools["set"].annotations.read_only_hint is False


async def test_status_runs_the_cli_on_the_board(board: Path) -> None:
    async with Client(build_server(board)) as c:
        out = _result(await c.call_tool("status", {}))
    assert out["exit_code"] in (0, 1)
    assert isinstance(out["data"], dict)


async def test_capture_schema_has_no_primary(board: Path) -> None:
    async with Client(build_server(board)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        schema = json.dumps(tools["capture"].input_schema)
        assert "secondary" in schema and "primary" not in schema
        res = await c.call_tool("capture", {"id": "N-1", "kind": "primary"})
    assert res.is_error


async def test_set_chains_with_expect_sha(board: Path) -> None:
    async with Client(build_server(board)) as c:
        status = _result(await c.call_tool("status", {}))
        need_id = status["data"]["needs"][0]["id"]
        preview = _result(
            await c.call_tool("set", {"id": need_id, "assignment": "must=true", "dry_run": True})
        )
        sha = preview["data"]["sha_before"]
        stale = await c.call_tool(
            "set", {"id": need_id, "assignment": "must=false", "expect_sha": "0" * 64}
        )
        assert stale.is_error
        done = _result(
            await c.call_tool("set", {"id": need_id, "assignment": "must=true", "expect_sha": sha})
        )
    assert done["data"]["sha_after"] == preview["data"]["sha_after"]


async def test_playbook_prompt_and_instructions(board: Path) -> None:
    async with Client(build_server(board)) as c:
        prompt = await c.get_prompt("playbook")
    assert "primary" in json.dumps(prompt.model_dump())
    assert "Never record a primary source" in INSTRUCTIONS


def test_every_tool_argv_parses_with_the_real_parser() -> None:
    parser = build_parser()
    for argv in (
        ["status", "--client", "c", "--goal", "g", "--tag", "t", "--only-must", "--stale", "3"],
        ["plan", "--include-drafts", "--revisit", "30"],
        ["lint", "--strict"],
        ["brief", "c"],
        ["issue", "file", "--title", "t", "--area", "a", "--body", "b", "--need", "N-1",
         "--need", "N-2"],
        ["issue", "update", "x", "--owner", "me"],
        ["issue", "list", "--need", "N-1"],
        ["suggest", "N-1", "--relink"],
        ["review", "--promote", "D-1", "--dry-run"],
        ["add", "need", "N-9", "--text", "t", "--file", "f.yaml", "--who", "w", "--kind",
         "assumption", "--draft", "--dry-run", "--expect-sha", "x"],
        ["add", "decision", "D-9", "--text", "t", "--file", "f.yaml", "--needs", "N-1",
         "--alternative", "a", "--consequences", "c", "--principles", "P-1"],
        ["set", "N-1", "must=true", "--dry-run", "--expect-sha", "x"],
        ["capture", "N-1", "--kind", "secondary", "--who", "w", "--date", "2026-01-01",
         "--quote", "q", "--locator", "l", "--role", "r"],
    ):  # fmt: skip
        parser.parse_args([*argv, "--json"])
