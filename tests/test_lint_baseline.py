"""``prodc lint --baseline``: show only the warnings that are new since a saved baseline (PD-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main
from prodc.cli.commands import baseline_key


def _board(tmp_path: Path, needs: str) -> str:
    (tmp_path / "n.yaml").write_text(f"needs:\n{needs}", encoding="utf-8")
    (tmp_path / "prodc.toml").write_text('[prodc]\nfiles = ["n.yaml"]\n', encoding="utf-8")
    return str(tmp_path / "prodc.toml")


_SECONDARY_NO_LOCATOR = (
    "  - id: {id}\n    text: When I log in, I can see my orders.\n"
    "    sources:\n      - {{kind: secondary, date: 2026-01-01}}\n"
)


def test_baseline_hides_known_warnings_and_shows_new_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _board(tmp_path, _SECONDARY_NO_LOCATOR.format(id="N-1"))
    base = tmp_path / "lint-baseline.txt"
    assert main(["lint", "--config", cfg, "--write-baseline", str(base)]) == 0
    assert "N-1\tsecondary source without a locator" in base.read_text(encoding="utf-8")
    capsys.readouterr()

    assert main(["lint", "--config", cfg, "--baseline", str(base)]) == 0
    assert capsys.readouterr().out.strip() == "lint: 0 error(s), 0 warning(s)"

    cfg = _board(
        tmp_path,
        _SECONDARY_NO_LOCATOR.format(id="N-1")
        + _SECONDARY_NO_LOCATOR.format(id="N-2").replace("see my orders", "export a CSV"),
    )
    assert main(["lint", "--config", cfg, "--baseline", str(base)]) == 0
    out = capsys.readouterr().out
    assert "N-2: secondary source without a locator" in out
    assert "N-1: secondary source" not in out


def test_baseline_key_ignores_counts_and_dates() -> None:
    a = baseline_key("D-1", "decided 2026-09-27 under principle p, revised later")
    b = baseline_key("D-1", "decided 2026-10-01 under principle p, revised later")
    assert a == b
    assert a != baseline_key("D-2", "decided 2026-09-27 under principle p, revised later")


def test_a_missing_baseline_file_is_a_usage_error(tmp_path: Path) -> None:
    cfg = _board(tmp_path, _SECONDARY_NO_LOCATOR.format(id="N-1"))
    assert main(["lint", "--config", cfg, "--baseline", str(tmp_path / "nope.txt")]) == 2
