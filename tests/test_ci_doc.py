"""The CI job in ``docs/ci.md`` is valid and its ``prodc.toml`` reads test results (PD-6)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from prodc.cli import main

_DOC = Path(__file__).parent.parent / "docs" / "ci.md"


def _blocks(lang: str) -> list[str]:
    text = _DOC.read_text(encoding="utf-8")
    found = re.findall(rf"```{lang}\n(.*?)```", text, flags=re.S)
    return [re.sub(r"^   ", "", b, flags=re.M) for b in found]


def test_the_documented_job_pins_an_exact_prodc_version() -> None:
    jobs = [yaml.safe_load(b) for b in _blocks("yaml")]
    prodc_job = next(j["prodc"] for j in jobs if "prodc" in j)
    assert prodc_job["needs"] == ["test"]
    (script,) = prodc_job["script"]
    assert re.fullmatch(r"uvx --from prodc==\d+\.\d+\.\d+ prodc lint", script)
    test_job = next(j["test"] for j in jobs if "test" in j)
    assert test_job["artifacts"]["reports"]["junit"] == "reports/junit.xml"


def test_the_documented_config_reads_the_junit_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (toml,) = _blocks("toml")
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "product" / "needs").mkdir(parents=True)
    (tmp_path / "product" / "needs" / "n.yaml").write_text(
        "needs:\n  - id: N-1\n    text: When I log in, I can see my orders.\n"
        "    sources:\n      - {kind: secondary, date: 2026-01-01, locator: notes.md}\n"
        '    proofs: ["test:tests/test_x.py::test_orders"]\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_orders():\n    pass\n", "utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "junit.xml").write_text(
        '<testsuite><testcase classname="tests.test_x" name="test_orders">'
        '<failure message="no"/></testcase></testsuite>',
        encoding="utf-8",
    )
    main(["status", "--config", str(tmp_path / "prodc.toml"), "--json"])
    out = capsys.readouterr().out
    assert '"state": "pending"' in out
