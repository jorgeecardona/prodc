"""The view links: why, orphans, dangling links, walkable paths, click budget, graph (#104-#108)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prodc import views as v
from prodc.adapters import Adapter, ViewsAdapter
from prodc.cli import main
from prodc.model import Need, NeedPath
from prodc.status import resolve

_WEB: dict[str, object] = {
    "schema": 1,
    "client": "web",
    "views": [
        {"id": "/", "kind": "page"},
        {"id": "/pricing", "kind": "page"},
        {"id": "/install", "kind": "page"},
        {"id": "/install#steps", "kind": "section", "parent": "/install"},
        {"id": "/lost", "kind": "page"},
        {"id": "/far", "kind": "page"},
    ],
    "links": [
        {"from": "/", "to": "/pricing", "why": "A visitor compares plans."},
        {"from": "/pricing", "to": "/install", "why": "Dictation is free, so try it."},
        {"from": "/install", "to": "/far"},
        {"from": "/pricing", "to": "/gone"},
    ],
}


def _inv(tmp_path: Path, doc: dict[str, object] | None = None) -> v.ViewInventory:
    f = tmp_path / "web.json"
    f.write_text(json.dumps(doc or _WEB), encoding="utf-8")
    return v.load_file(f)


def test_link_why_and_need_load_and_default_to_none(tmp_path: Path) -> None:
    links = _inv(tmp_path).links
    assert links[0].why == "A visitor compares plans."
    assert links[2].why is None and links[2].need is None
    assert links[0].file.endswith("web.json")


def test_orphan_is_top_level_unlinked_and_not_an_entry(tmp_path: Path) -> None:
    # /lost has no inbound link; / is an entry (a path starts there); /install#steps is reached through its parent.
    assert v.orphans(_inv(tmp_path), {"web:/"}) == {"web:/lost"}


def test_link_into_a_child_keeps_the_parent_from_being_orphan(tmp_path: Path) -> None:
    doc = {
        **_WEB,
        "links": [{"from": "/", "to": "/install#steps"}],
    }
    assert "web:/install" not in v.orphans(_inv(tmp_path, doc), {"web:/"})


def test_no_links_at_all_skips_the_orphan_check(tmp_path: Path) -> None:
    assert v.orphans(_inv(tmp_path, {**_WEB, "links": []}), set()) == set()


def test_dangling_link_is_found(tmp_path: Path) -> None:
    (lk,) = v.dangling(_inv(tmp_path))
    assert (lk.source, lk.target) == ("/pricing", "/gone")


def test_clicks_count_links_and_not_containment(tmp_path: Path) -> None:
    inv = _inv(tmp_path)
    assert v.clicks(inv, "web", {"/"}, {"/install"}) == 2
    assert v.clicks(inv, "web", {"/"}, {"/install#steps"}) == 2  # the section is on the page
    assert (
        v.clicks(inv, "web", {"/install#steps"}, {"/far"}) == 1
    )  # the page's link, from the section
    assert v.clicks(inv, "web", {"/"}, {"/lost"}) is None


_NESTED: dict[str, object] = {
    "schema": 1,
    "client": "web",
    "views": [
        {"id": "/app", "kind": "page"},
        {"id": "/app/a", "kind": "page", "parent": "/app"},
        {"id": "/app/b", "kind": "page", "parent": "/app"},
        {"id": "/app#menu", "kind": "section", "parent": "/app"},
    ],
    "links": [{"from": "/app", "to": "/app/a"}],
}


def test_a_page_under_a_page_costs_its_links(tmp_path: Path) -> None:
    inv = _inv(tmp_path, _NESTED)
    assert v.clicks(inv, "web", {"/app"}, {"/app/a"}) == 1
    assert v.clicks(inv, "web", {"/app/a"}, {"/app/b"}) is None  # siblings, no link between
    assert v.clicks(inv, "web", {"/app"}, {"/app/b"}) is None


def test_a_section_under_a_page_is_free_both_ways(tmp_path: Path) -> None:
    inv = _inv(tmp_path, _NESTED)
    assert v.clicks(inv, "web", {"/app"}, {"/app#menu"}) == 0
    assert v.clicks(inv, "web", {"/app#menu"}, {"/app"}) == 0


def test_unreachable_counts_a_nested_page_without_a_link(tmp_path: Path) -> None:
    assert v.unreachable(_inv(tmp_path, _NESTED), "web", {"web:/app"}) == 1  # /app/b


def test_unreachable_from_entry_views(tmp_path: Path) -> None:
    inv = _inv(tmp_path)
    assert v.unreachable(inv, "web", {"web:/"}) == 1  # /lost
    assert v.unreachable(inv, "web", set()) is None  # no entry, nothing to measure from


def test_orphan_ok_is_rejected(tmp_path: Path) -> None:
    bad: dict[str, object] = {**_WEB, "views": [{"id": "/", "orphan_ok": True}]}
    (tmp_path / "web.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(v.ViewInventoryError, match="orphan_ok' was removed"):
        v.load_file(tmp_path / "web.json")


def _adapters(tmp_path: Path, doc: dict[str, object] | None = None) -> dict[str, Adapter]:
    (tmp_path / "web.json").write_text(json.dumps(doc or _WEB), encoding="utf-8")
    return {"views": ViewsAdapter(tmp_path, ["web.json"])}


def _path_warnings(
    ads: dict[str, Adapter], start: str, outcome: str, max_clicks: int | None = None
) -> list[str]:
    need = Need(
        id="R-1", text="x", path=NeedPath(start=start, outcome=outcome, max_clicks=max_clicks)
    )
    (r,) = resolve([need], ads)
    return [w for w in r.warnings if "view links" in w]


def test_path_with_a_route_in_budget_is_silent(tmp_path: Path) -> None:
    assert _path_warnings(_adapters(tmp_path), "/", "/install", max_clicks=2) == []


def test_path_without_a_route_warns(tmp_path: Path) -> None:
    assert _path_warnings(_adapters(tmp_path), "/", "/lost") == [
        "path outcome '/lost' cannot be reached from start '/' over the view links (#105)"
    ]


def test_path_over_budget_warns(tmp_path: Path) -> None:
    assert _path_warnings(_adapters(tmp_path), "/", "/far", max_clicks=2) == [
        "path takes 3 click(s) over the view links, over the budget of 2 (#108)"
    ]


def test_path_check_is_skipped_for_a_client_without_links(tmp_path: Path) -> None:
    ads = _adapters(tmp_path, {**_WEB, "links": []})
    assert _path_warnings(ads, "/", "/lost", max_clicks=1) == []


_TOML = """\
[prodc]
needs = ["needs/*.yaml"]

