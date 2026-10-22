"""Product principles (the vision, held as given) and the re-review ripple.

A principle is a founding commitment — not an `assumption` to validate but a chosen frame that
decides between clients who want opposite things. An `out_of_scope` withdrawal cites the principle
it rests on; revising that principle later flags the decision for re-review (the ripple)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from prodc.adapters import Adapter, ProofResult
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import Principle, PrincipleState, ProofState, Source, SourceKind
from prodc.status import principle_report, principle_state


@dataclass(frozen=True)
class _Stub:
    """Resolves any payload to a fixed ProofResult — a per-adapter test double."""

    result: ProofResult

    def resolve(self, payload: str) -> ProofResult:
        _ = payload
        return self.result


def _adapter(state: ProofState, *, declared: bool) -> dict[str, Adapter]:
    return {"g": _Stub(ProofResult(state, declared=declared, detail="stub"))}

_TOML = """
[prodc]
needs = ["needs/*.yaml"]
"""

# A comment to prove the splice is comment-safe, two principles (one revised recently, one not),
# and two needs withdrawn under P-1 — one decided before its revision (stale), one after.
_NEEDS = """
roles:
  - id: owner
    text: the product owner

principles:
  # the founding local-first commitment — keep this comment through a revise
  - id: P-1
    text: timbre is local-first; audio never leaves the machine
    revised_at: 2026-10-15
    sources:
      - kind: primary
        who: Jordan
        role: owner
  - id: P-2
    text: single-user only, no accounts
    revised_at: 2026-10-10

needs:
  - id: N-1
    text: user can see a delivered thing
    proofs: ["x:1"]
  - id: N-7
    text: cloud sync of recorded audio
    withdrawn:
      kind: out_of_scope
      principle: P-1
      reason: audio must stay on the machine
      date: 2026-10-10
  - id: N-9
    text: multi-user shared sessions
    withdrawn:
      kind: out_of_scope
      principle: P-1
      reason: later, not now
      date: 2026-10-16
"""


def _project(tmp_path: Path, toml: str = _TOML, needs: str = _NEEDS) -> Path:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return tmp_path / "prodc.toml"


# --- loader -----------------------------------------------------------------


def test_loader_parses_principles_with_sources(tmp_path: Path) -> None:
    model = load(Config.load(_project(tmp_path)))
    by_id = {p.id: p for p in model.principles}
    assert by_id["P-1"] == Principle(
        id="P-1",
        text="timbre is local-first; audio never leaves the machine",
        revised_at="2026-10-15",
        sources=(Source(kind=SourceKind.PRIMARY, who="Jordan", role="owner"),),
    )
    assert by_id["P-2"].sources == ()


def test_duplicate_principle_id_across_files_rejected(tmp_path: Path) -> None:
    (tmp_path / "needs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(
        "principles:\n  - id: P-1\n    text: first\n", encoding="utf-8"
    )
    (tmp_path / "needs" / "b.yaml").write_text(
        "principles:\n  - id: P-1\n    text: clash\n", encoding="utf-8"
    )
    with pytest.raises(LoaderError, match="duplicate principle id 'P-1'"):
        load(Config.load(tmp_path / "prodc.toml"))


def test_unknown_withdrawal_principle_rejected(tmp_path: Path) -> None:
    needs = """
principles:
  - id: P-1
    text: a real one
    revised_at: 2026-10-15
needs:
  - id: N-1
    text: a withdrawn need
    withdrawn:
      kind: out_of_scope
      principle: P-9
      reason: cites a ghost
      date: 2026-10-10
"""
    with pytest.raises(LoaderError, match="is not a known principle id"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_principle_source_role_validated(tmp_path: Path) -> None:
    needs = """
principles:
  - id: P-1
    text: cites a ghost role
    revised_at: 2026-10-15
    sources:
      - kind: primary
        who: Jordan
        role: ghost
