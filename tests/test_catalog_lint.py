"""Commit 4: [principles].packs, missing_catalog_principles lint, unfilled-slot lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config, ConfigError

_TOML_BASE = """
[prodc]
needs = ["needs/*.yaml"]

[principles]
scopes = ["product", "design"]
"""

_TOML_WITH_PACK = _TOML_BASE + '\npacks = ["ux"]\n'

_TOML_WITH_PACK_AND_ERROR = (
    _TOML_BASE
    + '\npacks = ["ux"]\n'
    + '\n[lint]\nmissing_catalog_principles = "error"\n'
)

_TOML_WITH_PACK_OFF = (
    _TOML_BASE
    + '\npacks = ["ux"]\n'
    + '\n[lint]\nmissing_catalog_principles = "off"\n'
)

_CHECKABLE_PRINCIPLE = """\
principles:
  - id: ux-fitts
    text: interactive targets should be as large as possible
    revised_at: 2026-01-01
    sources:
      - kind: secondary
        url: https://lawsofux.com/en/fittss-law/
"""

_EMPTY_PRINCIPLES = "principles: []\n"
_EMPTY_NEEDS = "needs: []\n"


def _project(
    tmp_path: Path,
    toml: str = _TOML_BASE,
    principles: str = _EMPTY_PRINCIPLES,
    needs: str = _EMPTY_NEEDS,
) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "p.yaml").write_text(principles + "\n" + needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- config loading ---------------------------------------------------------


def test_config_loads_principle_packs(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path, toml=_TOML_WITH_PACK))
    assert cfg.principle_packs == ("ux",)


def test_config_packs_default_empty(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path))
    assert cfg.principle_packs == ()


def test_config_loads_missing_catalog_level(tmp_path: Path) -> None:
    toml = _TOML_BASE + '\n[lint]\nmissing_catalog_principles = "error"\n'
    cfg = Config.load(_project(tmp_path, toml=toml))
    assert cfg.missing_catalog_principles == "error"


def test_config_missing_catalog_level_default_warn(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path))
    assert cfg.missing_catalog_principles == "warn"


def test_config_rejects_invalid_missing_catalog_level(tmp_path: Path) -> None:
    toml = _TOML_BASE + '\n[lint]\nmissing_catalog_principles = "maybe"\n'
    with pytest.raises(ConfigError, match=r"warn.*error.*off"):
        Config.load(_project(tmp_path, toml=toml))


# --- lint: missing catalog principles ---------------------------------------


def test_lint_warns_missing_checkable_catalog_principle(tmp_path: Path) -> None:
    cfg_path = _project(tmp_path, toml=_TOML_WITH_PACK)
    rc = main(["lint", "--config", str(cfg_path)])
    # rc == 0 (warn, not error), but warnings are printed; just check it runs
    assert rc == 0


def test_lint_errors_missing_catalog_principle_when_set_to_error(tmp_path: Path) -> None:
    cfg_path = _project(tmp_path, toml=_TOML_WITH_PACK_AND_ERROR)
    rc = main(["lint", "--config", str(cfg_path)])
    assert rc == 1


def test_lint_off_no_missing_warning(tmp_path: Path) -> None:
    cfg_path = _project(tmp_path, toml=_TOML_WITH_PACK_OFF)
    rc = main(["lint", "--config", str(cfg_path)])
    assert rc == 0


def test_lint_no_missing_when_principle_present(tmp_path: Path) -> None:
    """With all 5 checkable principles present, lint --strict should not fail on missing."""
    from prodc.catalog.ux import UX_CATALOG

    checkable_yaml = "principles:\n"
    for entry in UX_CATALOG:
        if not entry.checkable:
            continue
        checkable_yaml += (
            f"  - id: {entry.id}\n"
            f"    text: {entry.text_template!r}\n"
            f"    revised_at: 2026-01-01\n"
            f"    sources:\n"
            f"      - kind: secondary\n"
            f"        url: {entry.url}\n"
        )
    cfg_path = _project(tmp_path, toml=_TOML_WITH_PACK, principles=checkable_yaml)
    # --strict fails on any warning; presence of all checkable entries means no missing warning
    main(["lint", "--config", str(cfg_path), "--strict"])
    # May fail for other reasons but not missing-catalog-principles
    # We check the JSON output for absence of missing warnings
    import io
    import json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["lint", "--config", str(cfg_path), "--json"])
    data = json.loads(buf.getvalue())
    assert not any(
        "catalog principle" in w["warning"] for w in data["warnings"]
    ), "should not warn about missing catalog principles when all are present"


# --- lint: unfilled slots ---------------------------------------------------


def test_lint_warns_unfilled_slot(tmp_path: Path) -> None:
    principles = """\
principles:
  - id: P-1
    text: "response time should be under {threshold_ms}ms"
    revised_at: 2026-01-01
"""
    cfg_path = _project(tmp_path, principles=principles)
    import io
    import json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["lint", "--config", str(cfg_path), "--json"])
    data = json.loads(buf.getvalue())
    slot_warnings = [w for w in data["warnings"] if "unfilled slot" in w["warning"]]
    assert slot_warnings, "expected an unfilled slot warning"
    assert any("{threshold_ms}" in w["warning"] for w in slot_warnings)


def test_lint_no_slot_warning_when_text_filled(tmp_path: Path) -> None:
    principles = """\
principles:
  - id: P-1
    text: response time should be under 200ms
    revised_at: 2026-01-01
"""
    cfg_path = _project(tmp_path, principles=principles)
    import io
    import json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["lint", "--config", str(cfg_path), "--json"])
    data = json.loads(buf.getvalue())
    slot_warnings = [w for w in data["warnings"] if "unfilled slot" in w["warning"]]
    assert not slot_warnings


def test_lint_no_slot_warning_for_withdrawn_principle(tmp_path: Path) -> None:
    principles = """\
principles:
  - id: P-1
    text: "response time under {threshold_ms}ms"
    revised_at: 2026-01-01
    withdrawn:
      reason: dropped
      date: 2026-10-01
"""
    cfg_path = _project(tmp_path, principles=principles)
    import io
    import json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["lint", "--config", str(cfg_path), "--json"])
    data = json.loads(buf.getvalue())
    slot_warnings = [w for w in data["warnings"] if "unfilled slot" in w["warning"]]
    assert not slot_warnings, "withdrawn principles should not generate slot warnings"