[proofs.views]
kind = "views"
files = ["views/web.json"]
{lint}"""

_NEEDS = """\
needs:
  - id: R-1
    text: a visitor installs after seeing pricing
    proofs: ["views:web:/install"]
  - id: R-2
    text: a visitor lands on the home page and reaches the install page
    path:
      start: web:/
      outcome: web:/install
"""


def _project(tmp_path: Path, lint: str = "", needs: str = _NEEDS) -> str:
    (tmp_path / "views").mkdir()
    (tmp_path / "needs").mkdir()
    (tmp_path / "views" / "web.json").write_text(json.dumps(_WEB), encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    (tmp_path / "prodc.toml").write_text(_TOML.format(lint=lint), encoding="utf-8")
    return str(tmp_path / "prodc.toml")


def test_views_json_carries_orphan_and_links(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["views", "--config", _project(tmp_path), "--json"]) == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["/lost"]["orphan"] is True
    assert rows["/pricing"]["orphan"] is False
    assert rows["/pricing"]["inbound"] == [
        {"from": "/", "why": "A visitor compares plans.", "need": None}
    ]
    assert [o["to"] for o in rows["/pricing"]["outbound"]] == ["/install", "/gone"]


def test_views_table_shows_counts_orphan_and_unreachable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["views", "--config", _project(tmp_path), "--links"]) == 0
    out = capsys.readouterr().out
    assert "[unjustified, orphan]" in out
    assert "1/2" in out  # /pricing: one inbound, two outbound
    assert "-> /install: Dictation is free, so try it." in out
    assert "orphan: 1" in out
    assert "web: unreachable from an entry view: 1" in out


def test_graph_mermaid_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["views", "--config", _project(tmp_path), "--graph", "mermaid"]) == 0
    assert capsys.readouterr().out == (
        "## web\n\n```mermaid\nflowchart LR\n"
        '  v0["/"]:::gap\n'
        '  v1["/far"]:::unjustified\n'
        '  v2["/install"]:::gap\n'
        '  v3["/install#steps"]:::unjustified\n'
        '  v5["/pricing"]:::unjustified\n'
        '  subgraph orphans ["no inbound link"]\n'
        '    v4["/lost"]:::unjustified\n'
        "  end\n"
        "  v2 -.- v3\n"
        '  v0 -->|"A visitor compares plans."| v5\n'  # a link without a why has no label
        "  v2 --> v1\n"
        '  v5 -->|"Dictation is free, so try it."| v2\n'  # the dangling /gone link is not drawn
        "  classDef delivered fill:#d3f9d8,stroke:#2f9e44\n"
        "  classDef gap fill:#ffe3e3,stroke:#e03131\n"
        "  classDef unjustified fill:#fff3bf,stroke:#f08c00\n"
        "  classDef noneed fill:#e9ecef,stroke:#868e96\n"
        "  classDef plain fill:#fff,stroke:#868e96\n"
        "```\n"
    )


def test_graph_writes_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_file = tmp_path / "g.md"
    cfg = _project(tmp_path)
    assert main(["views", "--config", cfg, "--graph", "mermaid", "-o", str(out_file)]) == 0
    assert out_file.read_text(encoding="utf-8").startswith("## web")


def _lint(cfg: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["lint", "--config", cfg])
    return code, capsys.readouterr().out


def test_lint_errors_on_a_dangling_link_and_warns_on_an_orphan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _lint(_project(tmp_path), capsys)
    assert code == 1
    assert "link /pricing -> /gone names a view that is not in the web inventory (#105)" in out
    assert "web:/lost: orphan view" in out


def test_lint_warns_when_a_client_has_links_but_no_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    only_proof = _NEEDS.split("  - id: R-2")[0]
    _, out = _lint(_project(tmp_path, needs=only_proof), capsys)
    assert "web: the view inventory has links but no entry view" in out


def test_lint_is_quiet_about_entries_when_a_path_starts_at_a_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _lint(_project(tmp_path), capsys)
    assert "no entry view" not in out


def test_lint_unjustified_views_and_link_without_why_are_opt_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, plain = _lint(_project(tmp_path), capsys)
    assert "unjustified view" not in plain and "has no why" not in plain


def test_lint_unjustified_views_warn_and_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _project(tmp_path, '[lint]\nunjustified_views = "warn"\nlink_without_why = "warn"\n')
    _, out = _lint(cfg, capsys)
    assert "web:/pricing: unjustified view" in out
    assert "web:/install: link to /far has no why (#104)" in out
    (tmp_path / "prodc.toml").write_text(
        _TOML.format(lint='[lint]\nunjustified_views = "error"\n'), encoding="utf-8"
    )
    _, out = _lint(cfg, capsys)
    assert "ERROR  web:/pricing: unjustified view" in out


def test_lint_rejects_a_bad_level(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _project(tmp_path, '[lint]\nunjustified_views = "loud"\n')
    assert main(["lint", "--config", cfg]) == 2
