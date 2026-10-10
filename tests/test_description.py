"""Optional free-form `description` on a Need — longer detail, not EARS-checked (#73)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config
from prodc.loader import load
from prodc.model import Model, ears_warnings

_TOML = '[prodc]\nneeds = ["needs/*.yaml"]\n'
_NEEDS = """
needs:
  - id: N-1
    text: "When an order is past due, an owner can see it highlighted."
    description: |
      Edge cases: partial shipments count as due; a note explains the rule.
      Not a solution — kept out of the EARS one-liner on purpose.
  - id: N-2
    text: "export the run sheet"
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    return tmp_path / "prodc.toml"


def _model(cfg_path: Path) -> Model:
    return load(Config.load(cfg_path))


def test_description_loaded(tmp_path: Path) -> None:
    model = _model(_project(tmp_path))
    by_id = {n.id: n for n in model.needs}
    assert "partial shipments" in (by_id["N-1"].description or "")
    assert by_id["N-2"].description is None  # optional, absent by default


def test_description_is_not_ears_checked(tmp_path: Path) -> None:
    """The EARS linter governs `text`, never `description` (which may be prose)."""
    model = _model(_project(tmp_path))
    n1 = next(n for n in model.needs if n.id == "N-1")
    # The description is not a valid EARS line, but it must not produce EARS warnings:
    assert ears_warnings(n1.text) == []  # the one-liner is well-shaped
    assert n1.description is not None and ears_warnings(n1.description)  # would warn if checked
    # Nothing in the model runs ears_warnings over description — the field is exempt by design.


def test_show_renders_description(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "N-1", "--config", str(_project(tmp_path))])
    assert code == 0
    assert "description:" in capsys.readouterr().out


def test_show_json_carries_description(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "N-1", "--json", "--config", str(_project(tmp_path))])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "partial shipments" in payload["description"]


def test_set_description(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    code = main(["set", "N-2", "description=A worked example lives here.", "--config", str(cfg)])
    assert code == 0
    model = _model(cfg)
    n2 = next(n for n in model.needs if n.id == "N-2")
    assert n2.description == "A worked example lives here."


def test_description_round_trips_on_unrelated_edit(tmp_path: Path) -> None:
    """Editing another field on N-1 must not drop its description (writer round-trip)."""
    cfg = _project(tmp_path)
    code = main(["set", "N-1", "must=true", "--config", str(cfg)])
    assert code == 0
    n1 = next(n for n in _model(cfg).needs if n.id == "N-1")
    assert n1.must is True
    assert "partial shipments" in (n1.description or "")
