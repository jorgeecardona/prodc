"""Duplicate detection (#55): the matcher, and its wiring into add/lint/dupes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.config import Config, ConfigError
from prodc.dedup import duplicate_pairs, matches_for, similarity
from prodc.model import Need


def _n(nid: str, text: str, **kw: object) -> Need:
    return Need(id=nid, text=text, **kw)  # type: ignore[arg-type]


def test_similarity_identical_and_disjoint() -> None:
    assert similarity("export my data to CSV", "export my data to CSV") == 1.0
    assert similarity("export my data to CSV", "schedule a weekly standup") < 0.2


def test_similarity_near_duplicate_scores_high() -> None:
    s = similarity("user can export their data to CSV", "user can export data to a CSV file")
    assert 0.5 < s < 1.0


def test_duplicate_pairs_finds_and_ranks() -> None:
    needs = [
        _n("A", "user can export their orders to CSV"),
        _n("B", "user can export orders to a CSV file"),
        _n("C", "admin schedules the weekly roast"),
    ]
    pairs = duplicate_pairs(needs, threshold=0.4)
    assert len(pairs) == 1
    assert {pairs[0].a.id, pairs[0].b.id} == {"A", "B"}


def test_not_duplicate_of_suppresses_pair() -> None:
    needs = [
        _n("A", "user can export their orders to CSV", not_duplicate_of=("B",)),
        _n("B", "user can export orders to a CSV file"),
    ]
    assert duplicate_pairs(needs, threshold=0.4) == []
    # but it's still a real text match when we ask to include acknowledged ones
    assert len(duplicate_pairs(needs, threshold=0.4, include_acknowledged=True)) == 1


def test_same_scope_flag_and_tiebreak() -> None:
    needs = [
        _n("A", "export orders to CSV", client="acme", goal="G-1"),
        _n("B", "export orders to CSV", client="acme", goal="G-1"),
    ]
    pairs = duplicate_pairs(needs, threshold=0.4)
    assert pairs[0].same_scope is True


def test_matches_for_excludes_self_and_sorts() -> None:
    needs = [
        _n("A", "export orders to CSV"),
        _n("B", "export orders to a CSV file"),
        _n("C", "export orders to CSV"),
    ]
    hits = matches_for("export orders to CSV", needs, threshold=0.4, exclude_id="C")
    ids = [n.id for n, _ in hits]
    assert "C" not in ids and ids[0] == "A"  # exact match ranks first


_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

_NEEDS = """
needs:
  - id: N-1
    text: user can export their orders to CSV
  - id: N-2
    text: user can export orders to a CSV file
  - id: N-3
    text: admin schedules the weekly roast run
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


def test_loader_parses_not_duplicate_of(tmp_path: Path) -> None:
    from prodc.loader import load

    cfg = Config.load(
        _project(
            tmp_path,
            needs="""
needs:
  - id: N-1
    text: a need
    not_duplicate_of: [N-2]
  - id: N-2
    text: another need
""",
        )
    )
    n1 = next(n for n in load(cfg).needs if n.id == "N-1")
    assert n1.not_duplicate_of == ("N-2",)


def test_config_duplicate_threshold_default_and_override(tmp_path: Path) -> None:
    assert Config.load(_project(tmp_path)).duplicate_threshold == 0.8
    toml = _TOML + "\n[lint]\nduplicate_threshold = 0.6\n"
    assert Config.load(_project(tmp_path, toml=toml)).duplicate_threshold == 0.6


def test_config_rejects_out_of_range_threshold(tmp_path: Path) -> None:
    toml = _TOML + "\n[lint]\nduplicate_threshold = 1.5\n"
    with pytest.raises(ConfigError, match="duplicate_threshold"):
        Config.load(_project(tmp_path, toml=toml))


def test_dupes_command_lists_pairs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    code = main(["dupes", "--config", str(_project(tmp_path)), "--threshold", "0.4"])
    out = capsys.readouterr().out
    assert code == 0
    assert "N-1 ~ N-2" in out and "N-3" not in out
    assert "1 candidate pair" in out


def test_dupes_command_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    code = main(["dupes", "--config", str(_project(tmp_path)), "--threshold", "0.4", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and len(payload) == 1
    assert {payload[0]["a"], payload[0]["b"]} == {"N-1", "N-2"}


def test_add_strict_dupes_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, toml=_TOML + "\n[lint]\nduplicate_threshold = 0.4\n")
    code = main(
        [
            "add",
            "need",
            "N-9",
            "--text",
            "user can export their orders to CSV",
            "--who",
            "agent",
            "--file",
            "needs/a.yaml",
            "--strict-dupes",
            "--config",
            str(cfg),
        ]
    )
    err = capsys.readouterr().err
    assert code == 2 and "possible duplicate of N-1" in err


def test_add_no_dupe_check_skips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, toml=_TOML + "\n[lint]\nduplicate_threshold = 0.4\n")
    code = main(
        [
            "add",
            "need",
            "N-9",
            "--text",
            "user can export their orders to CSV",
            "--who",
            "agent",
            "--file",
            "needs/a.yaml",
            "--no-dupe-check",
            "--config",
            str(cfg),
        ]
    )
    err = capsys.readouterr().err
    assert code == 0 and "possible duplicate" not in err


def test_lint_surfaces_duplicate_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, toml=_TOML + "\n[lint]\nduplicate_threshold = 0.4\n")
    code = main(["lint", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert code == 0  # a possible duplicate is a warning, not a hard error
    assert "possible duplicate of N-2" in out or "possible duplicate of N-1" in out


def test_score_prune_matches_brute_force() -> None:
    # the size-ratio short-circuit (#62) must never change which pairs clear the threshold:
    # compare optimized duplicate_pairs against a brute-force scan using raw similarity().
    texts = [
        "user can export their orders to CSV",
        "user can export orders to a CSV file",
        "export the weekly totals to CSV",
        "admin schedules the weekly roast",
        "schedule the weekly roast run",
        "a short one",
        "a short two",
        "highlight past due orders on the board",
        "past-due orders are highlighted on the board",
    ]
    needs = [_n(f"N-{i}", t) for i, t in enumerate(texts)]
    for threshold in (0.2, 0.4, 0.6, 0.8):
        got = {
            frozenset((p.a.id, p.b.id)): round(p.score, 10) for p in duplicate_pairs(needs, threshold)
        }
        brute: dict[frozenset[str], float] = {}
        for i in range(len(needs)):
            for j in range(i + 1, len(needs)):
                s = similarity(needs[i].text, needs[j].text)
                if s >= threshold:
                    brute[frozenset((needs[i].id, needs[j].id))] = round(s, 10)
        assert got == brute, f"mismatch at threshold {threshold}"
