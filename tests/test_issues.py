"""Issues read from a docs/issues folder join the board through needs: and sources: (#36)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main
from prodc.issues import read_issues

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
issues = ["docs/issues/*.md"]
[proofs.acc]
kind = "accept"
[sources.gitlab]
kind = "command"
command = ["true"]
"""

_NEEDS = """
needs:
  - id: N-1
    text: a delivered want
    proofs: ["acc:signed"]
  - id: N-2
    text: a want with no proof yet
"""


def _issue(title: str, **fm: str) -> str:
    """An issue file; ``status`` and ``area`` default to what the store requires."""
    fields = {"title": f'"{title}"', "status": "open", "area": "cli", **fm}
    head = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"---\n{head}\n---\n\nbody\n"


def _project(tmp_path: Path, issues: dict[str, str]) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    for name, text in issues.items():
        (tmp_path / "docs" / "issues" / name).write_text(text, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def test_read_issues_parses_front_matter_and_skips_the_rest(tmp_path: Path) -> None:
    _project(
        tmp_path,
        {
            "01-01-2026-a.md": _issue("A", status="done", needs="[N-1]", area="cli"),
            "02-01-2026-b.md": _issue("B", needs="N-2", sources='["gitlab:#7"]'),
            "03-01-2026-bare.md": "no front matter here\n",
            "04-01-2026-old.md": _issue("Old", status="closed"),
            "README.md": "# index\n",
            "config.toml": "x = 1\n",
        },
    )
    folder = read_issues(tmp_path, ["docs/issues/*"])
    a, b = folder.issues
    assert (a.id, a.title, a.status, a.needs, a.area, a.is_closed) == (
        "01-01-2026-a",
        "A",
        "done",
        ("N-1",),
        "cli",
        True,
    )
    assert (b.status, b.needs, b.sources, b.is_closed) == ("open", ("N-2",), ("gitlab:#7",), False)
    bare, old = folder.skipped
    assert bare.startswith("03-01-2026-bare.md: no YAML front matter")
    assert "status 'closed' is not a status here" in old and "`done`" in old


def test_issues_command_lists_issues_with_need_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(
        tmp_path,
        {
            "a.md": _issue("Do the thing", needs="[N-2]"),
            "b.md": _issue("Engineering only"),
        },
    )
    assert main(["issues", "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "N-2:HOLE" in out and "Engineering only  [no need]" in out
    assert "issues: 2, serving no need: 1" in out
    assert main(["issues", "--config", cfg, "--need", "N-2", "--json"]) == 0
    assert [i["id"] for i in json.loads(capsys.readouterr().out)] == ["a"]


def test_issues_command_needs_the_config_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, {})
    (tmp_path / "docs" / "issues").rmdir()
    (tmp_path / "docs").rmdir()
    (tmp_path / "prodc.toml").write_text(
        _TOML.replace('issues = ["docs/issues/*.md"]\n', ""), "utf-8"
    )
    assert main(["issues", "--config", cfg]) == 2
    assert "no issue register" in capsys.readouterr().err


def test_without_globs_the_register_is_found_from_the_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, {"01-01-2026-a.md": _issue("A", needs="[N-2]")})
    (tmp_path / "prodc.toml").write_text(
        _TOML.replace('issues = ["docs/issues/*.md"]\n', ""), "utf-8"
    )
    assert main(["issues", "--config", cfg, "--json"]) == 0
    assert [i["id"] for i in json.loads(capsys.readouterr().out)] == ["01-01-2026-a"]


def _lint(cfg: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["lint", "--config", cfg])
    return code, capsys.readouterr().out


def test_lint_finds_the_five_issue_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(
        tmp_path,
        {
            "no-need.md": _issue("floating"),
            "typo.md": _issue("typo", needs="[N-99]"),
            "closed-unproven.md": _issue("closed", status="done", needs="[N-2]"),
            "proven-open.md": _issue("open", needs="[N-1]"),
            "bare.md": "nothing\n",
        },
    )
    code, out = _lint(cfg, capsys)
    assert code == 1  # the unknown need is an error
    assert "no-need: issue serves no need" in out
    assert "ERROR  typo: needs names 'N-99', which is not a need" in out
    assert "closed-unproven: closed, but N-2 is HOLE: closed but unproven" in out
    assert "proven-open: open, but every need it serves is DELIVERED (N-1): proven but open" in out
    assert "1 issue file(s) have no front matter" in out


def test_a_closed_issue_on_a_delivered_need_is_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, {"ok.md": _issue("ok", status="done", needs="[N-1]")})
    code, out = _lint(cfg, capsys)
    assert code == 0 and "ok:" not in out


def test_show_lists_the_issues_serving_a_need(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, {"a.md": _issue("Do the thing", status="in-progress", needs="[N-2]")})
    assert main(["show", "N-2", "--config", cfg]) == 0
    assert "- a [in-progress] Do the thing" in capsys.readouterr().out
    assert main(["show", "N-2", "--config", cfg, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["issues"][0]["id"] == "a"


def test_issue_list_shows_need_state_and_issues_is_a_deprecated_alias(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, {"a.md": _issue("Do the thing", needs="[N-1, N-2]")})
    assert main(["issue", "list", "--config", cfg, "--json"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["need_states"] == {"N-1": "DELIVERED", "N-2": "HOLE"}
    assert main(["issue", "list", "--config", cfg, "--need", "N-9"]) == 0
    assert "issues: 0" in capsys.readouterr().out
    assert main(["issues", "--config", cfg]) == 0
    out = capsys.readouterr()
    assert "N-1:DELIVERED" in out.out
    assert "deprecated; use `prodc issue list`" in out.err


def test_only_an_open_issue_with_no_need_warns_and_repeats_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(
        tmp_path,
        {
            "a.md": _issue("first"),
            "b.md": _issue("second"),
            "done.md": _issue("old work", status="done"),
        },
    )
    _, out = _lint(cfg, capsys)
    assert "2 ids: issue serves no need" in out
    assert "done: issue serves no need" not in out
    main(["lint", "--config", cfg, "--all-warnings"])
    full = capsys.readouterr().out
    assert "a: issue serves no need" in full or "first: issue serves no need" in full
    assert "old work" not in full and "done: issue serves no need" not in full
