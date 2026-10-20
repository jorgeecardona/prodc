"""The vitest proof adapter (#91): `file.test.ts#title`, by existence, upgraded by junit."""

from __future__ import annotations

from pathlib import Path

from prodc.adapters import Adapter, VitestAdapter
from prodc.model import Principle, PrincipleState, ProofState
from prodc.status import principle_state

_TEST = """import { describe, it } from 'vitest'

describe('design', () => {
  it("no design CSS file uses the CSS named color 'purple'", () => {})
  it('dates render as dd/mm', () => {})
})
"""

_JUNIT = """<?xml version="1.0" encoding="UTF-8" ?>
<testsuites>
  <testsuite name="src/design/guard.test.ts" tests="2">
    <testcase classname="src/design/guard.test.ts"
              name="design &gt; no design CSS file uses the CSS named color 'purple'"/>
    <testcase classname="src/design/guard.test.ts" name="design &gt; dates render as dd/mm">
      <failure message="expected 2026-10-20 to be 20/10/2026" type="AssertionError"/>
    </testcase>
  </testsuite>
</testsuites>
"""

_PURPLE = "src/design/guard.test.ts#no design CSS file uses the CSS named color 'purple'"
_DATES = "src/design/guard.test.ts#dates render as dd/mm"


def _root(tmp_path: Path, junit: str | None = None) -> Path:
    (tmp_path / "src" / "design").mkdir(parents=True)
    (tmp_path / "src" / "design" / "guard.test.ts").write_text(_TEST, encoding="utf-8")
    if junit is not None:
        (tmp_path / "vitest-junit.xml").write_text(junit, encoding="utf-8")
    return tmp_path


def test_missing_file_is_broken(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path), None).resolve("src/nope.test.ts#x")
    assert r.state is ProofState.BROKEN and "no file" in r.detail


def test_missing_title_is_broken(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path), None).resolve("src/design/guard.test.ts#no such test")
    assert r.state is ProofState.BROKEN and "no such test" in r.detail


def test_locator_without_title_is_broken(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path), None).resolve("src/design/guard.test.ts")
    assert r.state is ProofState.BROKEN


def test_existing_test_without_report_is_declared_delivered(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path), None).resolve(_PURPLE)
    assert r.state is ProofState.DELIVERED and r.declared


def test_describe_path_locator_resolves(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path), None).resolve(
        "src/design/guard.test.ts#design > dates render as dd/mm"
    )
    assert r.state is ProofState.DELIVERED


def test_passing_report_is_real_delivered(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path, _JUNIT), "vitest-junit.xml").resolve(_PURPLE)
    assert r.state is ProofState.DELIVERED and not r.declared


def test_failing_report_is_pending_not_declared(tmp_path: Path) -> None:
    r = VitestAdapter(_root(tmp_path, _JUNIT), "vitest-junit.xml").resolve(_DATES)
    assert r.state is ProofState.PENDING and not r.declared
    assert r.detail == "junit: failing"


def test_skipped_report_stays_declared(tmp_path: Path) -> None:
    junit = _JUNIT.replace(
        '<failure message="expected 2026-10-20 to be 20/10/2026" type="AssertionError"/>',
        "<skipped/>",
    )
    r = VitestAdapter(_root(tmp_path, junit), "vitest-junit.xml").resolve(_DATES)
    assert r.state is ProofState.PENDING and r.declared


def test_failing_guard_makes_the_principle_violated(tmp_path: Path) -> None:
    # The #91 case: a red guard used to read ENFORCED by existence; now it reads VIOLATED.
    adapters: dict[str, Adapter] = {
        "fe": VitestAdapter(_root(tmp_path, _JUNIT), "vitest-junit.xml")
    }
    dates = Principle(id="P-1", text="dates are dd/mm", proofs=(f"fe:{_DATES}",))
    purple = Principle(id="P-2", text="no purple", proofs=(f"fe:{_PURPLE}",))
    assert principle_state(dates, adapters) is PrincipleState.VIOLATED
    assert principle_state(purple, adapters) is PrincipleState.ENFORCED


def test_config_builds_vitest_adapter(tmp_path: Path) -> None:
    from prodc.config import Config

    (tmp_path / "prodc.toml").write_text(
        '[prodc]\nfiles = ["n/*.yaml"]\n\n[proofs.fe]\nkind = "vitest"\nroot = "web"\n'
        'results = "vitest-junit.xml"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path / "prodc.toml")
    assert isinstance(cfg.adapters["fe"], VitestAdapter)
