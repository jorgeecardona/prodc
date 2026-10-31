"""The view inventory: the UI units of every client, read from files each client generates (#100).

A view is any UI unit on a client: a web page, a section inside a page, a dialog, a mobile
screen, a desktop window. prodc never crawls app code. Each client writes one JSON file (the web
app from its router, a mobile app from its navigator) and prodc reads it. ``parent`` is
containment; ``links`` are navigation. The two relations are kept apart.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SCHEMA = 1

_PARAM_RE = re.compile(r"^(?::(\w+)|\{(\w+)\})$")


@dataclass(frozen=True)
class View:
    """One UI unit of one client."""

    client: str
    id: str  # normalised: ``:id`` and ``{id}`` path params are spelled ``$id``
    kind: str | None = None  # free string (page, screen, section, dialog...); None = untyped
    parent: str | None = None  # the view that contains this one, same client
    section: str | None = None
    needless_ok: bool = False  # no need is expected (redirect, auth, public)

    @property
    def key(self) -> str:
        """The canonical ``client:id`` a ``views:`` locator payload names."""
        return f"{self.client}:{self.id}"


@dataclass(frozen=True)
class ViewLink:
    """A navigation link between two views of one client."""

    client: str
    source: str
    target: str
    why: str | None = None  # the reason a user takes this link (#104)
    need: str | None = None  # the need id that reason points at (#104)
    file: str = ""  # the inventory file the link came from, for error messages


@dataclass(frozen=True)
class ViewInventory:
    """Every view and link across the configured inventory files."""

    views: tuple[View, ...] = ()
    links: tuple[ViewLink, ...] = ()

    def clients(self) -> list[str]:
        """The client names, in file order."""
        return list(dict.fromkeys(v.client for v in self.views))


class ViewInventoryError(ValueError):
    """A view inventory file is missing or does not follow the file contract."""


def normalise_id(view_id: str) -> str:
    """Spell every ``:param`` and ``{param}`` path segment as ``$param``."""
    path, sep, frag = view_id.partition("#")
    segments: list[str] = []
    for seg in path.split("/"):
        m = _PARAM_RE.match(seg)
        segments.append(f"${m.group(1) or m.group(2)}" if m else seg)
    return "/".join(segments) + sep + frag


def matches(pattern: str, concrete: str) -> bool:
    """True if a concrete web-like id (``/roast/sessions/42``) fits a ``$param`` pattern.

    Only ids that start with ``/`` are matched this way. A ``$`` segment matches any one
    non-empty segment. The ``#fragment`` part must be equal.
    """
    if not (pattern.startswith("/") and concrete.startswith("/")):
        return False
    p_path, _, p_frag = pattern.partition("#")
    c_path, _, c_frag = concrete.partition("#")
    if p_frag != c_frag:
        return False
    p_segs, c_segs = p_path.split("/"), c_path.split("/")
    if len(p_segs) != len(c_segs):
        return False
    return all(p == c or (p.startswith("$") and c) for p, c in zip(p_segs, c_segs, strict=True))


def _opt_str(raw: dict[str, object], key: str, where: str) -> str | None:
    val = raw.get(key)
    if val is None or isinstance(val, str):
        return val
    raise ViewInventoryError(f"{where}: '{key}' must be a string or null")


def _bool(raw: dict[str, object], key: str, where: str) -> bool:
    val = raw.get(key, False)
    if isinstance(val, bool):
        return val
    raise ViewInventoryError(f"{where}: '{key}' must be true or false")


def _records(data: dict[str, object], key: str, where: str) -> list[dict[str, object]]:
    items = data.get(key, [])
    if not isinstance(items, list) or not all(
        isinstance(i, dict) for i in cast(list[object], items)
    ):
        raise ViewInventoryError(f"{where}: '{key}' must be a list of objects")
    return cast(list[dict[str, object]], items)


def load_file(path: Path) -> ViewInventory:
    """Read one client's inventory file.

    Raises:
        ViewInventoryError: the file is missing, is not JSON, has another ``schema``, or a
            field has the wrong type.
    """
    where = str(path)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ViewInventoryError(f"{where}: no such view inventory file") from e
    except json.JSONDecodeError as e:
        raise ViewInventoryError(f"{where}: not JSON ({e.msg})") from e
    if not isinstance(data, dict):
        raise ViewInventoryError(f"{where}: top level must be an object")
    doc = cast(dict[str, object], data)
    if doc.get("schema") != SCHEMA:
        raise ViewInventoryError(f"{where}: 'schema' must be {SCHEMA}")
    client = doc.get("client")
    if not isinstance(client, str) or not client:
        raise ViewInventoryError(f"{where}: 'client' must be a non-empty string")
    views: list[View] = []
    for i, raw in enumerate(_records(doc, "views", where)):
        at = f"{where}: views[{i}]"
        vid = raw.get("id")
        if not isinstance(vid, str) or not vid:
            raise ViewInventoryError(f"{at}: 'id' must be a non-empty string")
        if "orphan_ok" in raw:
            raise ViewInventoryError(
                f"{at}: 'orphan_ok' was removed: a view is an entry when a need's path starts there"
            )
        parent = _opt_str(raw, "parent", at)
        views.append(
            View(
                client=client,
                id=normalise_id(vid),
                kind=_opt_str(raw, "kind", at),
                parent=normalise_id(parent) if parent is not None else None,
                section=_opt_str(raw, "section", at),
                needless_ok=_bool(raw, "needless_ok", at),
            )
        )
    links: list[ViewLink] = []
    for i, raw in enumerate(_records(doc, "links", where)):
        at = f"{where}: links[{i}]"
        src, dst = raw.get("from"), raw.get("to")
        if not isinstance(src, str) or not isinstance(dst, str):
            raise ViewInventoryError(f"{at}: 'from' and 'to' must be strings")
        links.append(
            ViewLink(
                client,
                normalise_id(src),
                normalise_id(dst),
                why=_opt_str(raw, "why", at),
                need=_opt_str(raw, "need", at),
                file=where,
            )
        )
    return ViewInventory(tuple(views), tuple(links))


def load(paths: list[Path]) -> ViewInventory:
    """Read and merge several clients' inventory files."""
    views: list[View] = []
    links: list[ViewLink] = []
    for p in paths:
        inv = load_file(p)
        views.extend(inv.views)
        links.extend(inv.links)
    return ViewInventory(tuple(views), tuple(links))


