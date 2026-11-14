"""Attestation policy (#87): a verdict is required, an AI review can count, warnings group."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli import main

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
[proofs.acc]
kind = "accept"
{lint}"""

_NEEDS = """
needs:
  - id: N-1
    text: first delivered need
    proofs: ["acc:a"]
  - id: N-2
    text: second delivered need
    proofs: ["acc:b"]
  - id: N-3
    text: third delivered need, reviewed by a model
    proofs: ["acc:c"]
    attestation: {who: claude, date: 2026-10-30, kind: ai, verdict: pass}
"""


def _project(tmp_path: Path, lint: str = "") -> str:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML.format(lint=lint), encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _lint(cfg: str, capsys: pytest.CaptureFixture[str], *extra: str) -> str:
    main(["lint", "--config", cfg, *extra])
    return capsys.readouterr().out


def test_attest_requires_a_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["attest", "N-1", "--config", cfg, "--by", "Jo", "--date", "2026-11-01"])
    assert exc.value.code == 2
    assert "--verdict" in capsys.readouterr().err
    assert main(["attest", "N-1", "--config", cfg, "--by", "Jo", "--date", "2026-11-01", "--verdict", "pass"]) == 0  # fmt: skip


def test_the_writer_rejects_no_verdict(tmp_path: Path) -> None:
    from prodc.config import Config
    from prodc.writer import WriteError, attest

    cfg = Config.load(Path(_project(tmp_path)))
    with pytest.raises(WriteError, match="needs a verdict"):
        attest(
            cfg,
            "N-1",
            who="x",
            date="2026-11-01",
            kind="human",
            verdict=None,
            comment=None,
            expect_sha=None,
            dry_run=True,
        )


def test_unattested_warnings_group_into_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _lint(_project(tmp_path), capsys)
    assert (
        "2 ids: DELIVERED on an unattested proof link (warrant not reviewed) (#13) "
        "(pass --all-warnings to list them)"
    ) in out
    assert "N-1: DELIVERED on an unattested proof link" not in out


def test_all_warnings_and_strict_list_each_need(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path)
    for flag in ("--all-warnings", "--strict"):
        out = _lint(cfg, capsys, flag)
        assert "N-1: DELIVERED on an unattested proof link" in out
        assert "N-2: DELIVERED on an unattested proof link" in out
        assert "delivered needs have an unattested" not in out


def test_an_ai_review_warns_by_default_and_counts_by_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _lint(_project(tmp_path), capsys)
    assert "N-3: DELIVERED, warrant reviewed by claude (AI), not a human" in out
    (tmp_path / "prodc.toml").write_text(
        _TOML.format(lint='[lint]\nai_attestation = "counts"\n'), encoding="utf-8"
    )
    out = _lint(str(tmp_path / "prodc.toml"), capsys)
    assert "reviewed by claude" not in out


def test_a_bad_ai_attestation_policy_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, '[lint]\nai_attestation = "maybe"\n')
    assert main(["lint", "--config", cfg]) == 2
    assert "ai_attestation" in capsys.readouterr().err
