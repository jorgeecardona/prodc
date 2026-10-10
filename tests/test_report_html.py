"""`prodc report --format html`: a self-contained, interactive, read-only HTML viewer (#79)."""

from __future__ import annotations

import json
import re
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
label: "design partner"
needs:
  - id: N-1
    text: see past-due orders at a glance
    must: true
    client: acme
    sources:
      - kind: primary
        who: Jordan
        date: 2026-09-20
        quote: "I lose them"
    proofs:
      - "web:orders.feature#Past due orders are highlighted"
  - id: N-2
    text: export the run sheet
    client: beta
    sources:
      - kind: secondary
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


def _payload(html: str) -> dict[str, object]:
    """Extract and parse the embedded JSON snapshot the viewer renders from."""
    m = re.search(r'id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m is not None
    return json.loads(m.group(1).replace("\\u003c", "<"))


def _render(tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> str:
    code = main(["report", "--format", "html", "--config", str(_project(tmp_path)), *extra])
    assert code == 0
    return capsys.readouterr().out


def test_html_is_self_contained_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _render(tmp_path, capsys)
    assert out.lstrip().startswith("<!doctype html>")
    assert "<title>" in out and "</html>" in out.rstrip()[-10:]
    # No external assets: nothing is fetched over the network.
    assert 'src="http' not in out and 'href="http' not in out
    assert "<link" not in out  # no external stylesheet


def test_html_embeds_resolved_board(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _payload(_render(tmp_path, capsys))
    assert len(data["needs"]) == 3  # type: ignore[arg-type]
    assert data["summary"]["coverage_pct"] == 33  # type: ignore[index]  # 1 of 3 delivered
    ids = {n["id"] for n in data["needs"]}  # type: ignore[attr-defined]
    assert ids == {"N-1", "N-2", "N-3"}


def test_html_carries_source_quote_and_proof_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _payload(_render(tmp_path, capsys))
    n1 = next(n for n in data["needs"] if n["id"] == "N-1")  # type: ignore[attr-defined]
    assert n1["state"] == "delivered"
    assert n1["sources"][0]["quote"] == "I lose them"
    assert n1["warrant"] == "primary"
    n3 = next(n for n in data["needs"] if n["id"] == "N-3")  # type: ignore[attr-defined]
    assert n3["opinion"] is True  # no source at all


def test_html_client_scope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _payload(_render(tmp_path, capsys, "--client", "acme"))
    ids = {n["id"] for n in data["needs"]}  # type: ignore[attr-defined]
    assert "N-1" in ids and "N-2" not in ids  # acme-scoped drops the beta-only need
    assert data["scope"] == "acme"


def test_html_escapes_angle_brackets_so_data_cannot_break_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "features").mkdir(exist_ok=True)
    (tmp_path / "needs" / "x.yaml").write_text(
        'needs:\n  - id: N-X\n    text: "close </script><script>alert(1)</script> tag"\n',
        encoding="utf-8",
    )
    code = main(["report", "--format", "html", "--config", str(tmp_path / "prodc.toml")])
    assert code == 0
    out = capsys.readouterr().out
    # The raw closing tag from need text must not appear literally in the data script.
    data_block = re.search(r'id="data".*?</script>', out, re.S)
    assert data_block is not None
    assert "</script>" not in data_block.group(0)[:-9]  # only the real closing tag, at the end
    assert _payload(out)["needs"][0]["text"].startswith("close ")  # type: ignore[index]


def test_html_written_to_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "out" / "status.html"
    code = main(
        [
            "report",
            "--format",
            "html",
            "--config",
            str(_project(tmp_path)),
            "-o",
            str(dest),
        ]
    )
    assert code == 0
    assert "wrote report" in capsys.readouterr().out
    assert dest.read_text(encoding="utf-8").lstrip().startswith("<!doctype html>")
