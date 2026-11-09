"""Commit 3: `prodc add principle --from-catalog` and loader ux- prefix guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.catalog.ux import UX_CATALOG
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import SourceKind, WithdrawalKind
from prodc.writer import add_principle

_TOML = """
[prodc]
needs = ["needs/*.yaml"]

[principles]
scopes = ["product", "design"]
"""

_EMPTY_YAML = "principles: []\n"


def _project(tmp_path: Path, body: str = _EMPTY_YAML) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(body, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


# --- loader ux- prefix guard ------------------------------------------------


def test_loader_rejects_unknown_ux_prefix(tmp_path: Path) -> None:
    yaml = """\
principles:
  - id: ux-nonexistent
    text: custom ux law
    revised_at: 2026-01-01
"""
    with pytest.raises(LoaderError, match="reserved for catalog entries"):
        load(_project(tmp_path, yaml))


def test_loader_allows_known_ux_prefix(tmp_path: Path) -> None:
    yaml = """\
principles:
  - id: ux-fitts
    text: interactive targets should be as large as possible
    revised_at: 2026-01-01
    sources:
      - kind: secondary
        url: https://lawsofux.com/en/fittss-law/
"""
    cfg = _project(tmp_path, yaml)
    model = load(cfg)
    assert any(p.id == "ux-fitts" for p in model.principles)


# --- from-catalog writer (via add_principle) --------------------------------


def test_from_catalog_writes_correct_id_scope_text(tmp_path: Path) -> None:

    cfg = _project(tmp_path)
    entry = next(e for e in UX_CATALOG if e.id == "ux-fitts")
    from prodc.model import Source
    from prodc.model import SourceKind as SK

    add_principle(
        cfg,
        entry.id,
        entry.text_template,
        file="needs/p.yaml",
        revised_at="2026-11-01",
        scope="design",
        sources=(Source(kind=SK.SECONDARY, locator=entry.url),),
        dry_run=False,
    )
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "ux-fitts")
    assert p.scope == "design"
    assert p.text == entry.text_template
    assert len(p.sources) == 1
    assert p.sources[0].kind == SourceKind.SECONDARY
    assert p.sources[0].locator == entry.url


def test_from_catalog_decline_marks_withdrawn_out_of_scope(tmp_path: Path) -> None:
    from prodc.writer import withdraw_principle

    cfg = _project(tmp_path)
    entry = next(e for e in UX_CATALOG if e.id == "ux-fitts")
    from prodc.model import Source

    add_principle(
        cfg,
        entry.id,
        entry.text_template,
        file="needs/p.yaml",
        revised_at="2026-11-01",
        scope="design",
        sources=(Source(kind=SourceKind.SECONDARY, locator=entry.url),),
        dry_run=False,
    )
    withdraw_principle(
        cfg,
        entry.id,
        reason="targets are small by design in our UI",
        date="2026-11-01",
        kind="out_of_scope",
        dry_run=False,
    )
    model = load(cfg)
    p = next(x for x in model.principles if x.id == "ux-fitts")
    assert p.withdrawn is not None
    assert p.withdrawn.kind == WithdrawalKind.OUT_OF_SCOPE
    assert p.withdrawn.reason == "targets are small by design in our UI"


# --- CLI integration --------------------------------------------------------


def test_cli_add_principle_from_catalog(tmp_path: Path) -> None:
    """End-to-end: the CLI writes the principle with correct scope and secondary source."""
    from prodc.cli import main

    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(_EMPTY_YAML, encoding="utf-8")
    rc = main(
        [
            "add",
            "principle",
            "--from-catalog",
            "ux-fitts",
            "--file",
            "needs/p.yaml",
            "--config",
            str(tmp_path / "prodc.toml"),
        ]
    )
    assert rc == 0
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    p = next((x for x in model.principles if x.id == "ux-fitts"), None)
    assert p is not None
    assert p.scope == "design"


def test_cli_add_principle_from_catalog_decline(tmp_path: Path) -> None:
    """--decline writes principle then immediately withdraws it out_of_scope."""
    from prodc.cli import main

    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(_EMPTY_YAML, encoding="utf-8")
    rc = main(
        [
            "add",
            "principle",
            "--from-catalog",
            "ux-fitts",
            "--decline",
            "not relevant to this UI",
            "--file",
            "needs/p.yaml",
            "--config",
            str(tmp_path / "prodc.toml"),
        ]
    )
    assert rc == 0
    cfg = Config.load(tmp_path / "prodc.toml")
    model = load(cfg)
    p = next((x for x in model.principles if x.id == "ux-fitts"), None)
    assert p is not None
    assert p.withdrawn is not None
    assert p.withdrawn.kind == WithdrawalKind.OUT_OF_SCOPE
