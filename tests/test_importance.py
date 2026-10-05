"""Importance rubric (#59): config scale, set validation, importance_set_at, show, lint."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from prodc.config import Config, ConfigError

_SCALE = """
[importance]
levels = [[1, "nice", "no one notices its absence"], [2, "useful", "asked for once"], [3, "needed", "blocks a flow"]]
"""

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
""" + _SCALE


def _project(tmp_path: Path, toml: str, needs: str) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


_ONE_NEED = """
needs:
  - id: N-1
    text: user can see a thing
"""


def test_config_parses_scale_and_labels(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path, _TOML, _ONE_NEED))
    assert cfg.importance_levels[2] == ("useful", "asked for once")
    assert cfg.importance_label(3) == "needed" and cfg.importance_label(None) is None


def test_config_rejects_malformed_scale(tmp_path: Path) -> None:
    bad = "[prodc]\nneeds = [\"needs/*.yaml\"]\n[importance]\nlevels = [[1, \"nice\"]]\n"
    with pytest.raises(ConfigError, match="number, label, meaning"):
        Config.load(_project(tmp_path, bad, _ONE_NEED))


def test_resolve_importance_by_number_and_label(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path, _TOML, _ONE_NEED))
    assert cfg.resolve_importance("2") == 2
    assert cfg.resolve_importance("needed") == 3
    with pytest.raises(ConfigError, match="not on the scale"):
        cfg.resolve_importance("5")


def test_resolve_importance_without_scale_accepts_any_int(tmp_path: Path) -> None:
    toml = "[prodc]\nneeds = [\"needs/*.yaml\"]\n"
    cfg = Config.load(_project(tmp_path, toml, _ONE_NEED))
    assert cfg.resolve_importance("7") == 7
    with pytest.raises(ConfigError, match="not an integer"):
        cfg.resolve_importance("needed")


def test_set_importance_by_label_stamps_date(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, _TOML, _ONE_NEED)
    code = main(["set", "N-1", "importance=needed", "--config", str(cfg)])
    assert code == 0
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "importance: 3" in text
    assert "importance_set_at:" in text and date.today().isoformat() in text


def test_set_importance_off_scale_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, _TOML, _ONE_NEED)
    code = main(["set", "N-1", "importance=9", "--config", str(cfg)])
    assert code == 2 and "not on the scale" in capsys.readouterr().err


def test_show_prints_label(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: user can see a thing
    importance: 2
    importance_set_at: 2026-10-01
"""
    main(["show", "N-1", "--config", str(_project(tmp_path, _TOML, needs))])
    out = capsys.readouterr().out
    assert "importance: 2 (useful)" in out and "set 2026-10-01" in out


def test_lint_flags_missing_revisit_date(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: user can see a thing
    importance: 2
"""
    main(["lint", "--config", str(_project(tmp_path, _TOML, needs))])
    assert "no revisit date" in capsys.readouterr().out


def test_lint_flags_stale_importance(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    old = (date.today() - timedelta(days=400)).isoformat()
    needs = f"""
needs:
  - id: N-1
    text: user can see a thing
    importance: 2
    importance_set_at: {old}
"""
    toml = _TOML + "\n[lint]\nimportance_revisit_days = 180\n"
    main(["lint", "--config", str(_project(tmp_path, toml, needs))])
    assert "revisit" in capsys.readouterr().out


def test_lint_flags_off_scale_importance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: user can see a thing
    importance: 9
"""
    main(["lint", "--config", str(_project(tmp_path, _TOML, needs))])
    assert "off the declared scale" in capsys.readouterr().out


def test_status_json_carries_importance_set_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: user can see a thing
    importance: 2
    importance_set_at: 2026-10-01
"""
    main(["status", "--config", str(_project(tmp_path, _TOML, needs)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    n1 = next(n for n in payload["needs"] if n["id"] == "N-1")
    assert n1["importance_set_at"] == "2026-10-01"
