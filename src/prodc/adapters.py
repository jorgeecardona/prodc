"""Proof adapters: resolve a locator payload to a :class:`ProofState`.

An adapter reads a repo as it already is (Gherkin titles, pytest node ids). Status
comes from a test-results artifact (cucumber-json / junit) when configured and
present; otherwise it reports a *declared* state (from tags or existence) and says so.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from .model import ProofState

_TAG_RE = re.compile(r"@[\w\-.]+")
_SCENARIO_RE = re.compile(r"^\s*(?:Scenario|Scenario Outline):\s*(.*?)\s*$")


def _steps_passed(steps: list[object]) -> bool:
    """A scenario passes iff every step's result status is 'passed' (cucumber-json)."""
    for step in steps:
        if not isinstance(step, dict):
            return False
        result = cast("dict[str, object]", step).get("result")
        status = (
            cast("dict[str, object]", result).get("status") if isinstance(result, dict) else None
        )
        if status != "passed":
            return False
    return True


def _git_head(repo: Path) -> str | None:
    """Short git rev of a checked-out repo, read from .git/HEAD (no git binary needed)."""
    head = repo / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if ref.startswith("ref:"):
        try:
            return (repo / ".git" / ref[4:].strip()).read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return None
    return ref[:7]


@dataclass(frozen=True)
class ProofResult:
    state: ProofState
    declared: bool  # True when the state rests on tags/existence, not a results artifact
    detail: str


class Adapter(Protocol):
    def resolve(self, payload: str) -> ProofResult: ...


@runtime_checkable
class Inventoried(Protocol):
    """An adapter that can list every proof unit it knows (for proof discovery, #54).

    Weaker than :class:`Enumerable`: discovery only needs the universe, not the per-payload
    `covers` mapping the orphan report uses — so an adapter can offer suggestions without
    changing orphan behaviour.
    """

    def inventory(self) -> list[str]: ...  # canonical ids of every proof unit


@runtime_checkable
class Enumerable(Protocol):
    """An adapter that can list every proof unit it knows and which a payload claims.

    Needed for the orphan report (proofs referenced by no need). Adapters that can't
    enumerate their universe (e.g. pytest, which resolves by existence) don't implement it.
    """

    def inventory(self) -> list[str]: ...  # canonical ids of every proof unit
    def covers(self, payload: str) -> list[str]: ...  # canonical ids a payload claims


@dataclass(frozen=True)
class _Scenario:
    file: str
    title: str
    tags: frozenset[str]