"""
    with pytest.raises(LoaderError, match="is not a known role id"):
        load(Config.load(_project(tmp_path, needs=needs)))


# --- scope (#88) ------------------------------------------------------------

_SCOPED_TOML = """
[prodc]
needs = ["needs/*.yaml"]

[principles]
scopes = ["product", "visual", "engineering"]
"""


def test_principle_scope_defaults_to_product(tmp_path: Path) -> None:
    needs = "principles:\n  - id: P-1\n    text: a principle\n"
    model = load(Config.load(_project(tmp_path, needs=needs)))
    assert model.principles[0].scope == "product"


def test_declared_scope_loads(tmp_path: Path) -> None:
    needs = "principles:\n  - id: P-1\n    text: colour is load-bearing\n    scope: visual\n"
    model = load(Config.load(_project(tmp_path, toml=_SCOPED_TOML, needs=needs)))
    assert model.principles[0].scope == "visual"


def test_undeclared_scope_rejected(tmp_path: Path) -> None:
    # default [principles].scopes is just ["product"], so "visual" is undeclared here.
    needs = "principles:\n  - id: P-1\n    text: a principle\n    scope: visual\n"
    with pytest.raises(LoaderError, match="scope 'visual' is not declared"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_add_principle_writes_scope(tmp_path: Path) -> None:
    from prodc.writer import add_principle

    cfg = Config.load(_project(tmp_path, toml=_SCOPED_TOML, needs="principles:\n  - id: P-0\n    text: seed\n"))
    add_principle(
        cfg,
        "P-9",
        "colour is load-bearing",
        file="needs/a.yaml",
        revised_at=date.today().isoformat(),
        scope="visual",
        dry_run=False,
    )
    model = load(cfg)
    assert next(p for p in model.principles if p.id == "P-9").scope == "visual"


# --- enforced / stated / violated / broken (#89) ----------------------------


def _p(**kw: object) -> Principle:
    return Principle(id="P-1", text="colour is load-bearing", **kw)  # type: ignore[arg-type]


def test_no_proofs_is_stated() -> None:
    # a principle with no guards is honestly STATED — allowed, never a gate failure.
    assert principle_state(_p(), _adapter(ProofState.DELIVERED, declared=True)) is PrincipleState.STATED


def test_all_proofs_delivered_is_enforced() -> None:
    p = _p(proofs=("g:noPurple",))
    assert principle_state(p, _adapter(ProofState.DELIVERED, declared=True)) is PrincipleState.ENFORCED


def test_failing_guard_with_results_is_violated() -> None:
    # the trap: a guard that ran and FAILED (results artifact present, not declared) means the code
    # contradicts the principle NOW — VIOLATED, never a mere STATED/PENDING. "The board cannot lie."
    p = _p(proofs=("g:noPurple",))
    assert principle_state(p, _adapter(ProofState.PENDING, declared=False)) is PrincipleState.VIOLATED


def test_declared_pending_guard_is_stated_not_violated() -> None:
    # a guard that is only declared (e.g. @pending, no results) is not yet active — STATED, not VIOLATED.
    p = _p(proofs=("g:noPurple",))
    assert principle_state(p, _adapter(ProofState.PENDING, declared=True)) is PrincipleState.STATED


def test_broken_proof_is_broken() -> None:
    p = _p(proofs=("g:noPurple",))
    assert principle_state(p, _adapter(ProofState.BROKEN, declared=False)) is PrincipleState.BROKEN


def test_dangling_implemented_in_is_broken_even_without_proofs() -> None:
    p = _p(implemented_in="g:tokens.css")
    assert principle_state(p, _adapter(ProofState.BROKEN, declared=False)) is PrincipleState.BROKEN


def test_need_proof_on_principle_rejected(tmp_path: Path) -> None:
    needs = "principles:\n  - id: P-1\n    text: a principle\n    proofs:\n      - 'need:N-1@yes'\n"
    with pytest.raises(LoaderError, match="guards the code, it does not wait on a need"):
        load(Config.load(_project(tmp_path, needs=needs)))


def test_lint_hard_fails_broken_principle(tmp_path: Path) -> None:
    import argparse

    from prodc.cli.commands import cmd_lint

    # a principle whose only proof is an unresolvable locator (no 'ghost' adapter) is BROKEN.
    needs = "principles:\n  - id: P-1\n    text: a principle\n    proofs:\n      - 'ghost:x'\n"
    cfg_path = _project(tmp_path, needs=needs)
    args = argparse.Namespace(config=str(cfg_path), strict=False, json=False)
    assert cmd_lint(args) == 1


# --- principle_report (declined / stale) ------------------------------------


def test_principle_report_declined_and_stale(tmp_path: Path) -> None:
    model = load(Config.load(_project(tmp_path)))
    reports = {
        r.principle.id: r for r in principle_report(list(model.needs), list(model.principles))
    }
    p1 = reports["P-1"]
    # both needs cite P-1; declined sorted by id
    assert [n.id for n in p1.declined] == ["N-7", "N-9"]
    # only N-7 was decided (2026-10-10) before P-1 was revised (2026-10-15)
    assert [n.id for n in p1.stale] == ["N-7"]
    # P-2 has no decisions resting on it
    assert reports["P-2"].declined == ()
    assert reports["P-2"].stale == ()


# --- writer: add principle --------------------------------------------------


def test_add_principle_stamps_revised_at_today(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a live need\n")
    code = main(
        [
            "add",
            "principle",
            "P-1",
            "--text",
            "local-first always",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    by_id = {p.id: p for p in load(Config.load(cfg)).principles}
    assert by_id["P-1"].text == "local-first always"
    assert by_id["P-1"].revised_at == date.today().isoformat()


# --- writer: revise principle (comment-safe splice) -------------------------


def test_revise_principle_updates_text_and_date_keeping_comment(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    code = main(
        [
            "revise",
            "principle",
            "P-1",
            "--text",
            "timbre is local-first; audio stays on-device",
            "--date",
            "2026-10-20",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    text = (tmp_path / "needs" / "a.yaml").read_text(encoding="utf-8")
    # the comment elsewhere in the file survives the splice (comment-safe)
    assert "keep this comment through a revise" in text
    by_id = {p.id: p for p in load(Config.load(cfg)).principles}
    assert by_id["P-1"].text == "timbre is local-first; audio stays on-device"
    assert by_id["P-1"].revised_at == "2026-10-20"
    # P-2 untouched
    assert by_id["P-2"].revised_at == "2026-10-10"


def test_revise_principle_date_defaults_today(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    main(["revise", "principle", "P-2", "--config", str(cfg)])
    by_id = {p.id: p for p in load(Config.load(cfg)).principles}
    assert by_id["P-2"].revised_at == date.today().isoformat()
    assert (
        by_id["P-2"].text == "single-user only, no accounts"
    )  # text unchanged when --text omitted


def test_revise_unknown_principle_errors(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path)
    code = main(["revise", "principle", "P-404", "--config", str(cfg)])
    assert code == 2


# --- writer: withdraw --principle -------------------------------------------


def test_withdraw_with_principle(tmp_path: Path) -> None:
    from prodc.cli import main
    from prodc.model import WithdrawalKind

    cfg = _project(
        tmp_path,
        needs=(
            "principles:\n  - id: P-1\n    text: local-first\n    revised_at: 2026-10-15\n"
            "needs:\n  - id: N-1\n    text: cloud sync\n"
        ),
    )
    code = main(
        [
            "withdraw",
            "N-1",
            "--reason",
            "breaks local-first",
            "--kind",
            "out_of_scope",
            "--principle",
            "P-1",
            "--date",
            "2026-10-16",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    by_id = {n.id: n for n in load(Config.load(cfg)).needs}
    w = by_id["N-1"].withdrawn
    assert w is not None
    assert w.principle == "P-1"
    assert w.kind is WithdrawalKind.OUT_OF_SCOPE


# --- status (text + json) ---------------------------------------------------


def test_status_text_shows_principles_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "principles (the vision, held as given):" in out
    assert "P-1" in out and "revised 2026-10-15" in out
    assert "declined: N-7, N-9" in out
    assert "decided before the latest revision: N-7: re-review" in out


def test_status_json_carries_principles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from prodc.cli import main

    main(["status", "--config", str(_project(tmp_path)), "--json"])
    payload = json.loads(capsys.readouterr().out)
    by_id = {p["id"]: p for p in payload["principles"]}
    assert by_id["P-1"]["revised_at"] == "2026-10-15"
    assert by_id["P-1"]["declined"] == ["N-7", "N-9"]
    assert by_id["P-1"]["stale"] == ["N-7"]


def test_status_json_no_principles_is_empty_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs="needs:\n  - id: N-1\n    text: a live need\n")
    main(["status", "--config", str(cfg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["principles"] == []


# --- show -------------------------------------------------------------------


def test_show_withdrawn_line_names_the_principle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["show", "N-7", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    assert "withdrawn [out_of_scope] per P-1: audio must stay on the machine (2026-10-10)" in out


# --- lint ripple ------------------------------------------------------------


def test_lint_ripple_fires_only_for_decisions_before_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    main(["lint", "--config", str(_project(tmp_path))])
    out = capsys.readouterr().out
    # N-7 (decided 2026-10-10, before P-1's 2026-10-15 revision) is flagged
    assert "N-7: withdrawn per principle P-1 on 2026-10-10, but P-1 was revised 2026-10-15" in out
    # N-9 (decided 2026-10-16, after the revision) is not
    assert "N-9: withdrawn per principle" not in out


# --- discovery lifecycle: promote a need into a principle (--from-need) ------

_PROMOTE_NEEDS = """
roles:
  - id: owner
    text: the product owner
