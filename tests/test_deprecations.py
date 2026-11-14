"""Each deprecated thing prints one line per run: ``deprecated, removed in 0.12: ...``."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_NEED = "  - id: N-1\n    text: When I log in, I can see my orders.\n"


def _board(tmp_path: Path, toml: str = "", needs: str = _NEED, top: str = "") -> str:
    (tmp_path / "n.yaml").write_text(f"{top}needs:\n{needs}", encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(f'[prodc]\nfiles = ["n.yaml"]\n{toml}', encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _lines(err: str, thing: str) -> list[str]:
    return [ln for ln in err.splitlines() if f"deprecated, removed in 0.12: {thing}" in ln]


def test_sync_and_callbacks_warn_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _board(tmp_path, '[[callbacks.hooks]]\non = "state_change"\ncommand = ["true"]\n')
    main(["sync", "--config", cfg, "--dry-run"])
    err = capsys.readouterr().err
    assert len(_lines(err, "prodc sync")) == 1
    assert len(_lines(err, "[callbacks]")) == 1
    assert main(["lint", "--config", cfg]) == 0
    assert len(_lines(capsys.readouterr().out, "[callbacks]")) == 1


def test_gitlab_source_warns_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _board(tmp_path, '[sources.gl]\nkind = "gitlab"\nproject = "a/b"\n')
    assert main(["status", "--config", cfg]) == 0
    assert len(_lines(capsys.readouterr().err, '[sources.gl] kind = "gitlab"')) == 1
