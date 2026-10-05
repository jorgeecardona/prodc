"""Evidence staleness (#58): observed_at, evidence_age, status --stale, lint, capture."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from prodc.config import Config, ConfigError
from prodc.model import Need, Source, SourceKind
from prodc.status import evidence_age_days, last_observed


def _src(observed_at: str | None) -> Source:
    return Source(kind=SourceKind.INTERVIEW, who="Ana", observed_at=observed_at)


def test_evidence_age_uses_newest_source() -> None:
    today = date(2026, 10, 5)
    need = Need(id="N-1", text="a need", sources=(_src("2026-09-01"), _src("2026-10-01")))
    assert last_observed(need) == "2026-10-01"
    assert evidence_age_days(need, today) == 4


def test_evidence_age_unknown_without_observed_at() -> None:
    need = Need(id="N-1", text="a need", sources=(_src(None),))
    assert last_observed(need) is None
    assert evidence_age_days(need, date(2026, 10, 5)) is None


def test_malformed_observed_at_is_ignored() -> None:
    need = Need(id="N-1", text="a need", sources=(_src("not-a-date"), _src("2026-10-01")))
    assert last_observed(need) == "2026-10-01"


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""


def _project(tmp_path: Path, toml: str, needs: str) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


def _needs_yaml() -> str:
    old = (date.today() - timedelta(days=400)).isoformat()
    fresh = date.today().isoformat()
    return f"""
needs:
  - id: OLD-1
    text: user can see an old thing
    sources:
      - kind: interview
        who: Ana
        quote: "I need this"
        observed_at: {old}
  - id: FRESH-1
    text: user can see a fresh thing
    sources:
      - kind: interview
        who: Bob
        quote: "me too"
        observed_at: {fresh}
"""


def test_loader_parses_observed_at(tmp_path: Path) -> None:
    from prodc.loader import load

    cfg = Config.load(_project(tmp_path, _TOML, _needs_yaml()))
    old = next(n for n in load(cfg).needs if n.id == "OLD-1")
    assert old.sources[0].observed_at == (date.today() - timedelta(days=400)).isoformat()


def test_status_stale_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    code = main(
        [
            "status",
            "--config",
            str(_project(tmp_path, _TOML, _needs_yaml())),
            "--stale",
            "180",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    ids = {n["id"] for n in payload["needs"]}
    assert ids == {"OLD-1"}  # only the >180d need survives the filter


def test_status_json_carries_evidence_age(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path, _TOML, _needs_yaml())), "--json"])
    payload = json.loads(capsys.readouterr().out)
    fresh = next(n for n in payload["needs"] if n["id"] == "FRESH-1")
    assert fresh["evidence_age"] == 0 and fresh["last_observed_at"] == date.today().isoformat()


def test_lint_flags_stale_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    toml = _TOML + "\n[lint]\nstale_after_days = 180\n"
    code = main(["lint", "--config", str(_project(tmp_path, toml, _needs_yaml()))])
    out = capsys.readouterr().out
    assert code == 0  # staleness is a warning, not a hard error
    assert "OLD-1" in out and "evidence is" in out and "FRESH-1: evidence is" not in out


def test_config_rejects_bad_stale_after_days(tmp_path: Path) -> None:
    toml = _TOML + "\n[lint]\nstale_after_days = 0\n"
    with pytest.raises(ConfigError, match="stale_after_days"):
        Config.load(_project(tmp_path, toml, _needs_yaml()))


def test_capture_writes_observed_at(tmp_path: Path) -> None:
    from prodc.cli import main

    needs = """
needs:
  - id: N-1
    text: user can see a thing
"""
    cfg = _project(tmp_path, _TOML, needs)
    code = main(
        [
            "capture",
            "N-1",
            "--kind",
            "interview",
            "--who",
            "Ana",
            "--quote",
            "I want it",
            "--observed-at",
            "2026-10-05",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    written = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    assert "observed_at:" in written and "2026-10-05" in written
