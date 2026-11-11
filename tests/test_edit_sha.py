"""A write's --json carries the file hashes, so an agent can chain writes with --expect-sha."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.cli.app import build_parser


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: N-1\n    text: t\n", encoding="utf-8"
    )
    return tmp_path / "prodc.toml"


def test_dry_run_hash_then_write_with_expect_sha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = str(_project(tmp_path))
    assert main(["set", "N-1", "must=true", "--dry-run", "--json", "--config", cfg]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert len(preview["sha_before"]) == 64 and preview["sha_before"] != preview["sha_after"]

    args = ["set", "N-1", "must=true", "--json", "--expect-sha", preview["sha_before"]]
    assert main([*args, "--config", cfg]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["sha_after"] == preview["sha_after"]


def test_a_stale_hash_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = str(_project(tmp_path))
    code = main(["set", "N-1", "must=true", "--expect-sha", "0" * 64, "--config", cfg])
    assert code == 2
    assert "must: true" not in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")


def test_build_parser_is_the_parser_main_uses() -> None:
    ns = build_parser().parse_args(["status", "--json"])
    assert ns.command == "status" and ns.json
