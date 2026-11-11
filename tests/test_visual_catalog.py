"""The visual pack: WCAG 2.2 and Material 3 rules, and a palette a person signs off."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.catalog import VISUAL_CATALOG, find
from prodc.cli import main
from prodc.config import Config
from prodc.loader import LoaderError, load


def test_entries_are_the_visual_pack_with_visual_scope() -> None:
    assert [e.id for e in VISUAL_CATALOG] == [
        "visual-contrast-text",
        "visual-contrast-ui",
        "visual-not-color-alone",
        "visual-color-roles",
        "visual-palette-chosen",
    ]
    for e in VISUAL_CATALOG:
        assert e.pack == "visual" and e.scope == "visual"
        assert e.url.startswith("https://")


def test_contrast_recipe_carries_the_reference_vectors() -> None:
    # The math is easy to get subtly wrong; the snippet must test itself against known ratios
    # and must fail on a colour it cannot parse, not skip it.
    entry = find("visual-contrast-text")
    assert entry is not None and entry.recipe is not None
    snippet = entry.recipe.snippet
    for vector in ('contrast("#000", "#fff")', '"#767676"', '"#777777"', "0.04045", "toThrow"):
        assert vector in snippet
    assert "composite(" in snippet  # rgba() tokens are painted over the background first


def test_every_recipe_has_a_non_vacuous_check() -> None:
    for e in VISUAL_CATALOG:
        if e.recipe is not None:
            assert "expect(" in e.recipe.snippet
            assert e.recipe.proof_locator_hint.startswith("vitest:src/design/")


def test_palette_is_a_sign_off_with_slots() -> None:
    entry = find("visual-palette-chosen")
    assert entry is not None
    assert entry.sign_off and not entry.checkable and entry.recipe is None
    for slot in ("{palette}", "{who}", "{N}"):
        assert slot in entry.text_template


_TOML = '[prodc]\nneeds = ["needs/*.yaml"]\n[principles]\nscopes = ["product", "visual"]\n'


def _project(tmp_path: Path, toml: str = _TOML, yaml: str = "principles: []\n") -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(yaml, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_from_catalog_writes_visual_scope_and_prints_sign_off_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    rc = main(
        [
            "add",
            "principle",
            "--from-catalog",
            "visual-palette-chosen",
            "--file",
            "needs/p.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "accept:<who>@<date>" in out and "primary source" in out
    p = next(p for p in load(Config.load(cfg)).principles if p.id == "visual-palette-chosen")
    assert p.scope == "visual"


def test_from_catalog_refuses_an_undeclared_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, toml='[prodc]\nneeds = ["needs/*.yaml"]\n')
    rc = main(
        [
            "add",
            "principle",
            "--from-catalog",
            "visual-contrast-text",
            "--file",
            "needs/p.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert rc == 2
    assert "add it to [principles].scopes" in capsys.readouterr().err


def test_lint_asks_for_checkable_and_sign_off_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, toml=_TOML + 'packs = ["visual"]\n')
    main(["lint", "--config", str(cfg)])
    out = capsys.readouterr()
    text = out.out + out.err
    for e in VISUAL_CATALOG:
        assert e.id in text


def test_decline_counts_as_present(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path, toml=_TOML + 'packs = ["visual"]\n')
    rc = main(
        [
            "add",
            "principle",
            "--from-catalog",
            "visual-color-roles",
            "--decline",
            "no design system yet",
            "--file",
            "needs/p.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    main(["lint", "--config", str(cfg)])
    out = capsys.readouterr()
    assert "'visual-color-roles'" not in out.out + out.err


def test_a_made_up_visual_id_is_refused(tmp_path: Path) -> None:
    yaml = "principles:\n  - id: visual-mine\n    text: t\n    revised_at: 2026-01-01\n    scope: visual\n"
    with pytest.raises(LoaderError, match="'visual-' prefix is reserved"):
        load(Config.load(_project(tmp_path, yaml=yaml)))