class GherkinAdapter:
    """Resolves ``file#Scenario title`` or ``tag:@US-050`` against feature files."""

    def __init__(
        self,
        root: Path,
        paths: list[str],
        delivered_tags: list[str],
        pending_tags: list[str],
        results: str | None,
    ) -> None:
        self._root = root
        self._paths = paths
        self._delivered = frozenset(delivered_tags)
        self._pending = frozenset(pending_tags)
        self._results_path = results
        self._scenarios: list[_Scenario] | None = None
        self._results: dict[str, bool] | None = None

    def _load(self) -> list[_Scenario]:
        if self._scenarios is not None:
            return self._scenarios
        found: list[_Scenario] = []
        for pattern in self._paths:
            for fp in sorted(self._root.glob(pattern)):
                pending: set[str] = set()
                for line in fp.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("@"):
                        pending |= set(_TAG_RE.findall(stripped))
                        continue
                    m = _SCENARIO_RE.match(line)
                    if m:
                        found.append(_Scenario(fp.name, m.group(1), frozenset(pending)))
                        pending = set()
                    elif stripped and not stripped.startswith("#"):
                        pending = set()
        self._scenarios = found
        return found

    def _load_results(self) -> dict[str, bool]:
        """Map ``file#scenario`` -> passed, from a cucumber-json report if configured.

        Keyed by ``file#name`` (matching :meth:`_id`), not the bare scenario name, so two
        features with a same-named scenario don't collide (#42). A Scenario Outline expands to
        one row per Examples line, all sharing the name — those are AND-ed (every example must
        pass), not last-write-wins.
        """
        if self._results is not None:
            return self._results
        out: dict[str, bool] = {}
        if self._results_path:
            rp = self._root / self._results_path
            if rp.exists():
                data: object = json.loads(rp.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for feature in cast("list[object]", data):
                        if not isinstance(feature, dict):
                            continue
                        feat = cast("dict[str, object]", feature)
                        uri = feat.get("uri")
                        fname = Path(uri).name if isinstance(uri, str) else None
                        elements = feat.get("elements")
                        if not isinstance(elements, list):
                            continue
                        for el in cast("list[object]", elements):
                            if not isinstance(el, dict):
                                continue
                            el_d = cast("dict[str, object]", el)
                            name = el_d.get("name")
                            steps = el_d.get("steps")
                            if isinstance(name, str) and isinstance(steps, list):
                                key = f"{fname}#{name}" if fname else name
                                passed = _steps_passed(cast("list[object]", steps))
                                out[key] = out.get(key, True) and passed
        self._results = out
        return out

    @staticmethod
    def _id(s: _Scenario) -> str:
        return f"{s.file}#{s.title}"

    def _match(self, payload: str) -> list[_Scenario]:
        """The scenarios a locator payload refers to (``tag:@X`` or ``file#title``)."""
        scenarios = self._load()
        if payload.startswith("tag:"):
            want = payload[4:]
            return [s for s in scenarios if want in s.tags]
        file_part, _, title = payload.partition("#")
        return [s for s in scenarios if s.title == title and (not file_part or s.file == file_part)]

    def inventory(self) -> list[str]:
        """Every scenario, as ``file#title`` — the universe the orphan report diffs against."""
        return sorted({self._id(s) for s in self._load()})

    def covers(self, payload: str) -> list[str]:
        """The scenarios (as ``file#title``) a referenced payload claims."""
        return sorted({self._id(s) for s in self._match(payload)})

    def resolve(self, payload: str) -> ProofResult:
        matches = self._match(payload)
        if not matches:
            return ProofResult(ProofState.BROKEN, False, f"no scenario matches '{payload}'")

        results = self._load_results()
        if results:
            states = [results.get(self._id(s)) for s in matches]
            missing = [self._id(s) for s, v in zip(matches, states, strict=True) if v is None]
            if missing:
                # Wired a results artifact but a matched scenario isn't in it — renamed,
                # filtered, crashed, or sharded away. Do NOT fall through to the tag and
                # call it delivered (#41); surface that it never ran.
                return ProofResult(
                    ProofState.PENDING,
                    False,
                    f"results configured but scenario not in report: {', '.join(missing)}",
                )
            if all(states):
                return ProofResult(ProofState.DELIVERED, False, "results: passed")
            return ProofResult(ProofState.PENDING, False, "results: failing")
        tags: frozenset[str] = frozenset()
        for s in matches:
            tags |= s.tags
        if tags & self._delivered:
            return ProofResult(ProofState.DELIVERED, True, "tagged delivered")
        if tags & self._pending:
            return ProofResult(ProofState.PENDING, True, "tagged pending")
        return ProofResult(ProofState.PENDING, True, "found, untagged")


class PytestAdapter:
    """Resolves ``path::test_name`` by existence, upgraded by a junit report if given."""

    def __init__(self, root: Path, results: str | None) -> None:
        self._root = root
        self._results_path = results
        self._results: dict[str, bool] | None = None

    def _load_results(self) -> dict[str, bool]:
        if self._results is not None:
            return self._results
        out: dict[str, bool] = {}
        if self._results_path:
            rp = self._root / self._results_path
            if rp.exists():
                tree = ET.parse(rp)
                for case in tree.iter("testcase"):
                    name = case.get("name", "")
                    failed = any(c.tag in ("failure", "error") for c in case)
                    skipped = any(c.tag == "skipped" for c in case)
                    if name:
                        out[name] = not failed and not skipped
        self._results = out
        return out

    def resolve(self, payload: str) -> ProofResult:
        # Node id: file[::Class[::Nested]]::test_name, each segment may carry [params].
        parts = [p.split("[")[0] for p in payload.split("::")]
        file_part = parts[0]
        node = parts[1:]
        func = node[-1] if node else ""
        classes = node[:-1]  # class path for class-based tests (file::TestX::test_y)
        fp = self._root / file_part
        if not fp.exists():
            return ProofResult(ProofState.BROKEN, False, f"no file '{file_part}'")
        text = fp.read_text(encoding="utf-8")
        missing = [f"class {c}" for c in classes if f"class {c}" not in text]
        if func and f"def {func}" not in text:
            missing.append(f"def {func}")
        if missing:
            return ProofResult(ProofState.BROKEN, False, f"no {', '.join(missing)} in {file_part}")
        results = self._load_results()
        if func in results:
            ok = results[func]
            return ProofResult(
                ProofState.DELIVERED if ok else ProofState.PENDING,
                False,
                "junit: passed" if ok else "junit: failing",
            )
        return ProofResult(ProofState.DELIVERED, True, "test exists")


class FilesAdapter:
    """Resolves ``path`` to a verification script's existence.

    For proofs that are executable models/scripts, not pytest tests. Existence is a
    *declared* DELIVERED — a script existing is not a script passing; a run/result
    marker (confirmed) is left for later, mirroring the gherkin/pytest results split.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, payload: str) -> ProofResult:
        fp = self._root / payload
        if not fp.exists():
            return ProofResult(ProofState.BROKEN, False, f"no file '{payload}'")
        return ProofResult(ProofState.DELIVERED, True, "script exists")


class AcceptAdapter:
    """Resolves ``who@date`` to a human sign-off — a functional acceptance, not a test.

    Some needs are accepted by a person, not proven by an automated test. This records
    that as a *declared* DELIVERED (``*``), visibly distinct from a machine-checked proof;
    it never goes BROKEN, because it is an assertion, like a tag.
    """

    def resolve(self, payload: str) -> ProofResult:
        who, _, date = payload.partition("@")
        detail = "accepted" + (f" by {who}" if who else "") + (f" on {date}" if date else "")
        return ProofResult(ProofState.DELIVERED, True, detail)


class CoverageAdapter:
    """Resolves a category path against a catalog of existing categories (one per line).

    DELIVERED when a category matches (already covered — point them at it); PENDING when
    nothing matches (declared, not yet covered — an honest gap, not a build failure).
    """

    def __init__(self, root: Path, catalog: str) -> None:
        self._path = root / catalog
        self._cats: set[str] | None = None

    def _load(self) -> set[str]:
        if self._cats is None:
            out: set[str] = set()
            if self._path.exists():
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        out.add(s)
            self._cats = out
        return self._cats

    def inventory(self) -> list[str]:
        """Every catalog category — the universe a coverage proof can point at (#54)."""
        return sorted(self._load())

    def resolve(self, payload: str) -> ProofResult:
        if payload in self._load():
            return ProofResult(ProofState.DELIVERED, True, f"covered by '{payload}'")
        return ProofResult(ProofState.PENDING, True, f"no category matches '{payload}'")


class FieldAdapter:
    """Resolves a field name against an upstream schema/sample JSON.

    Schema: ``{"surfaced": [...], "received": [...]}``. DELIVERED if the field is surfaced;
    PENDING otherwise, with a distinct detail for 'received but not surfaced' vs 'not
    received upstream' — a different fix. Never a hard failure.
    """

    def __init__(self, root: Path, schema: str) -> None:
        self._path = root / schema
        self._data: tuple[set[str], set[str]] | None = None

    def _load(self) -> tuple[set[str], set[str]]:
        if self._data is None:
            surfaced: set[str] = set()
            received: set[str] = set()
            if self._path.exists():
                raw: object = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    d = cast("dict[str, object]", raw)
                    s, r = d.get("surfaced"), d.get("received")
                    if isinstance(s, list):
                        surfaced = {x for x in cast("list[object]", s) if isinstance(x, str)}
                    if isinstance(r, list):
                        received = {x for x in cast("list[object]", r) if isinstance(x, str)}
            self._data = (surfaced, received)
        return self._data

    def inventory(self) -> list[str]:
        """Every field the upstream schema knows (surfaced or received) — the universe (#54)."""
        surfaced, received = self._load()
        return sorted(surfaced | received)

    def resolve(self, payload: str) -> ProofResult:
        surfaced, received = self._load()
        if payload in surfaced:
            return ProofResult(ProofState.DELIVERED, True, f"'{payload}' present and surfaced")
        if payload in received:
            return ProofResult(ProofState.PENDING, True, f"'{payload}' received but not surfaced")
        return ProofResult(ProofState.PENDING, True, f"'{payload}' not received upstream")


class OutcomeAdapter:
    """Resolves an observable-outcome key against a recorded results file (#25).

    A proof that asserts externally-observable behaviour — an HTTP request/response pair, a UI
    assertion — instead of binding to test internals (a pytest node, a Gherkin step), so it
    survives a reimplementation and describes what a user can observe. The assertion runs
    *outside* prodc (a harness, a probe); its pass/fail is recorded in a JSON results file
    (``{"<outcome key>": true|false}``, or ``{"<key>": {"passed": bool}}``), and prodc only reads
    that — records-only, never a live call, never a hard failure of its own.

    DELIVERED when the key is recorded passing; PENDING when it is recorded failing or absent from
    a present file; BROKEN when the results file itself is absent (nothing to resolve against).
    """

    def __init__(self, root: Path, results: str) -> None:
        self._path = root / results
        self._data: dict[str, bool] | None = None
        self._loaded = False

    def _load(self) -> dict[str, bool] | None:
        if not self._loaded:
            self._loaded = True
            if self._path.exists():
                out: dict[str, bool] = {}
                raw: object = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, val in cast("dict[str, object]", raw).items():
                        if isinstance(val, bool):
                            out[key] = val
                        elif isinstance(val, dict):
                            passed = cast("dict[str, object]", val).get("passed")
                            out[key] = passed is True
                self._data = out
        return self._data

    def resolve(self, payload: str) -> ProofResult:
        data = self._load()
        if data is None:
            return ProofResult(ProofState.BROKEN, False, f"no results file '{self._path.name}'")
        if payload not in data:
            return ProofResult(ProofState.PENDING, False, f"outcome '{payload}' not in results")
        if data[payload]:
            return ProofResult(ProofState.DELIVERED, False, f"outcome '{payload}' recorded passing")
        return ProofResult(ProofState.PENDING, False, f"outcome '{payload}' recorded failing")


class PrototypeAdapter:
    """Resolves ``ref@who@date`` to a prototype validated with users in discovery.

    For perception/experience needs with no pass/fail test: a prototype shown to users in
    an interview is real evidence of the need and the chosen direction. A *declared*
    DELIVERED (``*``), distinct from a shipped-feature test and from a human sign-off
    (accept) — this validates the need/direction, not the implementation.
    """

    def resolve(self, payload: str) -> ProofResult:
        ref, _, rest = payload.partition("@")
        who, _, date = rest.partition("@")
        detail = "prototype " + (ref or "?")
        detail += f" shown to {who}" if who else ""
        detail += f" on {date}" if date else ""
        return ProofResult(ProofState.DELIVERED, True, detail)


class External:
    """Wraps a proof adapter that resolves against a sibling repo checked out at ``repo``.

    If the sibling is absent the fact could not be read at all → UNRESOLVED, distinct
    from a BROKEN locator (read, resolves to nothing) and not a coverage miss. On a read,
    the sibling's git HEAD is appended to the detail so the result is traceable to the
    exact upstream revision (reproducible across machines, not just per-checkout).
    """

    def __init__(self, inner: Adapter, repo: Path) -> None:
        self._inner = inner
        self._repo = repo

    def resolve(self, payload: str) -> ProofResult:
        if not self._repo.exists():
            return ProofResult(
                ProofState.UNRESOLVED, False, f"sibling '{self._repo.name}' not checked out"
            )
        res = self._inner.resolve(payload)
        rev = _git_head(self._repo)
        suffix = f" @ {self._repo.name}:{rev}" if rev else f" @ {self._repo.name}"
        return ProofResult(res.state, res.declared, res.detail + suffix)


@dataclass(frozen=True)
class SourceResult:
    """Whether a Source.locator resolves. Verifies provenance *exists*, not that it is good."""

    ok: bool
    detail: str


class SourceAdapter(Protocol):
    def resolve(self, payload: str) -> SourceResult: ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class FrontmatterAdapter:
    """Resolves ``file#anchor`` against markdown files (e.g. docs/issues/*.md).

    Confirms a heading matching the anchor exists, so a Source citing a ticket/section
    that is absent or renamed surfaces as a dangling (BROKEN) source — the provenance-side
    analogue of a BROKEN proof.
    """

    def __init__(self, root: Path, paths: list[str]) -> None:
        self._root = root
        self._paths = paths
        self._headings: list[tuple[str, str]] | None = None  # (file name, heading text)

    def _load(self) -> list[tuple[str, str]]:
        if self._headings is not None:
            return self._headings
        found: list[tuple[str, str]] = []
        heading_re = re.compile(r"^#{1,6}\s+(.*?)\s*$")
        for pattern in self._paths:
            for fp in sorted(self._root.glob(pattern)):
                for line in fp.read_text(encoding="utf-8").splitlines():
                    m = heading_re.match(line)
                    if m:
                        found.append((fp.name, m.group(1)))
        self._headings = found
        return found

    def resolve(self, payload: str) -> SourceResult:
        file_part, _, anchor = payload.partition("#")
        if not anchor:
            return SourceResult(False, f"no anchor in '{payload}'")
        want = _slug(anchor)
        for fname, heading in self._load():
            if file_part and fname != file_part and not fname.endswith("/" + file_part):
                continue
            hslug = _slug(heading)
            if hslug == want or hslug.startswith(want + "-") or anchor.lower() in heading.lower():
                return SourceResult(True, f"{fname}: '{heading}'")
        return SourceResult(False, f"no heading matches '{payload}'")


# ---------------------------------------------------------------------------
# GitLab source adapter
# ---------------------------------------------------------------------------

#: Callable type for the HTTP fetcher injected into :class:`GitLabSource`.
#: Takes (url, token) and returns (http_status, parsed_json_body).
_GitLabFetcher = Callable[[str, str], tuple[int, object]]


def _gitlab_fetch(url: str, token: str) -> tuple[int, object]:
    """Real HTTP fetcher: GET *url* with a ``PRIVATE-TOKEN`` header."""
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
    try:
        with urllib.request.urlopen(req) as resp:  # type: ignore[assignment]
            return int(resp.status), json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            body: object = json.loads(exc.read())
        except Exception:
            body = {}
        return exc.code, body


class GitLabSource:
    """Resolves a GitLab issue locator against the GitLab REST API.

    Payload formats accepted:
    - ``#123``              — issue iid in the adapter's configured project
    - ``group/project#123`` — issue iid with an inline project path override

    Resolution outcomes:
    - ``ok=True``  with title/author/date — the issue exists and was read
    - ``ok=False`` with "not found" detail — the issue does not exist (BROKEN source)
    - ``ok=True``  with "unverified: …" detail — token absent, auth failed, or host
      unreachable; the source is *not* flagged BROKEN because we could not check it

    The token is never stored here; only the name of the env var that holds it.
    """

    def __init__(
        self,
        base_url: str,
        project: str,
        token_env: str,
        _fetcher: _GitLabFetcher | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._project = project
        self._token_env = token_env
        self._fetch: _GitLabFetcher = _fetcher or _gitlab_fetch

    def resolve(self, payload: str) -> SourceResult:
        # Parse the payload into a (project, iid) pair.
        if "#" not in payload:
            return SourceResult(False, f"invalid gitlab locator '{payload}': expected '#<iid>'")
        project_part, _, iid_s = payload.partition("#")
        project = project_part.strip() or self._project
        if not iid_s.isdigit():
            return SourceResult(False, f"invalid issue iid in '{payload}'")

        # Secrets never leave env-vars.
        token = os.environ.get(self._token_env)
        if not token:
            return SourceResult(True, f"unverified: {self._token_env} not set")

        encoded_project = urllib.parse.quote(project, safe="")
        url = f"{self._base_url}/api/v4/projects/{encoded_project}/issues/{iid_s}"

        try:
            status, data = self._fetch(url, token)
        except OSError as exc:
            return SourceResult(True, f"unverified: host unreachable ({exc})")

        if status == 200 and isinstance(data, dict):
            d = cast("dict[str, object]", data)
            title = d.get("title", "")
            author = d.get("author")
            author_name = (
                cast("dict[str, object]", author).get("username", "") if isinstance(author, dict) else ""
            )
            created_at = str(d.get("created_at", ""))[:10]
            return SourceResult(True, f"#{iid_s} '{title}' by {author_name} at {created_at}")
        if status == 404:
            return SourceResult(False, f"#{iid_s} not found in {project}")
        if status in (401, 403):
            return SourceResult(True, f"unverified: auth failed (check {self._token_env})")
        return SourceResult(True, f"unverified: unexpected status {status} from GitLab")
