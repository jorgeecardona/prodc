"""Role noun (#52): role declared once, who+client is the instance, ref validated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""


def _project(tmp_path: Path, needs: str) -> Config:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


_WITH_ROLES = """
roles:
  - id: owner
    text: the owner of the roastery
  - id: roaster
    text: roasts the day's coffee
needs:
  - id: N-1
    text: John can see the day's summary
    who: john
    client: sincerely
    role: owner
  - id: N-2
    text: Jacob can log a roast
    who: jacob
    client: sincerely
    role: roaster
"""


def test_roles_load_and_attach(tmp_path: Path) -> None:
    model = load(_project(tmp_path, _WITH_ROLES))
    assert {r.id for r in model.roles} == {"owner", "roaster"}
    by_id = {n.id: n for n in model.needs}
    assert by_id["N-1"].role == "owner" and by_id["N-1"].who == "john"


def test_unknown_role_ref_is_an_error(tmp_path: Path) -> None:
    needs = """
roles:
  - id: owner
    text: the owner
needs:
  - id: N-1
    text: a need
    role: roaster
"""
    with pytest.raises(LoaderError, match="role 'roaster' is not a known role id"):
        load(_project(tmp_path, needs))


def test_role_ref_checked_unconditionally(tmp_path: Path) -> None:
    # even with zero roles declared, a role ref must resolve (new field, no migration)
    needs = """
needs:
  - id: N-1
    text: a need
    role: owner
"""
    with pytest.raises(LoaderError, match="role 'owner' is not a known role id"):
        load(_project(tmp_path, needs))


def test_duplicate_role_id_is_an_error(tmp_path: Path) -> None:
    needs = """
roles:
  - id: owner
    text: one
  - id: owner
    text: two
"""
    with pytest.raises(LoaderError, match="duplicate role id"):
        load(_project(tmp_path, needs))


def test_one_person_several_roles(tmp_path: Path) -> None:
    # a person plays several roles — the role is per-need, not per person
    needs = """
roles:
  - id: owner
    text: the owner
  - id: sales
    text: takes orders
needs:
  - id: N-1
    text: John approves the budget
    who: john
    role: owner
  - id: N-2
    text: John takes a phone order
    who: john
    role: sales
"""
    model = load(_project(tmp_path, needs))
    by_id = {n.id: n for n in model.needs}
    assert by_id["N-1"].who == by_id["N-2"].who == "john"
    assert {by_id["N-1"].role, by_id["N-2"].role} == {"owner", "sales"}


def test_who_stays_free_text(tmp_path: Path) -> None:
    # who is NOT validated against roles — it's the person's name, not a role id
    model = load(_project(tmp_path, _WITH_ROLES))
    assert {n.who for n in model.needs} == {"john", "jacob"}


def test_status_json_lists_roles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, _WITH_ROLES)
    main(["status", "--config", str(cfg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in payload["roles"]} == {"owner", "roaster"}
    n1 = next(n for n in payload["needs"] if n["id"] == "N-1")
    assert n1["role"] == "owner"


def test_show_renders_role(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, _WITH_ROLES)
    main(["show", "N-1", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert "who: john — owner" in out


def test_set_role_via_writer(tmp_path: Path) -> None:
    from prodc.cli import main

    needs = """
roles:
  - id: owner
    text: the owner
needs:
  - id: N-1
    text: a need
"""
    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, needs)
    code = main(["set", "N-1", "role=owner", "--config", str(cfg)])
    assert code == 0
    assert "role: owner" in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
