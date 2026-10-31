"""A source anchor points inside its locator, and a line range is checked against the file (#57)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.anchor import anchor_drift, line_span
from prodc.cli import main
from prodc.model import Source, SourceKind


@pytest.mark.parametrize(
    ("anchor", "span"),
    [("L120-L134", (120, 134)), ("L7", (7, 7)), ("L3-4", (3, 4)), ("p.7", None), ("L9-L2", None)],
)
def test_line_span(anchor: str, span: tuple[int, int] | None) -> None:
    assert line_span(anchor) == span


def _src(anchor: str | None, quote: str | None = "I lose them", loc: str = "t.md") -> Source:
    return Source(kind=SourceKind.PRIMARY, quote=quote, locator=loc, anchor=anchor)


def test_quote_inside_the_span_is_fine(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("a\nso I  lose\nthem often\nz\n", encoding="utf-8")
    assert anchor_drift(tmp_path, _src("L2-L3")) is None  # whitespace and line breaks are ignored


def test_quote_moved_out_of_the_span_drifts(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("a\nb\nc\nI lose them\n", encoding="utf-8")
    assert "no longer appears in t.md#L1-L2" in (anchor_drift(tmp_path, _src("L1-L2")) or "")


def test_span_past_the_end_of_the_file_drifts(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("one\ntwo\n", encoding="utf-8")
    assert "has 2 line(s)" in (anchor_drift(tmp_path, _src("L1-L9")) or "")


def test_missing_file_is_reported(tmp_path: Path) -> None:
    assert "cannot be read" in (anchor_drift(tmp_path, _src("L1")) or "")


def test_other_anchors_and_locators_are_not_checked(tmp_path: Path) -> None:
    assert anchor_drift(tmp_path, _src("p.7")) is None
    assert anchor_drift(tmp_path, _src("L1", loc="https://x.org/t")) is None
    assert anchor_drift(tmp_path, _src("L1", loc="t.md#h")) is None
    assert anchor_drift(tmp_path, _src("L1", quote=None)) is None


def test_ref_joins_locator_and_anchor() -> None:
    assert _src("L3").ref == "t.md#L3"
    assert _src(None).ref == "t.md"
    assert Source(kind=SourceKind.ASSUMPTION, anchor="L3").ref is None


def test_capture_writes_the_anchor_and_status_warns_on_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "needs:\n  - id: N-1\n    text: see past-due orders\n", encoding="utf-8"
    )
    (tmp_path / "t.md").write_text("a\nb\nI lose them\n", encoding="utf-8")
    cfg = str(tmp_path / "prodc.toml")
    code = main(
        [
            "capture", "N-1", "--config", cfg, "--kind", "primary", "--who", "Jo",
            "--quote", "I lose them", "--locator", "t.md", "--anchor", "L1-L2",
            "--date", "2026-10-01",
        ]
    )  # fmt: skip
    capsys.readouterr()
    assert code == 0
    assert "anchor: L1-L2" in (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert main(["status", "--config", cfg, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    need = payload["needs"][0]
    assert any("source anchor drifted" in w for w in need["warnings"])
