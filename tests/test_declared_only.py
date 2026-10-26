"""``lint --strict`` fails on a must-have DELIVERED only by declared proofs (#103)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """\
[prodc]
needs = ["needs/*.yaml"]

[proofs.accept]
kind = "accept"

[proofs.pytest]
kind = "pytest"
results = "junit.xml"
"""

_JUNIT = '<testsuite><testcase name="test_arm" classname="t"/></testsuite>\n'


def _lint(tmp_path: Path, need: str, *, strict: bool = True) -> int:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "test_arm.py").write_text("def test_arm():\n    pass\n", encoding="utf-8")
    (tmp_path / "junit.xml").write_text(_JUNIT, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: R-1\n"
        "    text: When the plan is ready, the roaster can arm a live roast\n"
        "    sources:\n      - kind: primary\n        who: Ana\n        quote: one click\n"
        "        date: 2026-10-20\n"
        "    attestation:\n      who: Jorge\n      date: 2026-10-26\n      verdict: pass\n" + need,
        encoding="utf-8",
    )
    args = ["lint", "--config", str(tmp_path / "prodc.toml")]
    return main([*args, "--strict"] if strict else args)


def test_must_with_only_declared_proofs_fails_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _lint(tmp_path, '    must: true\n    proofs: ["accept:jorge@2026-10-26"]\n')
    out = capsys.readouterr().out
    assert code == 1
    assert "R-1: must-have DELIVERED on declared proofs only" in out


def test_must_with_declared_only_passes_without_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _lint(
        tmp_path, '    must: true\n    proofs: ["accept:jorge@2026-10-26"]\n', strict=False
    )
    assert code == 0  # a warning, not an error
    assert "declared proofs only" in capsys.readouterr().out


def test_must_with_a_passing_test_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _lint(
        tmp_path,
        '    must: true\n    proofs: ["accept:jorge@2026-10-26", "pytest:test_arm.py::test_arm"]\n',
    )
    out = capsys.readouterr().out
    assert "declared proofs only" not in out
    assert code == 0


def test_should_with_only_declared_proofs_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _lint(tmp_path, '    proofs: ["accept:jorge@2026-10-26"]\n')
    assert "declared proofs only" not in capsys.readouterr().out
    assert code == 0


def test_status_shows_the_same_per_need_warning_as_lint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _lint(tmp_path, '    must: true\n    proofs: ["accept:jorge@2026-10-26"]\n')
    capsys.readouterr()
    main(["status", "--config", str(tmp_path / "prodc.toml")])
    assert "must-have DELIVERED on declared proofs only" in capsys.readouterr().out  # (#81)


def test_must_flow_of_declared_only_steps_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flow = (
        "    must: true\n    children:\n      - id: R-2\n"
        "  - id: R-2\n    text: When asked, the roaster can open the queue\n"
        '    proofs: ["accept:jorge@2026-10-26"]\n'
    )
    code = _lint(tmp_path, flow)
    out = capsys.readouterr().out
    assert "R-1: must-have DELIVERED on declared proofs only" in out  # the flow, not only R-2
    assert code == 1
