"""Flow step vocabulary (#90 follow-up): [flows].steps config, the load-time membership
error, and the flow_step_warnings hygiene lint (never-terminal / out-of-order / mixed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.config import Config, ConfigError
from prodc.loader import LoaderError, load
from prodc.model import Child, Need
from prodc.status import flow_step_warnings

_TOML = """
[prodc]
needs = ["needs/*.yaml"]

[flows]
steps = ["trigger", "act", "conclude"]
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = "needs: []\n") -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- config (#90) -----------------------------------------------------------


def test_flow_steps_default_is_empty_and_terminal_none(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path, toml="[prodc]\nneeds = [\"needs/*.yaml\"]\n"))
    assert cfg.flow_steps == ()
    assert cfg.terminal_step is None  # no vocab → nothing is terminal


def test_flow_steps_parsed_ordered_and_terminal_is_last(tmp_path: Path) -> None:
    cfg = Config.load(_project(tmp_path))
    assert cfg.flow_steps == ("trigger", "act", "conclude")
    assert cfg.terminal_step == "conclude"  # last entry, the single definition of terminal


def test_flow_steps_empty_list_rejected(tmp_path: Path) -> None:
    toml = "[prodc]\nneeds = [\"needs/*.yaml\"]\n\n[flows]\nsteps = []\n"
    with pytest.raises(ConfigError, match=r"\[flows\].steps must list at least one step"):
        Config.load(_project(tmp_path, toml=toml))


def test_flow_steps_duplicate_rejected(tmp_path: Path) -> None:
    toml = "[prodc]\nneeds = [\"needs/*.yaml\"]\n\n[flows]\nsteps = [\"act\", \"act\"]\n"
    with pytest.raises(ConfigError, match="must not repeat a step"):
        Config.load(_project(tmp_path, toml=toml))


# --- loader membership = hard error (#90) -----------------------------------


def test_undeclared_step_is_load_error(tmp_path: Path) -> None:
    needs = """
needs:
  - id: F-1
    text: a flow
    children: [{id: US-1, step: conlcude}]
  - id: US-1
    text: a step
"""
    with pytest.raises(LoaderError, match="step 'conlcude' is not declared in"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_declared_step_loads(tmp_path: Path) -> None:
    needs = """
needs:
  - id: F-1
    text: a flow
    children: [{id: US-1, step: trigger}, {id: US-2, step: conclude}]
  - id: US-1
    text: a
  - id: US-2
    text: b
"""
    model = load(Config.load(_project(tmp_path, needs=needs)))
    flow = next(n for n in model.needs if n.id == "F-1")
    assert [c.step for c in flow.children] == ["trigger", "conclude"]


def test_no_vocab_lets_any_step_pass(tmp_path: Path) -> None:
    toml = "[prodc]\nneeds = [\"needs/*.yaml\"]\n"
    needs = """
needs:
  - id: F-1
    text: a flow
    children: [{id: US-1, step: whatever}]
  - id: US-1
    text: a
"""
    model = load(Config.load(_project(tmp_path, toml=toml, needs=needs)))
    assert model.needs[0].children[0].step == "whatever"  # free text, unchecked


# --- lint: shape of the journey (#90) ---------------------------------------

_STEPS = ("trigger", "act", "conclude")


def test_lint_silent_without_vocabulary() -> None:
    needs = [Need(id="F-1", text="f", children=(Child("A", "trigger"),)), Need(id="A", text="a")]
    assert flow_step_warnings(needs, ()) == []


def test_lint_exempts_flow_with_no_stepped_edges() -> None:
    needs = [Need(id="F-1", text="f", children=(Child("A"), Child("B")))]
    assert flow_step_warnings(needs, _STEPS) == []  # a plain flow, not a use case


def test_lint_warns_when_no_terminal_step() -> None:
    needs = [Need(id="F-1", text="f", children=(Child("A", "trigger"), Child("B", "act")))]
    warns = flow_step_warnings(needs, _STEPS)
    assert any(nid == "F-1" and "terminal step 'conclude'" in m for nid, m in warns)


def test_lint_terminal_step_names_the_configured_word() -> None:
    needs = [Need(id="F-1", text="f", children=(Child("A", "start"),))]
    warns = flow_step_warnings(needs, ("start", "done"))
    assert any("terminal step 'done'" in m for _, m in warns)  # not hardcoded "conclude"


def test_lint_warns_on_out_of_order_steps() -> None:
    needs = [
        Need(id="F-1", text="f", children=(Child("A", "act"), Child("B", "trigger"), Child("C", "conclude")))
    ]
    warns = flow_step_warnings(needs, _STEPS)
    assert any("out of order" in m for _, m in warns)


def test_lint_warns_on_mixed_bare_and_stepped() -> None:
    needs = [
        Need(id="F-1", text="f", children=(Child("A", "trigger"), Child("B"), Child("C", "conclude")))
    ]
    warns = flow_step_warnings(needs, _STEPS)
    assert any("has no step while siblings do" in m for _, m in warns)


def test_lint_clean_journey_is_silent() -> None:
    needs = [
        Need(id="F-1", text="f", children=(Child("A", "trigger"), Child("B", "act"), Child("C", "conclude")))
    ]
    assert flow_step_warnings(needs, _STEPS) == []


def test_lint_command_surfaces_flow_step_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: F-1
    text: a flow that never ends
    children: [{id: US-1, step: trigger}, {id: US-2, step: act}]
  - id: US-1
    text: a
  - id: US-2
    text: b
"""
    code = main(["lint", "--config", str(_project(tmp_path, needs=needs))])
    out = capsys.readouterr().out
    assert code == 0  # a shape warning is not a hard error
    assert "terminal step 'conclude'" in out
