"""`prodc report`: the board rendered as a readable markdown document."""

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
"""

_FEATURE = """
Feature: orders
  @implemented
  Scenario: Past due orders are highlighted
    Given an order
    Then it is highlighted
"""

_NEEDS = """
who: jordan
needs:
  - id: N-1
    text: see past-due orders at a glance
    must: true
    sources:
      - kind: interview
        who: Jordan
        date: 2026-09-20
        quote: "I lose them"
    proofs:
      - "web:orders.feature#Past due orders are highlighted"
  - id: N-2
    text: export the run sheet
    sources:
      - kind: artifact
        locator: issues.md#N-2
        date: 2026-09-21
  - id: N-3
    text: implement a settings page
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "features" / "orders.feature").write_text(_FEATURE, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_report_renders_summary_needs_and_open_questions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["report", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "# " in out and "product status" in out
    assert "1 of 3 delivered" in out  # one proof passes, three leaves
    assert "### jordan" in out
    assert "N-1" in out and "DELIVERED" in out
    assert "## Open questions" in out
    assert "N-3" in out and "no evidence" in out  # the opinion surfaces


def test_report_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    dest = tmp_path / "out" / "status.md"
    code = main(["report", "--config", str(cfg), "--output", str(dest)])
    assert code == 0
    assert "wrote report to" in capsys.readouterr().out
    assert dest.exists() and "product status" in dest.read_text(encoding="utf-8")


def test_report_client_scope_in_heading(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["report", "--config", str(_project(tmp_path)), "--client", "jordan"])
    out = capsys.readouterr().out
    assert code == 0
    assert ": jordan: product status" in out


_NEEDS_PD = """
principles:
  - id: P-1
    text: local-first always
    revised_at: 2026-10-15
needs:
  - id: N-1
    text: store a recording
decisions:
  - id: D-1
    text: store as FLAC on disk
    needs: [N-1]
    alternatives: [WAV]
    principles: [P-1]
    decided_at: 2026-10-16
"""


def test_report_renders_principles_and_decisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS_PD, encoding="utf-8")
    code = main(["report", "--config", str(tmp_path / "prodc.toml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "## Principles" in out and "P-1: local-first always" in out
    assert "## Decisions" in out and "D-1: store as FLAC on disk" in out
    assert "WAV" in out  # the rejected alternative is shown


def test_report_title_replaces_the_heading_and_keeps_the_stamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--config", str(_project(tmp_path)), "--title", "Weekly review"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "# Weekly review"
    assert lines[2].startswith("_20")  # the date stamp is still there


def test_report_only_open_is_the_brief_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--config", str(_project(tmp_path)), "--only-open"]) == 0
    out = capsys.readouterr().out
    assert "## Open questions" in out and "`N-3`" in out
    assert "## Needs" not in out and "delivered**" not in out


def test_report_hide_empty_drops_the_explainer_and_an_empty_open_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    main(["report", "--config", str(cfg)])
    assert "is an honest gap" in capsys.readouterr().out
    # with every need delivered and sourced, nothing is open
    (tmp_path / "needs" / "a.yaml").write_text(
        "who: jordan\nneeds:\n  - id: N-1\n    text: see past-due orders\n    sources:\n"
        '      - kind: interview\n        who: Jordan\n        date: 2026-09-20\n        quote: "x"\n'
        '    proofs:\n      - "web:orders.feature#Past due orders are highlighted"\n',
        encoding="utf-8",
    )
    assert main(["report", "--config", str(cfg), "--hide-empty"]) == 0
    out = capsys.readouterr().out
    assert "is an honest gap" not in out and "## Open questions" not in out


def test_report_flags_are_md_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["report", "--config", str(_project(tmp_path)), "--format", "html", "--title", "x"])
    assert code == 2
    assert "md only" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("locator", "expected"),
    [
        ("https://gitlab.com/g/p/-/issues/12", "ticket"),
        ("PROJ-123", "ticket"),
        ("https://gitlab.com/g/p/-/merge_requests/7", "merge request"),
        ("https://acme.slack.com/archives/C01/p123", "message"),
        ("mailto:a@b.com", "email"),
        ("https://acme.canny.io/requests/42", "post"),
        ("notes/interview-1.md", None),
        (None, None),
    ],
)
def test_source_type_is_read_from_the_locator(locator: str | None, expected: str | None) -> None:
    from prodc.report import source_type

    assert source_type(locator) == expected


def test_display_title_titles_identifiers_and_keeps_plain_names() -> None:
    from prodc.report import display_title

    assert display_title("safety-analyst") == "Safety analyst"
    assert display_title("master_description") == "Master description"
    assert display_title("jordan") == "jordan"


def test_report_signal_names_the_source_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main_cfg = _project(tmp_path)
    (tmp_path / "needs" / "a.yaml").write_text(
        "who: night-shift\nneeds:\n  - id: N-9\n    text: see past-due orders\n    sources:\n"
        "      - kind: secondary\n        locator: https://gitlab.com/g/p/-/issues/12\n"
        "        date: 2026-09-21\n",
        encoding="utf-8",
    )
    assert main(["report", "--config", str(main_cfg)]) == 0
    out = capsys.readouterr().out
    assert "| secondary (ticket) |" in out
    assert "### Night shift" in out


def test_report_goal_and_only_must_scope_the_needs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    (tmp_path / "needs" / "a.yaml").write_text(
        "who: jordan\ngoals:\n  - id: G-1\n    text: fewer lost orders\nneeds:\n"
        "  - id: N-1\n    text: first need\n    must: true\n    goal: G-1\n"
        "  - id: N-2\n    text: second need\n    goal: G-1\n"
        "  - id: N-3\n    text: third need\n    must: true\n",
        encoding="utf-8",
    )
    assert main(["report", "--config", str(cfg), "--goal", "G-1", "--only-must"]) == 0
    out = capsys.readouterr().out
    assert "N-1" in out
    assert "N-2" not in out and "N-3" not in out
