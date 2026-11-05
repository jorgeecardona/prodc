"""The ``playwright`` proof kind: Playwright tests resolved against a junit report (#112)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.adapters import PlaywrightAdapter
from prodc.cli import main
from prodc.model import ProofState

_SOURCE = """\
import { test, expect } from "@playwright/experimental-ct-react";

test.describe("Order row", () => {
  test("fits on a phone", async ({ mount }) => {
    await expect(await mount(<Row />)).toHaveScreenshot("row.png");
  });
  test('shows the "total"', async ({ mount }) => {});
  test.skip(`is skipped ${1}`, async () => {});
});
"""


def _junit(mobile: str = "", laptop: str = "", prefix: str = "") -> str:
    """A report in Playwright's shape: one testsuite per file and project, name joined by U+203A."""
    case = '<testcase name="{p}Order row {sep} {t}" classname="OrderRow.visual.tsx" time="0.4">{x}</testcase>'
    suites = ""
    for project, extra in (("mobile", mobile), ("laptop", laptop)):
        cases = case.format(
            sep=chr(0x203A), p=f"[{project}] " if prefix else "", t="fits on a phone", x=extra
        )
        suites += (
            f'<testsuite name="OrderRow.visual.tsx" hostname="{project}" tests="1" '
            f'failures="0" skipped="0" errors="0">{cases}</testsuite>'
        )
    return f'<?xml version="1.0"?><testsuites name="">{suites}</testsuites>'


def _adapter(tmp_path: Path, report: str | None = None) -> PlaywrightAdapter:
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "OrderRow.visual.tsx").write_text(_SOURCE, encoding="utf-8")
    if report is not None:
        (tmp_path / "ct-junit.xml").write_text(report, encoding="utf-8")
    return PlaywrightAdapter(tmp_path, "ct-junit.xml", ["tests/**/*.visual.tsx"])


_LOC = "tests/OrderRow.visual.tsx#fits on a phone"
_FAIL = '<failure message="screenshot differs"/>'


def test_without_a_report_a_test_that_exists_is_declared(tmp_path: Path) -> None:
    r = _adapter(tmp_path).resolve(_LOC)
    assert (r.state, r.declared, r.detail) == (ProofState.DELIVERED, True, "test exists")


def test_a_passing_report_makes_it_real(tmp_path: Path) -> None:
    r = _adapter(tmp_path, _junit()).resolve(_LOC)
    assert (r.state, r.declared, r.detail) == (ProofState.DELIVERED, False, "junit: passed")


def test_one_failing_project_fails_the_test_and_names_it(tmp_path: Path) -> None:
    r = _adapter(tmp_path, _junit(mobile=_FAIL)).resolve(_LOC)
    assert (r.state, r.declared) == (
        ProofState.PENDING,
        False,
    )  # not declared: a guard reads VIOLATED
    assert r.detail == "junit: failing (mobile)"


def test_a_locator_can_pin_one_project(tmp_path: Path) -> None:
    ad = _adapter(tmp_path, _junit(mobile=_FAIL))
    assert ad.resolve("tests/OrderRow.visual.tsx#[laptop] fits on a phone").state is (
        ProofState.DELIVERED
    )
    bad = ad.resolve("tests/OrderRow.visual.tsx#[mobile] fits on a phone")
    assert bad.state is ProofState.PENDING and "[mobile]" in bad.detail


def test_the_project_prefix_the_reporter_can_add_is_understood(tmp_path: Path) -> None:
    ad = _adapter(tmp_path, _junit(mobile=_FAIL, prefix="x"))
    assert ad.resolve("tests/OrderRow.visual.tsx#[laptop] fits on a phone").detail == (
        "junit: passed [laptop]"
    )
    assert ad.resolve(_LOC).state is ProofState.PENDING


def test_the_full_describe_path_pins_a_test(tmp_path: Path) -> None:
    ad = _adapter(tmp_path, _junit())
    assert ad.resolve("tests/OrderRow.visual.tsx#Order row > fits on a phone").detail == (
        "junit: passed"
    )


def test_a_missing_file_or_title_is_broken(tmp_path: Path) -> None:
    ad = _adapter(tmp_path)
    assert ad.resolve("tests/Nope.visual.tsx#x").state is ProofState.BROKEN
    gone = ad.resolve("tests/OrderRow.visual.tsx#does not exist")
    assert gone.state is ProofState.BROKEN and "no test 'does not exist'" in gone.detail
    assert ad.resolve("tests/OrderRow.visual.tsx").state is ProofState.BROKEN  # no #title


def test_a_quote_in_the_title_is_found(tmp_path: Path) -> None:
    ad = _adapter(tmp_path)
    assert ad.resolve('tests/OrderRow.visual.tsx#shows the "total"').state is ProofState.DELIVERED


def test_inventory_lists_test_calls_and_not_describe_or_interpolated_titles(
    tmp_path: Path,
) -> None:
    assert _adapter(tmp_path).inventory() == [
        "tests/OrderRow.visual.tsx#fits on a phone",
        'tests/OrderRow.visual.tsx#shows the "total"',
    ]


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.ct]
kind = "{kind}"
results = "ct-junit.xml"
"""

_NEEDS = """
needs:
  - id: N-1
    text: When the order row is shown on a phone it fits the screen
    proofs: ["ct:tests/OrderRow.visual.tsx#fits on a phone"]
  - id: N-2
    text: fits on a phone
    expects: test
"""


@pytest.mark.parametrize("kind", ["playwright"])
def test_both_kind_names_work_through_the_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    _adapter(tmp_path, _junit(laptop=_FAIL))
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML.format(kind=kind), encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    cfg = str(tmp_path / "prodc.toml")
    assert main(["status", "--config", cfg, "--json"]) == 0
    needs = {n["id"]: n for n in json.loads(capsys.readouterr().out)["needs"]}
    assert needs["N-1"]["state"] == "pending" and "failing (laptop)" in needs["N-1"]["detail"][0]
    assert main(["suggest", "--config", cfg, "--json"]) == 0
    got = {s["locator"] for s in json.loads(capsys.readouterr().out) if s["need"] == "N-2"}
    assert "ct:tests/OrderRow.visual.tsx#fits on a phone" in got