needs:
  - id: N-3
    text: timbre should keep everything on the laptop
    sources:
      - kind: primary
        who: Jordan
        role: owner
        date: 2026-10-01
        quote: I never want my audio in the cloud
"""


def test_add_principle_from_need_copies_text_and_sources_leaving_need(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs=_PROMOTE_NEEDS)
    code = main(
        [
            "add",
            "principle",
            "P-1",
            "--from-need",
            "N-3",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    model = load(Config.load(cfg))
    p1 = {p.id: p for p in model.principles}["P-1"]
    assert p1.text == "timbre should keep everything on the laptop"  # text copied from the need
    assert p1.revised_at == date.today().isoformat()
    # the provenance that surfaced it travels across
    assert p1.sources == (
        Source(
            kind=SourceKind.PRIMARY,
            who="Jordan",
            role="owner",
            date="2026-10-01",
            quote="I never want my audio in the cloud",
        ),
    )
    # the origin need stays on the board, unchanged
    n3 = {n.id: n for n in model.needs}["N-3"]
    assert n3.is_withdrawn is False
    assert len(n3.sources) == 1


def test_add_principle_from_need_text_override(tmp_path: Path) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs=_PROMOTE_NEEDS)
    main(
        [
            "add",
            "principle",
            "P-1",
            "--from-need",
            "N-3",
            "--text",
            "timbre is local-first",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    p1 = {p.id: p for p in load(Config.load(cfg)).principles}["P-1"]
    assert p1.text == "timbre is local-first"  # --text wins over the need's text
    assert len(p1.sources) == 1  # sources still copied


def test_add_principle_from_unknown_need_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs=_PROMOTE_NEEDS)
    code = main(
        [
            "add",
            "principle",
            "P-1",
            "--from-need",
            "N-404",
            "--file",
            "needs/a.yaml",
            "--config",
            str(cfg),
        ]
    )
    assert code == 2
    assert "no need 'N-404'" in capsys.readouterr().err


def test_add_principle_without_text_or_from_need_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prodc.cli import main

    cfg = _project(tmp_path, needs=_PROMOTE_NEEDS)
    code = main(["add", "principle", "P-1", "--file", "needs/a.yaml", "--config", str(cfg)])
    assert code == 2
    assert "requires --text" in capsys.readouterr().err