def has_links(inv: ViewInventory, client: str) -> bool:
    """True if the client's inventory carries any link. Link checks are skipped without one."""
    return any(lk.client == client for lk in inv.links)


def dangling(inv: ViewInventory) -> list[ViewLink]:
    """Links whose ``from`` or ``to`` is not a view of the same client (#105)."""
    known = {v.key for v in inv.views}
    return [
        lk
        for lk in inv.links
        if f"{lk.client}:{lk.source}" not in known or f"{lk.client}:{lk.target}" not in known
    ]


def _children(inv: ViewInventory, client: str) -> dict[str, list[str]]:
    ids = {v.id for v in inv.views if v.client == client}
    out: dict[str, list[str]] = {}
    for v in inv.views:
        if v.client == client and v.parent in ids:
            out.setdefault(v.parent, []).append(v.id)
    return out


def _subtree(children: dict[str, list[str]], root: str) -> set[str]:
    seen = {root}
    stack = [root]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def orphans(inv: ViewInventory, entries: set[str]) -> set[str]:
    """Keys (``client:id``) of top-level views nobody links to (#106).

    A child view is reached through its parent, so only a view with no known parent can be an
    orphan. A link to the view or to a view it contains counts, unless it starts inside the same
    subtree. An entry is not an orphan: ``entries`` holds the ``client:id`` of every view a
    need's ``path.start`` names. A client with no links at all is skipped.
    """
    out: set[str] = set()
    for client in inv.clients():
        if not has_links(inv, client):
            continue
        children = _children(inv, client)
        nested = {c for kids in children.values() for c in kids}
        links = [lk for lk in inv.links if lk.client == client]
        for v in inv.views:
            if v.client != client or v.key in entries or v.id in nested:
                continue
            tree = _subtree(children, v.id)
            if not any(lk.target in tree and lk.source not in tree for lk in links):
                out.add(v.key)
    return out


def _distances(inv: ViewInventory, client: str, starts: set[str]) -> dict[str, int]:
    """Clicks from the nearest start to every reachable view of the client (0-1 search)."""
    ids = {v.id for v in inv.views if v.client == client}
    adj: dict[str, list[tuple[str, int]]] = {}
    for lk in inv.links:
        if lk.client == client and lk.source in ids and lk.target in ids:
            adj.setdefault(lk.source, []).append((lk.target, 1))
    for v in inv.views:
        # a page under a page is a separate screen: only its links get a user there (#109)
        if v.client == client and v.parent in ids and v.kind != "page":
            adj.setdefault(v.id, []).append((v.parent, 0))
            adj.setdefault(v.parent, []).append((v.id, 0))
    dist = {s: 0 for s in starts if s in ids}
    queue = deque(dist)
    while queue:
        cur = queue.popleft()
        for nxt, cost in adj.get(cur, []):
            if dist.get(nxt, 1 << 30) > dist[cur] + cost:
                dist[nxt] = dist[cur] + cost
                (queue.appendleft if cost == 0 else queue.append)(nxt)
    return dist


def clicks(inv: ViewInventory, client: str, starts: set[str], goals: set[str]) -> int | None:
    """The fewest clicks from any start view to any goal view, or None when unreachable (#108).

    A link costs one click. Containment costs none, in both directions, for a child that is not
    a ``page`` (a section, dialog or tab is on its parent's page, and a link from the page can be
    used from it). A page under a page costs what its links cost (#109). Ids are same-client
    view ids.
    """
    dist = _distances(inv, client, starts)
    best = [dist[g] for g in goals if g in dist]
    return min(best) if best else None


def unreachable(inv: ViewInventory, client: str, entries: set[str]) -> int | None:
    """How many views cannot be reached from an entry view (#105).

    None when the client has no links or no entry view, so there is nothing to measure from.
    """
    starts = {k.partition(":")[2] for k in entries if k.partition(":")[0] == client}
    if not starts or not has_links(inv, client):
        return None
    ids = {v.id for v in inv.views if v.client == client}
    return len(ids - set(_distances(inv, client, starts)))
