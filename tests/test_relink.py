"""BROKEN relink (#54): propose a live inventory entry to replace a renamed-test locator."""

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
[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
"""

# The scenario the need points at was renamed: "...order" -> "...an order".
_FEATURE = """
Feature: orders
  @implemented
  Scenario: Owner cancels an order
    Given a thing
    Then it works
"""

_NEEDS = """
needs:
  - id: N-1
    text: the owner can cancel an order
    proofs: ["web:orders.feature#Owner cancels order"]
  - id: H-1
    text: an unrelated hole
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_relink_proposes_renamed_scenario(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["suggest", "--relink", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    s = payload[0]
    assert s["need"] == "N-1"
    assert s["broken"] == "web:orders.feature#Owner cancels order"
    assert s["locator"] == "web:orders.feature#Owner cancels an order"


def test_relink_only_targets_broken_not_hole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["suggest", "--relink", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {s["need"] for s in payload} == {"N-1"}  # H-1 is a HOLE, not a relink target


def test_relink_apply_swaps_locator_and_delivers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    code = main(["suggest", "--relink", "--apply", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()
    need = {n.id: n for n in load(Config.load(cfg)).needs}["N-1"]
    assert need.proofs == ("web:orders.feature#Owner cancels an order",)


def test_relink_apply_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    before = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    code = main(["suggest", "--relink", "--apply", "--dry-run", "--config", str(cfg)])
    assert code == 0
    capsys.readouterr()
    assert (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8") == before


def test_relink_skips_when_adapter_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A locator whose adapter does not exist is BROKEN but has no inventory to relink against.
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: N-1\n    text: t\n    proofs: ['ghost:1']\n", encoding="utf-8"
    )
    main(["suggest", "--relink", "--config", str(tmp_path / "prodc.toml"), "--json"])
    assert json.loads(capsys.readouterr().out) == []
