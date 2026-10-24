"""Research-board `answer` axis: DELIVERED means a question is *settled*; `answer`
(yes/no/inconclusive) records which way. A settled-NO is a result that still counts toward
coverage, not a gap. Authored on the Need, never computed — a product board never sets it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Answer, Need

_TOML = """
[prodc]
needs = ["needs/*.yaml"]

[proofs.x]
kind = "files"
"""

# N-1 is settled (the files proof resolves) with a NO answer — a disproven hypothesis.
_NEEDS = """
needs:
  - id: N-1
    text: the Collatz conjecture is false
    proofs: ["x:1"]
    answer: no
  - id: N-2
    text: a question with no direction recorded
    proofs: ["x:1"]
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    (tmp_path / "1").write_text("ok\n", encoding="utf-8")  # files adapter payload "1" exists
    return tmp_path / "prodc.toml"


# --- model / loader ---------------------------------------------------------


def test_loader_parses_answer(tmp_path: Path) -> None:
    by_id = {n.id: n for n in load(Config.load(_project(tmp_path))).needs}
    assert by_id["N-1"].answer is Answer.NO
    assert by_id["N-2"].answer is None  # absent → None, a product need


def test_loader_accepts_every_direction(tmp_path: Path) -> None:
    needs = """
needs:
  - id: Y
    text: settled yes
    answer: yes
  - id: N
    text: settled no
    answer: no
  - id: I
    text: cannot decide
    answer: inconclusive
"""
    by_id = {n.id: n for n in load(Config.load(_project(tmp_path, needs=needs))).needs}
    assert (by_id["Y"].answer, by_id["N"].answer, by_id["I"].answer) == (
        Answer.YES,
        Answer.NO,
        Answer.INCONCLUSIVE,
    )


def test_loader_errors_on_unknown_answer(tmp_path: Path) -> None:
    bad = "needs:\n  - id: B\n    text: bad\n    answer: maybe\n"
    with pytest.raises(LoaderError, match="unknown answer 'maybe'"):
        load(Config.load(_project(tmp_path, needs=bad)))


def test_answer_does_not_touch_coverage_rule() -> None:
    # answer is a direction, not a coverage axis — a settled-no still counts
    settled_no = Need(id="X", text="t", proofs=("x:1",), answer=Answer.NO)
    assert settled_no.counts_toward_coverage is True
    assert Need(id="X", text="t").answer is None  # default, product need


# --- status (coverage + honesty warning) ------------------------------------


def test_settled_no_is_delivered_and_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    by_id = {n["id"]: n for n in payload["needs"]}
    assert by_id["N-1"]["state"] == "delivered"  # settled
    assert by_id["N-1"]["answer"] == "no"  # answered NO — a result
    assert payload["summary"]["delivered"] == 2  # settled-no is delivered, not a gap
    assert payload["summary"]["total"] == 2


def test_warns_when_answer_on_unsettled_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    # a HOLE (no proof) carrying an answer — the direction is unsupported
    needs = "needs:\n  - id: H\n    text: unsettled\n    answer: yes\n"
    main(["status", "--config", str(_project(tmp_path, needs=needs)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    warnings = payload["needs"][0]["warnings"]
    assert any("declared on an unsettled question" in w for w in warnings)


def test_no_warning_when_answer_on_settled_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    n1 = next(n for n in payload["needs"] if n["id"] == "N-1")
    assert not any("unsettled question" in w for w in n1["warnings"])  # DELIVERED + no is honest


# --- render (show) ----------------------------------------------------------


def test_show_renders_answer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["show", "N-1", "--config", str(_project(tmp_path))])
    assert "answer: no" in capsys.readouterr().out


# --- writer (round-trips through the one-need splice with no writer change) --


def test_answer_survives_a_splice_edit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    main(["set", "N-1", "importance=3", "--config", str(cfg)])  # edit a different field
    capsys.readouterr()  # drop the diff
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert by_id["N-1"].answer is Answer.NO  # the authored answer is still there
    assert by_id["N-1"].importance == 3
    # on disk it stays the research word, never re-dumped as the YAML bool `false`
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "answer: no\n" in text  # untouched key keeps its authored text (#98)
    assert "answer: false" not in text
