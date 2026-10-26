"""A need's path start and outcome are checked against the view inventory (#101)."""

from __future__ import annotations

import json
from pathlib import Path

from prodc.adapters import Adapter, ViewsAdapter
from prodc.model import Need, NeedPath
from prodc.status import resolve

_WEB: dict[str, object] = {
    "schema": 1,
    "client": "web",
    "views": [{"id": "/roast/sessions/$planId", "kind": "page"}, {"id": "/roast/preparation"}],
}
_IOS: dict[str, object] = {"schema": 1, "client": "ios", "views": [{"id": "RoastSession", "kind": "screen"}]}


def _views(tmp_path: Path, *clients: dict[str, object]) -> dict[str, Adapter]:
    files: list[str] = []
    for c in clients:
        name = f"{c['client']}.json"
        (tmp_path / name).write_text(json.dumps(c), encoding="utf-8")
        files.append(name)
    return {"views": ViewsAdapter(tmp_path, files)}


def _warnings(adapters: dict[str, Adapter], start: str, outcome: str) -> list[str]:
    need = Need(id="R-1", text="arm a roast", path=NeedPath(start=start, outcome=outcome))
    (r,) = resolve([need], adapters)
    return [w for w in r.warnings if "(#101)" in w]


def test_view_present_is_silent(tmp_path: Path) -> None:
    assert (
        _warnings(_views(tmp_path, _WEB), "/roast/preparation", "web:/roast/sessions/$planId") == []
    )


def test_view_absent_warns(tmp_path: Path) -> None:
    assert _warnings(_views(tmp_path, _WEB), "/roast/queue", "/roast/preparation") == [
        "path start 'web:/roast/queue' is not a view (#101)"
    ]


def test_concrete_url_matches_pattern(tmp_path: Path) -> None:
    assert _warnings(_views(tmp_path, _WEB), "/roast/preparation", "/roast/sessions/42") == []


def test_two_clients_need_a_prefix(tmp_path: Path) -> None:
    ads = _views(tmp_path, _WEB, _IOS)
    assert _warnings(ads, "ios:RoastSession", "web:/roast/preparation") == []
    assert _warnings(ads, "RoastSession", "ios:Missing") == [
        "path start 'RoastSession' names no client: write it as client:id (#101)",
        "path outcome 'ios:Missing' is not a view (#101)",
    ]


def test_outcome_that_is_a_test_locator_is_skipped(tmp_path: Path) -> None:
    ads = _views(tmp_path, _WEB)
    ads["e2e"] = ads["views"]  # any configured adapter name marks the outcome as a proof
    assert _warnings(ads, "/roast/preparation", "e2e:roast-live-armed") == []


def test_no_views_adapter_is_silent() -> None:
    assert _warnings({}, "/anything", "/else") == []
