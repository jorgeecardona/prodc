"""Suggest variant_of links (#56): the grouping matcher and its add into recurrence/lint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.dedup import variant_suggestions
from prodc.model import Need


def _n(nid: str, text: str, **kw: object) -> Need:
    return Need(id=nid, text=text, **kw)  # type: ignore[arg-type]


def test_suggests_cross_client_group() -> None:
    needs = [
        _n("A", "user can export orders to CSV", client="acme"),
        _n("B", "user can export orders to a CSV file", client="globex"),
        _n("C", "admin schedules the weekly roast", client="acme"),
    ]
    groups = variant_suggestions(needs, threshold=0.4)
    assert len(groups) == 1
    assert {m.id for m in groups[0].members} == {"A", "B"}


def test_same_client_is_not_a_variant_candidate() -> None:
    needs = [
        _n("A", "user can export orders to CSV", client="acme"),
        _n("B", "user can export orders to a CSV file", client="acme"),
    ]
    assert variant_suggestions(needs, threshold=0.4) == []


def test_already_linked_is_excluded() -> None:
    needs = [
        _n("A", "user can export orders to CSV", client="acme", variant_of="BASE"),
        _n("B", "user can export orders to a CSV file", client="globex"),
    ]
    assert variant_suggestions(needs, threshold=0.4) == []


def test_not_variant_of_suppresses() -> None:
    needs = [
        _n("A", "user can export orders to CSV", client="acme", not_variant_of=("B",)),
        _n("B", "user can export orders to a CSV file", client="globex"),
    ]
    assert variant_suggestions(needs, threshold=0.4) == []


def test_three_clients_form_one_group() -> None:
    needs = [
        _n("A", "user can export orders to CSV", client="acme"),
        _n("B", "user can export orders to a CSV file", client="globex"),
        _n("C", "user exports orders as CSV", client="initech"),
    ]
    groups = variant_suggestions(needs, threshold=0.3)
    assert len(groups) == 1 and len(groups[0].members) == 3


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[lint]
duplicate_threshold = 0.4
"""

_NEEDS = """
needs:
  - id: N-1
    text: user can export orders to CSV
    client: acme
  - id: N-2
    text: user can export orders to a CSV file
    client: globex
  - id: N-3
    text: admin schedules the weekly roast
    client: acme
"""


def _project(tmp_path: Path, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_loader_parses_not_variant_of(tmp_path: Path) -> None:
    from prodc.loader import load

    needs = """
needs:
  - id: N-1
    text: a need
    client: acme
    not_variant_of: [N-2]
  - id: N-2
    text: another need
    client: globex
"""
    cfg = Config.load(_project(tmp_path, needs))
    n1 = next(n for n in load(cfg).needs if n.id == "N-1")
    assert n1.not_variant_of == ("N-2",)


def test_recurrence_suggest_lists_groups(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    code = main(["recurrence", "--suggest", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and len(payload) == 1
    assert {m["id"] for m in payload[0]["members"]} == {"N-1", "N-2"}


def test_lint_surfaces_recurrence_unlinked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    code = main(["lint", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0  # unlinked recurrence is a warning, not a hard error
    assert "unlinked cross-client recurrence" in out


def test_recurrence_apply_creates_baseline_and_links(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main
    from prodc.loader import load

    cfg = _project(tmp_path)
    code = main(
        ["recurrence", "--suggest", "--apply", "--baseline-id", "B-ord",
         "--file", "needs/base.yaml", "--config", str(cfg)]
    )
    assert code == 0
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    assert "B-ord" in by_id and by_id["B-ord"].client is None  # client-agnostic baseline
    assert by_id["N-1"].variant_of == "B-ord"
    assert by_id["N-2"].variant_of == "B-ord"


def test_recurrence_apply_requires_baseline_id_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    code = main(["recurrence", "--suggest", "--apply", "--config", str(cfg)])
    assert code == 2
    assert "--baseline-id and --file" in capsys.readouterr().err


def test_recurrence_apply_dry_run_leaves_files_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    before = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    code = main(
        ["recurrence", "--suggest", "--apply", "--dry-run", "--baseline-id", "B-ord",
         "--file", "needs/base.yaml", "--config", str(cfg)]
    )
    assert code == 0
    assert (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8") == before
    assert not (tmp_path / "needs" / "base.yaml").exists()  # created file rolled back


def test_recurrence_apply_rolls_back_on_bad_baseline_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    before = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    # a baseline file outside the globs is refused -> the whole group must roll back
    code = main(
        ["recurrence", "--suggest", "--apply", "--baseline-id", "B-ord",
         "--file", "outside.yaml", "--config", str(cfg)]
    )
    assert code == 2
    assert (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8") == before  # members untouched
    assert not (tmp_path / "outside.yaml").exists()
