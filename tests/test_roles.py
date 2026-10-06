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


_ROSTER = """
roles:
  - id: sales
    text: takes the order
  - id: roaster
    text: roasts the day's coffee
  - id: owner
    text: owns the roastery
  - id: packer
    text: packs the orders
needs:
  - id: F-1
    text: the day's run from order to summary
    children: [N-1, N-2, N-3]
  - id: N-1
    text: sales takes a phone order
    who: sara
    client: sincerely
    role: sales
  - id: N-2
    text: jacob roasts the order
    who: jacob
    client: sincerely
    role: roaster
  - id: N-3
    text: john sees the day's summary
    who: john
    client: sincerely
    role: owner
  - id: N-4
    text: an unroled standalone need
    who: nobody
"""


def test_role_report_coverage_orphans_and_unroled(tmp_path: Path) -> None:
    from prodc.status import resolve, role_report

    model = load(_project(tmp_path, _ROSTER))
    results = resolve(list(model.needs), {})
    coverage, unroled = role_report(results, list(model.roles))
    by_role = {role.id: rsum for role, rsum in coverage}
    # every declared role appears, including the one no need plays (orphan: total 0)
    assert set(by_role) == {"sales", "roaster", "owner", "packer"}
    assert by_role["sales"].total == 1
    assert by_role["packer"].total == 0  # orphan role — on the roster, no need yet
    # N-4 has a who but no role -> unroled
    assert [r.need.id for r in unroled] == ["N-4"]


def test_handoffs_derived_from_ordered_cross_role_flow(tmp_path: Path) -> None:
    from prodc.status import handoffs

    model = load(_project(tmp_path, _ROSTER))
    hos = handoffs(list(model.needs))
    # F-1's ordered children cross sales -> roaster -> owner: two handoffs, in order
    assert [(h.from_role, h.to_role) for h in hos] == [("sales", "roaster"), ("roaster", "owner")]
    assert [(h.from_need.id, h.to_need.id) for h in hos] == [("N-1", "N-2"), ("N-2", "N-3")]
    assert hos[0].flow.id == "F-1"


def test_handoffs_ignores_same_role_and_missing_role(tmp_path: Path) -> None:
    from prodc.status import handoffs

    needs = """
roles:
  - id: roaster
    text: roasts
needs:
  - id: F-1
    text: two roaster steps then an unroled one
    children: [N-1, N-2, N-3]
  - id: N-1
    text: first roast step
    role: roaster
  - id: N-2
    text: second roast step
    role: roaster
  - id: N-3
    text: an unroled step
    who: someone
"""
    model = load(_project(tmp_path, needs))
    # same role (N-1->N-2) and a missing role (N-2->N-3) both yield no handoff
    assert handoffs(list(model.needs)) == []


def test_status_text_shows_roster_and_handoffs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, _ROSTER)
    main(["status", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert "roles (the roster" in out
    assert "orphan role" in out  # packer, no need plays it
    assert "handoffs" in out
    assert "sales → roaster" in out


def test_status_json_handoffs_orphan_and_unroled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, _ROSTER)
    main(["status", "--config", str(cfg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    roles = {r["id"]: r for r in payload["roles"]}
    assert roles["packer"]["orphan"] is True
    assert roles["sales"]["orphan"] is False
    assert payload["unroled"] == ["N-4"]
    assert payload["handoffs"] == [
        {
            "flow": "F-1",
            "from_role": "sales",
            "to_role": "roaster",
            "from_need": "N-1",
            "to_need": "N-2",
        },
        {
            "flow": "F-1",
            "from_role": "roaster",
            "to_role": "owner",
            "from_need": "N-2",
            "to_need": "N-3",
        },
    ]


def test_add_role_command_writes_and_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, "needs:\n  - id: N-1\n    text: a need\n")
    code = main(
        [
            "add",
            "role",
            "owner",
            "--text",
            "owns it",
            "--file",
            "needs/roles.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    model = load(Config.load(cfg))
    assert {r.id for r in model.roles} == {"owner"}


def test_add_need_without_who_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = tmp_path / "prodc.toml"
    _project(tmp_path, "needs:\n  - id: N-1\n    text: a need\n")
    code = main(
        ["add", "need", "N-2", "--text", "t", "--file", "needs/a.yaml", "--config", str(cfg)]
    )
    assert code == 2
    assert "requires --who" in capsys.readouterr().err
