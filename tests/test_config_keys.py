"""Unknown ``prodc.toml`` keys load with a notice and fail ``lint``."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main
from prodc.config import Config

_BASE = '[prodc]\nfiles = ["n.yaml"]\n'


def _write(tmp_path: Path, toml: str) -> Path:
    (tmp_path / "n.yaml").write_text("needs:\n  - id: N-1\n    text: t\n", encoding="utf-8")
    path = tmp_path / "prodc.toml"
    path.write_text(toml, encoding="utf-8")
    return path


def test_unknown_keys_are_named_at_every_level(tmp_path: Path) -> None:
    toml = (
        _BASE
        + 'profile = "research"\n[lint]\nstale_after_day = 3\n'
        + '[proofs.t]\nkind = "pytest"\nresult = "x"\n[extra]\na = 1\n'
        + '[[callbacks.hooks]]\non = "state_change"\ncommand = ["x"]\nwhen = "y"\n'
    )
    assert list(Config.load(_write(tmp_path, toml)).notices) == [
        "prodc.toml: top level: unknown key 'extra' is ignored",
        "prodc.toml: [prodc]: unknown key 'profile' is ignored",
        "prodc.toml: [lint]: unknown key 'stale_after_day' is ignored "
        "(did you mean 'stale_after_days'?)",
        "prodc.toml: [proofs.t]: unknown key 'result' is ignored (did you mean 'results'?)",
        "prodc.toml: [[callbacks.hooks]][0]: unknown key 'when' is ignored",
    ]


def test_lint_fails_on_an_unknown_key_and_status_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = str(_write(tmp_path, _BASE + 'profile = "research"\n'))
    assert main(["status", "--config", cfg]) == 0
    assert "unknown key 'profile'" in capsys.readouterr().err
    assert main(["lint", "--config", cfg]) == 1


def test_a_clean_config_has_no_notices(tmp_path: Path) -> None:
    assert Config.load(_write(tmp_path, _BASE)).notices == ()


def test_playwright_ct_is_gone(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="unknown kind 'playwright-ct'"):
        Config.load(_write(tmp_path, _BASE + '[proofs.c]\nkind = "playwright-ct"\n'))
