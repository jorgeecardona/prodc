"""The `need:` proof adapter (research-board step 2): a need→need edge for the question→question
DAG. `need:A` delivers iff A is settled; `need:A@yes` iff A is settled *and* answered that way.
It rides the proofs tuple and reuses the resolver's cycle detection — no new field, no new edge."""

from __future__ import annotations

from pathlib import Path

from prodc.config import Config
from prodc.loader import load
from prodc.model import Answer, NeedState
from prodc.status import resolve

_TOML = """
[prodc]
needs = ["needs/*.yaml"]

[proofs.x]
kind = "files"
"""


def _resolve(tmp_path: Path, needs: str) -> dict[str, NeedState]:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    (tmp_path / "1").write_text("ok\n", encoding="utf-8")  # the files proof `x:1` exists → settled
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    results = resolve(list(model.needs), cfg.adapters, cfg.source_adapters)
    return {r.need.id: r.state for r in results}


def test_needref_delivers_when_referenced_is_settled(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: lemma A is proven
    proofs: ["x:1"]
  - id: B
    text: theorem B builds on A
    proofs: ["need:A"]
""",
    )
    assert states["A"] is NeedState.DELIVERED
    assert states["B"] is NeedState.DELIVERED  # A is settled → B's needref delivers


def test_needref_pends_when_referenced_not_settled(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: lemma A, no proof yet
  - id: B
    text: theorem B builds on A
    proofs: ["need:A"]
""",
    )
    assert states["A"] is NeedState.HOLE  # no proof
    assert states["B"] is NeedState.PENDING  # cannot deliver until A settles


def test_needref_broken_on_unknown_id(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: B
    text: depends on a need that does not exist
    proofs: ["need:GHOST"]
""",
    )
    assert states["B"] is NeedState.BROKEN


def test_needref_directional_matches_authored_answer(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: the counterexample search settled it
    proofs: ["x:1"]
    answer: no
  - id: B
    text: needs A specifically answered no
    proofs: ["need:A@no"]
  - id: C
    text: needs A answered yes
    proofs: ["need:A@yes"]
""",
    )
    assert states["A"] is NeedState.DELIVERED
    assert states["B"] is NeedState.DELIVERED  # A settled AND answered no
    assert states["C"] is NeedState.PENDING  # A settled, but answered no, not yes


def test_needref_directional_pends_when_no_answer_recorded(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: settled but no direction recorded
    proofs: ["x:1"]
  - id: B
    text: wants A answered yes
    proofs: ["need:A@yes"]
""",
    )
    assert states["A"] is NeedState.DELIVERED
    assert states["B"] is NeedState.PENDING  # settled, but no answer to match the direction


def test_needref_malformed_direction_is_broken(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: settled
    proofs: ["x:1"]
  - id: B
    text: bad direction token
    proofs: ["need:A@maybe"]
""",
    )
    assert states["B"] is NeedState.BROKEN


def test_needref_cycle_is_broken_not_infinite(tmp_path: Path) -> None:
    states = _resolve(
        tmp_path,
        """
needs:
  - id: A
    text: A depends on B
    proofs: ["need:B"]
  - id: B
    text: B depends on A
    proofs: ["need:A"]
""",
    )
    assert states["A"] is NeedState.BROKEN
    assert states["B"] is NeedState.BROKEN  # the cycle is caught, resolution terminates


def test_needref_b_does_not_inherit_a_answer(tmp_path: Path) -> None:
    # B depends on A (answered no) but B is its own question with its own answer
    by_id = {}
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "1").write_text("ok\n", encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        """
needs:
  - id: A
    text: A answered no
    proofs: ["x:1"]
    answer: no
  - id: B
    text: B depends on A, answered yes itself
    proofs: ["need:A"]
    answer: yes
""",
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    by_id = {n.id: n for n in load(cfg).needs}
    assert by_id["A"].answer is Answer.NO
    assert by_id["B"].answer is Answer.YES  # B keeps its own answer, not A's
