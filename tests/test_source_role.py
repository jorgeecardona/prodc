"""Source.role (#52 follow-up): which declared role vouched for the evidence, + label deprecation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.board import warrant
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Need, Source, SourceKind
from prodc.writer import capture_source

_TOML = "[prodc]\nneeds = [\"needs/*.yaml\"]\n"

_NEEDS = """
roles:
  - id: owner
    text: owns the roastery
needs:
  - id: N-1
    text: the owner can see orders
    sources:
      - kind: primary
        who: Jordan
        role: owner
        date: 2026-01-01
        quote: "I need this"
"""


def _project(tmp_path: Path, needs: str = _NEEDS, toml: str = _TOML) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def test_loader_parses_source_role(tmp_path: Path) -> None:
    need = load(_project(tmp_path)).needs[0]
    assert need.sources[0].role == "owner"


def test_source_role_orthogonal_to_kind() -> None:
    # role is provenance, not a strength tier — it does not change ranking
    s = Source(kind=SourceKind.PRIMARY, who="J", role="owner")
    n = Need(id="N", text="t", sources=(s,))
    assert n.strongest_kind is SourceKind.PRIMARY  # role plays no part


def test_warrant_shows_role_on_primary(tmp_path: Path) -> None:
    need = load(_project(tmp_path)).needs[0]
    assert warrant(need) == "primary:Jordan (owner)"


def test_warrant_without_role_is_unchanged() -> None:
    n = Need(id="N", text="t", sources=(Source(kind=SourceKind.PRIMARY, who="Jo"),))
    assert warrant(n) == "primary:Jo"


def test_dangling_source_role_rejected(tmp_path: Path) -> None:
    needs = _NEEDS.replace("role: owner", "role: nobody")
    with pytest.raises(LoaderError, match="source\\[0\\] role 'nobody' is not a known role id"):
        load(_project(tmp_path, needs=needs))


def test_show_json_carries_source_role(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    _project(tmp_path)
    main(["show", "N-1", "--config", str(tmp_path / "prodc.toml"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["sources"][0]["role"] == "owner"


def test_capture_writes_source_role(tmp_path: Path) -> None:
    cfg = _project(
        tmp_path,
        needs="roles:\n  - id: owner\n    text: owns it\nneeds:\n  - id: N-1\n    text: t\n",
    )
    capture_source(
        cfg,
        "N-1",
        kind="primary",
        who="Jordan",
        role="owner",
        date="2026-02-02",
        quote="I said so",
        locator=None,
        expect_sha=None,
        dry_run=False,
    )
    need = load(cfg).needs[0]
    assert need.sources[-1].role == "owner" and need.sources[-1].who == "Jordan"


def test_capture_dangling_role_rejected_by_gate(tmp_path: Path) -> None:
    cfg = _project(
        tmp_path,
        needs="roles:\n  - id: owner\n    text: owns it\nneeds:\n  - id: N-1\n    text: t\n",
    )
    with pytest.raises(Exception, match="not a known role id"):
        capture_source(
            cfg,
            "N-1",
            kind="primary",
            who="Jordan",
            role="ghost",
            date="2026-02-02",
            quote="q",
            locator=None,
            expect_sha=None,
            dry_run=False,
        )


def test_lint_warns_on_deprecated_label(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    needs = 'who: jordan\nlabel: "design partner"\nneeds:\n  - id: N-1\n    text: t\n'
    _project(tmp_path, needs=needs)
    main(["lint", "--config", str(tmp_path / "prodc.toml")])
    out = capsys.readouterr().out
    assert "'label'" in out and "deprecated" in out
