"""Loader: YAML need files → Need objects, with the v0.1 schema rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.config import Config
from prodc.loader import LoaderError, load_needs
from prodc.model import SourceKind


def _config(tmp_path: Path, *files: tuple[str, str]) -> Config:
    needs_dir = tmp_path / "product" / "needs"
    needs_dir.mkdir(parents=True)
    for name, body in files:
        (needs_dir / name).write_text(body, encoding="utf-8")
    return Config(root=tmp_path, need_globs=["product/needs/*.yaml"])


def test_file_level_who_and_label_default_each_need(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "john.yaml",
            """
            who: john
            label: "design partner, Sincerely"
            needs:
              - id: J-1
                text: "multi-location per customer"
              - id: J-2
                text: "own voice"
                who: jane
            """,
        ),
    )
    needs = {n.id: n for n in load_needs(cfg)}
    assert needs["J-1"].who == "john"
    assert needs["J-1"].label == "design partner, Sincerely"
    assert needs["J-2"].who == "jane"  # per-need override wins
    assert needs["J-2"].label == "design partner, Sincerely"  # label still inherited


def test_source_kind_defaults_to_internal(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            """
            needs:
              - id: A-1
                text: "a need"
                sources:
                  - who: Jorge
                    date: 2026-08-02
                  - kind: interview
                    who: John
                    date: 2026-08-02
                    quote: "I need this"
            """,
        ),
    )
    (need,) = load_needs(cfg)
    assert need.sources[0].kind is SourceKind.INTERNAL
    assert need.sources[0].date == "2026-08-02"  # bare YAML date coerced to string
    assert need.sources[1].kind is SourceKind.INTERVIEW
    assert not need.is_opinion


def test_no_source_is_opinion(tmp_path: Path) -> None:
    cfg = _config(tmp_path, ("a.yaml", "needs:\n  - id: A-1\n    text: t\n"))
    (need,) = load_needs(cfg)
    assert need.is_opinion


def test_duplicate_id_across_files_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: X-1\n    text: a\n"),
        ("b.yaml", "needs:\n  - id: X-1\n    text: b\n"),
    )
    with pytest.raises(LoaderError, match="duplicate need id 'X-1'"):
        load_needs(cfg)


def test_flow_with_proofs_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            """
            needs:
              - id: F-1
                text: a flow
                children: [C-1]
                proofs: ["web:x#y"]
            """,
        ),
    )
    with pytest.raises(LoaderError, match="must not carry proofs"):
        load_needs(cfg)


def test_variant_scope_shared_baseline_across_clients(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "base.yaml",
            "needs:\n  - id: N-1\n    text: multi-location per customer\n",
        ),
        (
            "acme.yaml",
            """
            client: acme
            needs:
              - id: N-1@acme
                text: multi-location per customer
                variant_of: N-1
            """,
        ),
    )
    needs = {n.id: n for n in load_needs(cfg)}
    assert needs["N-1"].client is None and not needs["N-1"].is_variant  # shared baseline
    assert needs["N-1@acme"].client == "acme"  # file-level client default
    assert needs["N-1@acme"].is_variant and needs["N-1@acme"].variant_of == "N-1"


def test_variant_of_unknown_baseline_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: A-1\n    text: t\n    variant_of: NOPE\n"),
    )
    with pytest.raises(LoaderError, match="variant_of 'NOPE' is not a known need id"):
        load_needs(cfg)


def test_variant_cannot_chain(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            """
            needs:
              - id: B-1
                text: base
              - id: B-1@x
                text: variant
                variant_of: B-1
              - id: B-1@x@y
                text: variant of a variant
                variant_of: B-1@x
            """,
        ),
    )
    with pytest.raises(LoaderError, match="is itself a variant"):
        load_needs(cfg)


def test_unknown_source_kind_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            "needs:\n  - id: A-1\n    text: t\n    sources:\n      - kind: rumor\n",
        ),
    )
    with pytest.raises(LoaderError, match="unknown kind 'rumor'"):
        load_needs(cfg)


def test_importance_parsed_and_validated(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: A-1\n    text: t\n    importance: 3\n"),
    )
    (need,) = load_needs(cfg)
    assert need.importance == 3


def test_importance_rejects_non_positive_and_bool(tmp_path: Path) -> None:
    bad = _config(tmp_path, ("a.yaml", "needs:\n  - id: A-1\n    text: t\n    importance: 0\n"))
    with pytest.raises(LoaderError, match="positive integer ordinal"):
        load_needs(bad)


def test_claim_and_attestation_parsed(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            """
            needs:
              - id: A-1
                text: push to prod with no manual steps
                claim: a push event triggers an automatic build and deploy
                attestation:
                  who: Jorge
                  date: 2026-02-01
            """,
        ),
    )
    (need,) = load_needs(cfg)
    assert need.claim and "automatic build" in need.claim
    assert need.attestation is not None
    assert need.attestation.who == "Jorge" and need.attestation.date == "2026-02-01"


def test_attestation_requires_who_and_date(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: A-1\n    text: t\n    attestation:\n      who: Jorge\n"),
    )
    with pytest.raises(LoaderError, match="needs both 'who' and 'date'"):
        load_needs(cfg)


def test_goals_loaded_and_need_traces_up(tmp_path: Path) -> None:
    from prodc.loader import load

    cfg = _config(
        tmp_path,
        (
            "goals.yaml",
            "goals:\n  - id: G-1\n    text: reduce churn\n    metric: churn < 5%\n",
        ),
        (
            "needs.yaml",
            "needs:\n  - id: N-1\n    text: the owner can cancel in one step\n    goal: G-1\n",
        ),
    )
    model = load(cfg)
    assert [g.id for g in model.goals] == ["G-1"]
    assert model.goals[0].metric == "churn < 5%"
    assert model.needs[0].goal == "G-1"


def test_need_goal_unknown_raises(tmp_path: Path) -> None:
    cfg = _config(tmp_path, ("a.yaml", "needs:\n  - id: N-1\n    text: t\n    goal: NOPE\n"))
    with pytest.raises(LoaderError, match="goal 'NOPE' is not a known goal id"):
        load_needs(cfg)


def test_unknown_child_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: F-1\n    text: a flow\n    children: [C-404]\n"),
    )
    with pytest.raises(LoaderError, match="child 'C-404' is not a known need id"):
        load_needs(cfg)


def test_duplicate_goal_id_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "goals:\n  - id: G-1\n    text: a\n"),
        ("b.yaml", "goals:\n  - id: G-1\n    text: b\n"),
    )
    with pytest.raises(LoaderError, match="duplicate goal id 'G-1'"):
        load_needs(cfg)


def test_releases_loaded_and_need_slotted(tmp_path: Path) -> None:
    from prodc.loader import load

    cfg = _config(
        tmp_path,
        (
            "map.yaml",
            """
            releases:
              - id: R-1
                text: walking skeleton
              - id: R-2
                text: delight
            needs:
              - id: N-1
                text: the owner can sign in
                release: R-1
            """,
        ),
    )
    model = load(cfg)
    assert [r.id for r in model.releases] == ["R-1", "R-2"]  # declared order = ship order
    assert model.needs[0].release == "R-1"


def test_need_release_unknown_raises(tmp_path: Path) -> None:
    cfg = _config(tmp_path, ("a.yaml", "needs:\n  - id: N-1\n    text: t\n    release: NOPE\n"))
    with pytest.raises(LoaderError, match="release 'NOPE' is not a known release id"):
        load_needs(cfg)


def test_argument_graph_loaded_and_links_validated(tmp_path: Path) -> None:
    from prodc.loader import load
    from prodc.model import ArgKind

    cfg = _config(
        tmp_path,
        (
            "arg.yaml",
            """
            argument:
              - id: C-1
                kind: claim
                text: deploys are safe
                supported_by: [E-1]
                in_context_of: [A-1]
              - id: E-1
                kind: evidence
                text: the smoke suite passes
                about: web:deploy.feature#Smoke
              - id: A-1
                kind: assumption
                text: the suite covers the risky paths
            """,
        ),
    )
    model = load(cfg)
    assert {n.id for n in model.argument} == {"C-1", "E-1", "A-1"}
    c1 = next(n for n in model.argument if n.id == "C-1")
    assert c1.kind is ArgKind.CLAIM and c1.supported_by == ("E-1",)


def test_argument_dangling_link_raises(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            "argument:\n  - id: C-1\n    kind: claim\n    text: t\n    supported_by: [GHOST]\n",
        ),
    )
    with pytest.raises(LoaderError, match="link 'GHOST' is not a known argument node id"):
        load_needs(cfg)


def test_product_flag_defaults_true_and_parses(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: N-1\n    text: t\n  - id: N-2\n    text: infra\n    product: false\n"),
    )
    by_id = {n.id: n for n in load_needs(cfg)}
    assert by_id["N-1"].product is True and by_id["N-2"].product is False


def test_ai_attestation_parsed(tmp_path: Path) -> None:
    from prodc.model import AttestationKind

    cfg = _config(
        tmp_path,
        (
            "a.yaml",
            """
            needs:
              - id: N-1
                text: the owner can export a statement
                attestation:
                  who: claude-opus-4-8
                  date: 2026-10-05
                  kind: ai
                  verdict: pass
                  comment: the smoke proof exercises the export path end to end
            """,
        ),
    )
    (need,) = load_needs(cfg)
    a = need.attestation
    assert a is not None and a.kind is AttestationKind.AI
    assert a.who == "claude-opus-4-8" and a.verdict == "pass"
    assert a.comment and "end to end" in a.comment


def test_attestation_defaults_human(tmp_path: Path) -> None:
    from prodc.model import AttestationKind

    cfg = _config(
        tmp_path,
        ("a.yaml", "needs:\n  - id: N-1\n    text: t\n    attestation:\n      who: Jorge\n      date: 2026-10-05\n"),
    )
    (need,) = load_needs(cfg)
    assert need.attestation is not None and need.attestation.kind is AttestationKind.HUMAN
