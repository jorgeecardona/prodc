"""CLI board, end to end: gap summary line, warrant column, and the gate exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]
"""

_NEEDS = """
who: jordan
needs:
  - id: D-1
    text: a delivered need
    sources:
      - kind: interview
        who: John
        quote: "I need this"
        date: 2026-01-01
    proofs: ["web:orders.feature#Done"]
  - id: H-1
    text: a must-have with no proof
    must: true
    sources:
      - kind: artifact
        locator: issues.md#H-1
        date: 2026-01-01
  - id: O-1
    text: an unsourced opinion
"""

_FEATURE = """
Feature: orders
  @implemented
  Scenario: Done
    Given a thing
    Then it works

  Scenario: Unclaimed extra
    Given another thing
    Then no need references me
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_board_shows_summary_and_warrant(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0  # a must-HOLE is an honest gap, never a failure
    assert "gaps:" in out and "coverage 1/3" in out  # leading gap-count line (#2)
    assert "WARRANT" in out  # the warrant column header (#3)
    assert "interview:John" in out  # strongest warrant for D-1
    assert "opinion" in out  # O-1's warrant
    assert "legend:" in out  # glyph legend (#10)
    # provenance mix (#11): 1 interview, 1 artifact, 0 internal, 1 opinion
    assert "provenance:" in out and "1 interview" in out and "1 artifact" in out


def test_json_has_summary_and_grounds_warrant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    code = main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["total"] == 3 and payload["summary"]["must_hole"] == 1
    d1 = next(n for n in payload["needs"] if n["id"] == "D-1")
    assert d1["grounds"] == "delivered" and d1["warrant"] == "interview:John"


def test_min_coverage_gate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path)), "--min-coverage", "0.9"])
    capsys.readouterr()
    assert code == 1  # coverage is 1/3, below 0.9


def test_strict_fails_on_opinion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--config", str(_project(tmp_path)), "--strict"])
    capsys.readouterr()
    assert code == 1  # O-1 has no source


def test_orphan_report_lists_unclaimed_scenarios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0  # orphans alone don't fail without a gate
    assert "orphan proofs (claimed by no need): 1" in out
    assert "web:orders.feature#Unclaimed extra" in out
    assert "web:orders.feature#Done" not in out.split("orphan proofs")[1]  # Done is claimed


def test_max_orphans_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = str(_project(tmp_path))
    assert main(["status", "--config", p, "--max-orphans", "0"]) == 1  # 1 orphan > 0
    capsys.readouterr()
    assert main(["status", "--config", p, "--max-orphans", "1"]) == 0  # 1 orphan <= 1
    capsys.readouterr()


def test_orphans_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["orphans"] == 1
    assert payload["orphans"]["web"] == ["orders.feature#Unclaimed extra"]


def test_show_single_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "D-1", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "D-1" in out and "a delivered need" in out
    assert "grounds: DELIVERED" in out and "interview:John" in out
    assert "I need this" in out  # the source quote


def test_show_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    main(["show", "D-1", "--config", str(_project(tmp_path)), "--json"])
    p = json.loads(capsys.readouterr().out)
    assert p["id"] == "D-1" and p["warrant"] == "interview:John"
    assert p["sources"][0]["kind"] == "interview" and p["sources"][0]["who"] == "John"


def test_show_unknown_need_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "NOPE", "--config", str(_project(tmp_path))])
    capsys.readouterr()
    assert code == 2


def test_portfolio_rolls_up_many_repos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _project(tmp_path / "alpha")
    b = _project(tmp_path / "beta")
    code = main(["portfolio", str(a), str(b)])
    out = capsys.readouterr().out
    assert code == 0
    assert "alpha" in out and "beta" in out
    assert "33%" in out  # each repo is 1/3 delivered


def test_portfolio_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    main(["portfolio", str(_project(tmp_path / "alpha")), "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["repo"] == "alpha" and rows[0]["total"] == 3
    assert rows[0]["provenance"]["interview"] == 1


def test_portfolio_bad_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["portfolio", str(tmp_path / "nope.toml")])
    capsys.readouterr()
    assert code == 2


def test_diff_no_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    toml = str(_project(tmp_path))
    main(["status", "--config", toml, "--json"])
    snap = tmp_path / "snap.json"
    snap.write_text(capsys.readouterr().out, encoding="utf-8")
    main(["diff", str(snap), "--config", toml])
    assert "no changes" in capsys.readouterr().out


def test_diff_reports_new_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    toml = str(_project(tmp_path))
    main(["status", "--config", toml, "--json"])
    snap = tmp_path / "snap.json"
    snap.write_text(capsys.readouterr().out, encoding="utf-8")
    # add a brand-new need, then diff against the snapshot
    (tmp_path / "needs" / "a.yaml").write_text(
        _NEEDS + "  - id: X-9\n    text: a newly added need\n", encoding="utf-8"
    )
    code = main(["diff", str(snap), "--config", toml])
    out = capsys.readouterr().out
    assert code == 0
    assert "new" in out and "X-9" in out


def test_proxy_source_kind_warrant(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "who: me\nneeds:\n  - id: P-1\n    text: a proxy-sourced need\n"
        "    sources:\n      - kind: proxy\n        who: me\n        date: 2026-01-01\n",
        encoding="utf-8",
    )
    toml = str(tmp_path / "prodc.toml")
    main(["status", "--config", toml, "--json"])
    p = json.loads(capsys.readouterr().out)
    assert p["needs"][0]["warrant"] == "proxy"  # interview > artifact > proxy > internal
    main(["status", "--config", toml])
    assert "1 proxy" in capsys.readouterr().out  # provenance line counts proxy


_BRIEF_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_BRIEF_NEEDS = """
needs:
  - id: B-1
    text: shared baseline, proven nowhere
  - id: B-2
    text: shared baseline acme overrides
  - id: B-2@acme
    text: acme wants it their way
    client: acme
    variant_of: B-2
    sources:
      - kind: interview
        who: Ana
        quote: "we need this"
        date: 2026-02-01
    proofs: []
  - id: A-1
    text: acme-only opinion
    client: acme
  - id: X-1
    text: other client's need
    client: globex
"""


def _brief_project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_BRIEF_TOML, encoding="utf-8")
    (tmp_path / "needs" / "b.yaml").write_text(_BRIEF_NEEDS, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_brief_scopes_to_client_opinions_and_holes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    code = main(["brief", "acme", "--config", str(_brief_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    ids = {o["id"] for o in payload["open"]}
    # acme sees: B-1 (shared baseline, HOLE), B-2@acme (its variant, HOLE), A-1 (its opinion).
    # B-2 baseline is overridden by B-2@acme, and X-1 belongs to globex — both excluded.
    assert ids == {"B-1", "B-2@acme", "A-1"}
    a1 = next(o for o in payload["open"] if o["id"] == "A-1")
    assert a1["opinion"] is True


def test_brief_unknown_client_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["brief", "nobody", "--config", str(_brief_project(tmp_path))])
    assert code == 2
    assert "no needs for client 'nobody'" in capsys.readouterr().err
