"""``prodc views``: each client's views, the needs that point at them, and flags (#102)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc.cli import main

_WEB: dict[str, object] = {
    "schema": 1,
    "client": "web",
    "views": [
        {"id": "/roast/sessions", "kind": "page", "section": "roast"},
        {"id": "/roast/sessions/$planId", "kind": "page", "parent": "/roast/sessions"},
        {
            "id": "/roast/sessions/$planId#batches",
            "kind": "section",
            "parent": "/roast/sessions/$planId",
        },
        {"id": "/admin", "kind": "page"},
        {"id": "/login", "kind": "page", "needless_ok": True},
        {"id": "/legacy"},
    ],
}
_IOS: dict[str, object] = {
    "schema": 1,
    "client": "ios",
    "views": [{"id": "RoastSession", "kind": "screen"}],
}

_TOML = """\
[prodc]
needs = ["needs/*.yaml"]

[proofs.views]
kind = "views"
files = ["views/web.json", "views/ios.json"]
"""

_NEEDS = """\
needs:
  - id: R-1
    text: the roaster sees the batches of a session
    proofs: ["views:web:/roast/sessions/$planId#batches"]
  - id: R-2
    text: the roaster opens the session on the phone
    path:
      start: ios:RoastSession
      outcome: web:/roast/sessions/42
"""


def _project(tmp_path: Path) -> str:
    (tmp_path / "views").mkdir()
    (tmp_path / "needs").mkdir()
    (tmp_path / "views" / "web.json").write_text(json.dumps(_WEB), encoding="utf-8")
    (tmp_path / "views" / "ios.json").write_text(json.dumps(_IOS), encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(_NEEDS, encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def _rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> list[dict[str, object]]:
    assert main(["views", "--config", _project(tmp_path), "--json", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_tree_order_per_client(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = _rows(tmp_path, capsys)
    assert [(r["client"], r["id"], r["depth"]) for r in rows] == [
        ("web", "/admin", 0),
        ("web", "/legacy", 0),
        ("web", "/login", 0),
        ("web", "/roast/sessions", 0),
        ("web", "/roast/sessions/$planId", 1),
        ("web", "/roast/sessions/$planId#batches", 2),
        ("ios", "RoastSession", 0),
    ]


def test_needs_state_and_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    by_id = {r["id"]: r for r in _rows(tmp_path, capsys)}
    assert by_id["/roast/sessions/$planId#batches"]["needs"] == ["R-1"]
    assert by_id["/roast/sessions/$planId#batches"]["state"] == "delivered"
    assert by_id["/roast/sessions/$planId"]["needs"] == ["R-2"]  # through the path outcome URL
    assert by_id["RoastSession"]["needs"] == ["R-2"]  # through the path start
    # a parent with no need of its own is justified through its child
    assert by_id["/roast/sessions"]["needs"] == [] and by_id["/roast/sessions"]["justified"]
    assert by_id["/roast/sessions"]["state"] is None
    assert not by_id["/admin"]["justified"]
    assert by_id["/login"]["justified"]  # needless_ok
    assert by_id["/legacy"]["untyped"] and not by_id["/admin"]["untyped"]


def test_client_filter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert [r["id"] for r in _rows(tmp_path, capsys, "--client", "ios")] == ["RoastSession"]


def test_text_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["views", "--config", _project(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "      /roast/sessions/$planId#batches" in out  # indented under its parent
    assert "[unjustified, untyped]" in out  # /legacy
    assert "views: 7, unjustified: 2, untyped: 1" in out


def test_lint_strict_fails_on_untyped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _project(tmp_path)
    main(["lint", "--config", p, "--json"])
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert {
        "id": "web:/legacy",
        "warning": "view has no kind: set it in the inventory file (#102)",
    } in warnings
    assert main(["lint", "--config", p, "--strict"]) == 1
