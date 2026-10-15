"""Draft needs (#60): staged needs stay off the counted board until promoted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_NEEDS = """
needs:
  - id: N-1
    text: user can see a delivered thing
    proofs: ["x:1"]
  - id: D-1
    text: a staged draft idea
    draft: true
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_loader_parses_draft(tmp_path: Path) -> None:
    from prodc.loader import load

    cfg = Config.load(_project(tmp_path))
    by_id = {n.id: n for n in load(cfg).needs}
    assert by_id["D-1"].draft is True and by_id["N-1"].draft is False


def test_status_excludes_drafts_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    ids = {n["id"] for n in payload["needs"]}
    assert ids == {"N-1"}  # draft D-1 is off the board
    assert payload["summary"]["total"] == 1  # and out of coverage


def test_status_include_drafts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--include-drafts", "--json"])
    payload = json.loads(capsys.readouterr().out)
    ids = {n["id"] for n in payload["needs"]}
    assert ids == {"N-1", "D-1"}


def test_status_text_shows_draft_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "drafts: 1 staged" in out


def test_add_draft_writes_flag(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs: []\n")
    code = main(
        [
            "add",
            "need",
            "N-9",
            "--text",
            "a new staged need",
            "--who",
            "agent",
            "--file",
            "needs/a.yaml",
            "--draft",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert "draft: true" in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")


def test_default_draft_config(tmp_path: Path) -> None:
    from prodc.cli import main

    toml = _TOML + "\n[add]\ndefault_draft = true\n"
    cfg = _project(tmp_path, toml=toml, needs="needs: []\n")
    main(
        [
            "add",
            "need",
            "N-9",
            "--text",
            "a new staged need",
            "--who",
            "agent",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert "draft: true" in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")


def test_promote_via_set_draft_false(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    code = main(["set", "D-1", "draft=false", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()  # drop the `set` diff output so only the status JSON remains
    # now D-1 counts on the board
    main(["status", "--config", str(cfg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {n["id"] for n in payload["needs"]} == {"N-1", "D-1"}


_AGE_NEEDS = """
needs:
  - id: N-1
    text: user can see a thing
  - id: OLD-1
    text: a long-forgotten draft
    draft: true
    draft_added: 2020-01-01
  - id: UNDATED-1
    text: a draft with no staged date
    draft: true
"""


def test_lint_flags_stale_draft(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    toml = _TOML + "\n[lint]\ndraft_max_age_days = 30\n"
    cfg = _project(tmp_path, toml=toml, needs=_AGE_NEEDS)
    code = main(["lint", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert code == 0  # an old draft is a warning, not a hard error
    assert "OLD-1: draft staged" in out
    assert "UNDATED-1: draft with no staged date" in out


def test_lint_no_draft_gate_without_knob(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs=_AGE_NEEDS)  # no [lint].draft_max_age_days
    main(["lint", "--config", str(cfg)])
    assert "draft staged" not in capsys.readouterr().out


def test_config_rejects_bad_draft_max_age_days(tmp_path: Path) -> None:
    from prodc.config import ConfigError

    toml = _TOML + "\n[lint]\ndraft_max_age_days = 0\n"
    with pytest.raises(ConfigError, match="draft_max_age_days"):
        Config.load(_project(tmp_path, toml=toml))
