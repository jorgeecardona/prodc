"""The glossary (#72): what a term means globally or per client, and when two meanings collide."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config
from prodc.glossary import collisions, definition
from prodc.loader import LoaderError, load
from prodc.model import Term

_TOML = """
[prodc]
files = ["needs/*.yaml"]
"""

_FILE = """
glossary:
  - term: risk
    text: the chance a roast batch is lost
  - term: risk
    text: the chance an order ships late
    scope: client:acme
  - term: batch
    text: one roast of green coffee
  - term: batch
    text: One Roast Of  green coffee
    scope: client:acme
needs:
  - id: N-1
    text: When a roaster plans a day, they can see the risk
    client: acme
    terms: [risk, batch]
  - id: N-2
    text: When a roaster plans a day, they can see the batch
    terms: [batch]
"""


def _project(tmp_path: Path, body: str = _FILE) -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(body, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def test_collisions_ignore_case_and_whitespace_and_only_flag_a_different_meaning(
    tmp_path: Path,
) -> None:
    model = load(Config.load(Path(_project(tmp_path))))
    got = collisions(model.glossary)
    assert [(c.term, c.client) for c in got] == [("risk", "acme")]


def test_a_client_definition_wins_over_the_global_one() -> None:
    glossary = (
        Term("risk", "global meaning"),
        Term("risk", "acme meaning", "client:acme"),
    )
    assert definition(glossary, "risk", "acme") == glossary[1]
    assert definition(glossary, "risk", "globex") == glossary[0]
    assert definition(glossary, "risk", None) == glossary[0]
    assert definition(glossary, "nope", "acme") is None


def test_lint_warns_on_a_collision_and_is_otherwise_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    main(["lint", "--config", cfg])
    out = capsys.readouterr().out
    assert "risk: term means one thing globally and another for client acme" in out
    assert "batch:" not in out  # same meaning, different spelling: not a collision


def test_lint_errors_on_an_undefined_term(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(
        tmp_path,
        "glossary:\n  - term: risk\n    text: x\n    scope: client:acme\n"
        "needs:\n  - id: N-1\n    text: t\n    client: globex\n    terms: [risk]\n",
    )
    assert main(["lint", "--config", cfg]) == 1
    assert (
        "N-1: terms lists 'risk', which is not defined for client globex" in capsys.readouterr().out
    )


def test_a_duplicate_entry_for_one_scope_is_a_load_error(tmp_path: Path) -> None:
    cfg = _project(tmp_path, "glossary:\n  - {term: risk, text: a}\n  - {term: risk, text: b}\n")
    with pytest.raises(
        LoaderError, match="duplicate glossary entry for term 'risk' in scope global"
    ):
        load(Config.load(Path(cfg)))


def test_a_bad_scope_is_a_load_error(tmp_path: Path) -> None:
    cfg = _project(tmp_path, "glossary:\n  - {term: risk, text: a, scope: team:x}\n")
    with pytest.raises(LoaderError, match="must be 'global' or 'client:<id>'"):
        load(Config.load(Path(cfg)))


def test_the_report_renders_the_glossary_and_marks_the_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    assert main(["report", "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "## Glossary" in out
    assert (
        "| risk | client:acme | the chance an order ships late _(differs from the global meaning)_ |"
        in out
    )
    assert "| batch | global | one roast of green coffee |" in out


def test_terms_can_be_appended_with_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    assert main(["set", "N-2", "terms+=risk", "--config", cfg]) == 0
    capsys.readouterr()
    need = next(n for n in load(Config.load(Path(cfg))).needs if n.id == "N-2")
    assert need.terms == ("batch", "risk")
