"""`[prodc].files` (#95): one neutral key for the prodc files, `needs` kept as an alias, and
`prodc show` answering for a decision as well as a need."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config, ConfigError
from prodc.loader import load

_NEEDS = "needs:\n  - id: N-1\n    text: see past-due orders\n"
_DECISIONS = """decisions:
  - id: D-1
    text: highlight rows in red
    needs: [N-1]
    alternatives: [a separate past-due tab]
    consequences: colour carries meaning
"""


def _project(tmp_path: Path, prodc_tbl: str) -> Path:
    (tmp_path / "product" / "needs").mkdir(parents=True)
    (tmp_path / "product" / "decisions").mkdir(parents=True)
    (tmp_path / "product" / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "product" / "decisions" / "d.yaml").write_text(_DECISIONS, encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(f"[prodc]\n{prodc_tbl}\n", encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_files_key_reads_every_noun_from_its_own_folder(tmp_path: Path) -> None:
    cfg = Config.load(
        _project(tmp_path, 'files = ["product/needs/*.yaml", "product/decisions/*.yaml"]')
    )
    model = load(cfg)
    assert [n.id for n in model.needs] == ["N-1"]
    assert [d.id for d in model.decisions] == ["D-1"]


def test_needs_key_still_works_as_alias(tmp_path: Path) -> None:
    cfg = Config.load(
        _project(tmp_path, 'needs = ["product/needs/*.yaml", "product/decisions/*.yaml"]')
    )
    assert [d.id for d in load(cfg).decisions] == ["D-1"]


def test_files_and_needs_merge_and_overlap_is_read_once(tmp_path: Path) -> None:
    # product/needs/*.yaml is matched by both keys: it must load once, not as a duplicate id.
    toml = 'files = ["product/**/*.yaml"]\nneeds = ["product/needs/*.yaml"]'
    cfg = Config.load(_project(tmp_path, toml))
    assert cfg.need_globs == ["product/**/*.yaml", "product/needs/*.yaml"]
    model = load(cfg)
    assert [n.id for n in model.needs] == ["N-1"]
    assert [d.id for d in model.decisions] == ["D-1"]


def test_no_glob_is_a_config_error_naming_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[prodc\]\.files must list at least one glob"):
        Config.load(_project(tmp_path, ""))


def test_write_outside_globs_names_files_key(tmp_path: Path) -> None:
    from prodc.writer import WriteError, add_principle

    cfg = Config.load(_project(tmp_path, 'files = ["product/needs/*.yaml"]'))
    with pytest.raises(WriteError, match=r"\[prodc\]\.files glob"):
        add_principle(
            cfg,
            "P-1",
            "local-first",
            file="elsewhere/p.yaml",
            revised_at="2026-10-20",
            dry_run=True,
        )


def test_show_prints_a_decision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, 'files = ["product/**/*.yaml"]')
    assert main(["show", "D-1", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "D-1  highlight rows in red" in out
    assert "N-1: see past-due orders" in out  # what it serves, with the need's text
    assert "over: a separate past-due tab" in out
    assert "consequences: colour carries meaning" in out


def test_show_decision_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, 'files = ["product/**/*.yaml"]')
    assert main(["show", "D-1", "--json", "--config", str(cfg)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "D-1" and payload["needs"] == ["N-1"]
    assert payload["warnings"] == []


def test_show_unknown_id_names_both_kinds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, 'files = ["product/**/*.yaml"]')
    assert main(["show", "X-9", "--config", str(cfg)]) == 2
    assert "no need or decision 'X-9'" in capsys.readouterr().err
