"""The ``views`` proof adapter over generated view inventory files (#100)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.adapters import ViewsAdapter
from prodc.config import Config
from prodc.loader import load
from prodc.model import NeedState, ProofState
from prodc.status import orphans, proof_suggestions, resolve
from prodc.views import ViewInventoryError, load_file, matches, normalise_id

_WEB = {
    "schema": 1,
    "client": "web",
    "generated_from": "apps/website/src/router.tsx@abc123",
    "views": [
        {"id": "/roast/sessions", "kind": "page", "parent": None, "section": "roast"},
        {"id": "/roast/sessions/:planId", "kind": "page", "section": "roast"},
        {
            "id": "/roast/sessions/{planId}#batches",
            "kind": "section",
            "parent": "/roast/sessions/$planId",
        },
        {"id": "/login", "kind": "page", "needless_ok": True},
    ],
    "links": [{"from": "/roast/sessions", "to": "/roast/sessions/$planId"}],
}

_IOS = {
    "schema": 1,
    "client": "ios",
    "views": [{"id": "RoastSession", "kind": "screen"}],
}


def _adapter(tmp_path: Path) -> ViewsAdapter:
    (tmp_path / "web.json").write_text(json.dumps(_WEB), encoding="utf-8")
    (tmp_path / "ios.json").write_text(json.dumps(_IOS), encoding="utf-8")
    return ViewsAdapter(tmp_path, ["web.json", "ios.json"])


def test_param_spellings_normalise_to_dollar() -> None:
    assert normalise_id("/a/:id/b/{x}#s") == "/a/$id/b/$x#s"
    assert normalise_id("RoastSession") == "RoastSession"


def test_concrete_url_matches_pattern() -> None:
    assert matches("/roast/sessions/$planId", "/roast/sessions/42")
    assert not matches("/roast/sessions/$planId", "/roast/sessions")
    assert not matches("/roast/sessions/$planId", "/roast/sessions/42#batches")
    assert matches("/roast/sessions/$planId#batches", "/roast/sessions/42#batches")
    assert not matches("RoastSession", "RoastSession")  # not web-like: exact only


def test_inventory_lists_both_clients(tmp_path: Path) -> None:
    assert _adapter(tmp_path).inventory() == [
        "ios:RoastSession",
        "web:/login",
        "web:/roast/sessions",
        "web:/roast/sessions/$planId",
        "web:/roast/sessions/$planId#batches",
    ]


def test_resolve_hit_is_declared_delivered(tmp_path: Path) -> None:
    ad = _adapter(tmp_path)
    r = ad.resolve("ios:RoastSession")
    assert r.state is ProofState.DELIVERED and r.declared
    r = ad.resolve("web:/roast/sessions/:planId")  # another param spelling, same view
    assert r.state is ProofState.DELIVERED


def test_resolve_miss_is_broken(tmp_path: Path) -> None:
    ad = _adapter(tmp_path)
    assert ad.resolve("web:/roast/queue").state is ProofState.BROKEN
    assert ad.resolve("android:RoastSession").state is ProofState.BROKEN  # wrong client


def test_child_and_parent_are_claimed_separately(tmp_path: Path) -> None:
    ad = _adapter(tmp_path)
    assert ad.covers("web:/roast/sessions/$planId#batches") == [
        "web:/roast/sessions/$planId#batches"
    ]
    assert ad.covers("web:/roast/sessions/42") == ["web:/roast/sessions/$planId"]
    view = next(v for v in ad.load().views if v.id.endswith("#batches"))
    assert view.parent == "/roast/sessions/$planId" and view.kind == "section"


def test_links_kept_apart_from_parent(tmp_path: Path) -> None:
    inv = _adapter(tmp_path).load()
    assert [(lk.source, lk.target) for lk in inv.links] == [
        ("/roast/sessions", "/roast/sessions/$planId")
    ]
    assert inv.clients() == ["web", "ios"]


def test_bad_file_is_unresolved(tmp_path: Path) -> None:
    (tmp_path / "web.json").write_text('{"schema": 2, "client": "web"}', encoding="utf-8")
    r = ViewsAdapter(tmp_path, ["web.json"]).resolve("web:/x")
    assert r.state is ProofState.UNRESOLVED and "'schema' must be 1" in r.detail
    with pytest.raises(ViewInventoryError, match="no such view inventory file"):
        load_file(tmp_path / "missing.json")


_TOML = """\
[prodc]
needs = ["needs/*.yaml"]

[proofs.views]
kind = "views"
files = ["product/views/web.json", "product/views/ios.json"]
"""

_NEEDS = """\
needs:
  - id: R-1
    text: the roaster sees the batches of a session
    proofs: ["views:web:/roast/sessions/$planId#batches"]
  - id: R-2
    text: the roaster opens a session
    proofs: ["views:web:/roast/sessions/42"]
  - id: R-3
    text: the roast queue
"""


def test_config_board_and_orphans(tmp_path: Path) -> None:
    (tmp_path / "product" / "views").mkdir(parents=True)
    _adapter(tmp_path / "product" / "views")
    (tmp_path / "needs").mkdir()
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    cfg = Config.load(tmp_path / "prodc.toml")
    needs = list(load(cfg).needs)
    results = {r.need.id: r for r in resolve(needs, cfg.adapters, cfg.source_adapters)}
    assert results["R-1"].state is NeedState.DELIVERED and results["R-1"].declared
    assert results["R-2"].state is NeedState.DELIVERED
    assert orphans(needs, cfg.adapters) == {
        "views": ["ios:RoastSession", "web:/login", "web:/roast/sessions"]
    }
    # views are left out of suggest unless asked for by name
    suggested = proof_suggestions(list(results.values()), cfg.adapters, min_score=0.0, top=5)
    assert suggested == []
    named = proof_suggestions(
        list(results.values()), cfg.adapters, min_score=0.0, top=5, kind="views"
    )
    assert named and all(s.locator.startswith("views:") for s in named)
