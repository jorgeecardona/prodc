"""`prodc review`: triage staged drafts — list, promote, drop (#60 follow-up)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config
from prodc.loader import load

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_NEEDS = """\
# header comment, must survive
needs:
  - id: N-1
    text: the owner can see a delivered thing
    proofs: ["x:1"]
  - id: D-1
    text: the owner can see a delivered thing
    draft: true
    draft_added: 2026-10-10
  - id: D-2
    text: a totally unrelated vacuum request
    draft: true
"""


def _project(tmp_path: Path, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_review_lists_only_drafts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["review", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    ids = {d["id"] for d in payload["drafts"]}
    assert ids == {"D-1", "D-2"}  # N-1 is on the board, not a draft


def test_review_list_carries_staged_date_and_dup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["review", "--config", str(_project(tmp_path)), "--json"])
    rows = {d["id"]: d for d in json.loads(capsys.readouterr().out)["drafts"]}
    assert rows["D-1"]["staged"] == "2026-10-10"
    # D-1 is near-identical to N-1 → a duplicate hit; D-2 is unrelated → none
    assert rows["D-1"]["duplicate"] is not None
    assert rows["D-1"]["duplicate"]["id"] == "N-1"
    assert rows["D-2"]["duplicate"] is None


def test_review_promote_sets_draft_false(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    code = main(["review", "--promote", "D-1", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert by_id["D-1"].draft is False and by_id["D-2"].draft is True


def test_review_drop_deletes_the_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    code = main(["review", "--drop", "D-2", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()
    ids = {n.id for n in load(Config.load(cfg)).needs}
    assert ids == {"N-1", "D-1"}  # D-2 is gone from the file


def test_review_promote_all_except_dropped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    code = main(["review", "--promote-all", "--drop", "D-2", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert "D-2" not in by_id  # dropped
    assert by_id["D-1"].draft is False  # promoted


def test_review_refuses_non_draft(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    code = main(["review", "--drop", "N-1", "--config", str(cfg)])
    assert code == 2
    assert "not a staged draft" in capsys.readouterr().err


def test_review_refuses_id_in_both_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    code = main(["review", "--promote", "D-1", "--drop", "D-1", "--config", str(cfg)])
    assert code == 2
    assert "both --promote and --drop" in capsys.readouterr().err


def test_review_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    before = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    code = main(["review", "--promote-all", "--dry-run", "--config", str(cfg)])
    assert code == 0
    assert (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8") == before
    assert "dry-run" in capsys.readouterr().out


def test_review_preserves_header_comment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    main(["review", "--drop", "D-2", "--config", str(cfg)])
    capsys.readouterr()
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "# header comment, must survive" in text
