"""``prodc lint`` release hygiene: unscheduled needs, a must after the current release, empty
releases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
"""

_NEEDS = """
releases:
  - id: R1
    text: first
  - id: R2
    text: second
  - id: R3
    text: nobody here
needs:
  - id: N-1
    text: in the current release
    release: R1
  - id: N-2
    text: a must parked later
    release: R2
    must: true
  - id: N-3
    text: no release
  - id: N-4
    text: no release, but shipped
    proofs: ["acc:signed"]
  - id: N-5
    text: a draft with no release
    draft: true
"""


def _warnings(
    tmp_path: Path, needs: str, capsys: pytest.CaptureFixture[str]
) -> dict[str, list[str]]:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    main(["lint", "--config", str(tmp_path / "prodc.toml"), "--json"])
    out: dict[str, list[str]] = {}
    for w in json.loads(capsys.readouterr().out)["warnings"]:
        out.setdefault(w["id"], []).append(w["warning"])
    return out


def test_release_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    got = _warnings(tmp_path, _NEEDS, capsys)
    assert any(w.startswith("unscheduled") for w in got["N-3"])
    assert not any(w.startswith("unscheduled") for w in got.get("N-4", []))
    assert not any(w.startswith("unscheduled") for w in got.get("N-5", []))
    assert any("after the current release R1" in w for w in got["N-2"])
    assert "empty release: no need names it" in got["R3"]
    assert "empty release: no need names it" not in got.get("R1", [])


def test_no_releases_no_release_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    got = _warnings(tmp_path, "needs:\n  - id: N-1\n    text: t\n", capsys)
    assert not any("unscheduled" in w for ws in got.values() for w in ws)
