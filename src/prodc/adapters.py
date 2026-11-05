"""Proof adapters: resolve a locator payload to a :class:`ProofState`.

An adapter reads a repo as it already is (Gherkin titles, pytest node ids). Status
comes from a test-results artifact (cucumber-json / junit) when configured and
present; otherwise it reports a *declared* state (from tags or existence) and says so.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from . import views as _views
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


def _as_score(val: object) -> float | None:
    """A numeric eval score from a results value: a bare number, or ``{"score": N}``.

    ``bool`` is a subclass of ``int`` but is a pass/fail, not a score, so it is rejected. A
    boolean result belongs to :class:`OutcomeAdapter`, not the gate.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        inner = cast("dict[str, object]", val).get("score")
        if isinstance(inner, (int, float)) and not isinstance(inner, bool):
            return float(inner)
    return None


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


# ---------------------------------------------------------------------------
# Command hook: resolve a proof or a source via a user-supplied script (#70)
# ---------------------------------------------------------------------------

#: The token substituted with the need's locator inside a hook command template.
_LOCATOR_PLACEHOLDER = "{locator}"

#: A hook runner: given the built argv, the working dir, and a timeout, run the command
#: and return its parsed-JSON stdout. ``None`` means "could not read" (non-zero exit,
#: timeout, spawn failure, or unparseable output). Injected in tests so no process spawns.
_HookRunner = Callable[[list[str], Path, float], object | None]


def _hook_argv(command: list[str], locator: str) -> list[str]:
    """Build the argv for a hook invocation.

    The locator is the need's, never a shell string: it is substituted for every
    ``{locator}`` placeholder in the configured template, or appended as the final
    argument when the template has no placeholder. It is passed as an argv element, so
    it can never inject a command. The command comes only from trusted config (#70).
    """
    has_placeholder = any(_LOCATOR_PLACEHOLDER in arg for arg in command)
    argv = [arg.replace(_LOCATOR_PLACEHOLDER, locator) for arg in command]
    if not has_placeholder:
        argv.append(locator)
    return argv


def _run_hook(argv: list[str], cwd: Path, timeout: float) -> object | None:
    """Run a hook command (no shell), returning parsed-JSON stdout or ``None``.

    ``None`` is the "could not read" signal and must never resolve to a false pass: a
    non-zero exit, a timeout, a failure to spawn, or unparseable stdout all return it.
    The process inherits the environment so the hook owns any secrets/network itself.
    """
    try:
        # argv form (no shell); the command is from trusted config, the locator is data.
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


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
    `covers` mapping the orphan report uses. An adapter can offer suggestions without
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
        one row per Examples line, all sharing the name. Those are AND-ed (every example must
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
        """Every scenario, as ``file#title``: the universe the orphan report diffs against."""
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
                # Wired a results artifact but a matched scenario isn't in it. Renamed,
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


PYTEST_PATHS = ("**/test_*.py", "**/*_test.py")
VITEST_PATHS = ("**/*.test.ts", "**/*.test.tsx", "**/*.test.js", "**/*.test.jsx")
_SKIPPED_DIRS = frozenset({"node_modules", ".venv", "venv", ".git"})


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """A regex for a glob on a relative posix path: ``**/`` spans directories, ``*`` does not."""
    parts = re.split(r"(\*\*/|\*|\?)", pattern)
    tokens = {"**/": "(?:.*/)?", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(tokens.get(p, re.escape(p)) for p in parts))


def _test_files(root: Path, patterns: Sequence[str]) -> list[tuple[Path, str]]:
    """Each file ``patterns`` match under ``root`` with its text, in path order.

    Never enters a dependency folder, and skips a file that is not UTF-8: discovery only offers
    candidates, so one unreadable file must not stop it.
    """
    regexes = [_glob_regex(p) for p in patterns]
    out: list[tuple[Path, str]] = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)
        for name in names:
            fp = Path(folder) / name
            if any(r.fullmatch(fp.relative_to(root).as_posix()) for r in regexes):
                try:
                    out.append((fp, fp.read_text(encoding="utf-8")))
                except UnicodeDecodeError:
                    continue
    return sorted(out, key=lambda item: item[0])


def _pytest_names(body: list[ast.stmt]) -> list[str]:
    """The ``test*`` functions in ``body`` and, ``Class::``-qualified, those in ``Test*`` classes."""
    out: list[str] = []
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                out.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            out += [f"{node.name}::{n}" for n in _pytest_names(node.body)]
    return out


class PytestAdapter:
    """Resolves ``path::test_name`` by existence, upgraded by a junit report if given."""

    def __init__(
        self, root: Path, results: str | None, paths: Sequence[str] = PYTEST_PATHS
    ) -> None:
        self._root = root
        self._results_path = results
        self._paths = paths
        self._results: dict[str, bool] | None = None

    def inventory(self) -> list[str]:
        """Every ``file::test`` and ``file::Class::test`` in the configured test files."""
        out: list[str] = []
        for fp, text in _test_files(self._root, self._paths):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue  # a broken test file offers nothing; resolving it still reports it
            rel = fp.relative_to(self._root).as_posix()
            out += [f"{rel}::{n}" for n in _pytest_names(tree.body)]
        return sorted(out)

    def _load_results(self) -> dict[str, bool]:
        if self._results is None:
            self._results = {
                c.name: c.outcome == "passed"
                for c in _junit_cases(self._root, self._results_path)
                if c.name
            }
        return self._results

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


@dataclass(frozen=True)
class _JunitCase:
    """One ``<testcase>`` of a vitest junit report: where it lives, its title path, its outcome."""

    file: str  # the test file, relative to the vitest root (``classname`` or ``file``)
    name: str  # the full title path, ``describe > describe > it``
    outcome: str  # "passed" | "failed" | "skipped"
    project: str | None = None  # the Playwright project (a viewport) the case ran in (#112)


def _junit_cases(root: Path, results: str | None) -> list[_JunitCase]:
    """Every ``<testcase>`` of a junit report; empty when no report is configured or written."""
    path = root / results if results else None
    if path is None or not path.exists():
        return []
    out: list[_JunitCase] = []
    for suite in ET.parse(path).iter("testsuite"):
        for case in suite.findall("testcase"):
            if any(c.tag in ("failure", "error") for c in case):
                outcome = "failed"
            elif any(c.tag == "skipped" for c in case):
                outcome = "skipped"
            else:
                outcome = "passed"
            file = case.get("file") or case.get("classname", "")
            out.append(_JunitCase(file, case.get("name", ""), outcome, suite.get("hostname")))
    return out


class VitestAdapter:
    """Resolves ``path/x.test.ts#title`` by existence, upgraded by a vitest junit report (#91).

    ``title`` is the ``it``/``test`` title, or the full ``describe > it`` path to pin one test
    when a leaf title repeats. Without a report the test is DELIVERED by existence (declared),
    like :class:`PytestAdapter`. With ``vitest --reporter=junit`` output it is real: passing →
    DELIVERED, failing → PENDING with ``declared=False`` (so a principle guarded by it reads
    VIOLATED), skipped/todo → PENDING declared (it did not run, so it says nothing either way).

    Report matching follows vitest's defaults: ``classname`` is the file path relative to the
    vitest root (``root`` here) and ``name`` the title path joined by ``" > "``. A
    ``classnameTemplate`` that drops the path is still matched when ``addFileAttribute`` is on.
    """

    def __init__(
        self, root: Path, results: str | None, paths: Sequence[str] = VITEST_PATHS
    ) -> None:
        self._root = root
        self._results_path = results
        self._paths = paths
        self._cases: list[_JunitCase] | None = None

    def inventory(self) -> list[str]:
        """Every ``file#title`` found by an ``it("...")`` or ``test("...")`` call."""
        return _js_inventory(self._root, self._paths, _VITEST_TEST_RE)

    def _load_cases(self) -> list[_JunitCase]:
        if self._cases is None:
            self._cases = _junit_cases(self._root, self._results_path)
        return self._cases

    def resolve(self, payload: str) -> ProofResult:
        file_part, sep, title = payload.partition("#")
        if not sep or not title:
            return ProofResult(ProofState.BROKEN, False, "vitest locator must be file#test title")
        fp = self._root / file_part
        if not fp.exists():
            return ProofResult(ProofState.BROKEN, False, f"no file '{file_part}'")
        text = fp.read_text(encoding="utf-8")
        missing = _titles_missing(text, title, " > ")
        if missing is not None:
            return ProofResult(ProofState.BROKEN, False, f"no test {missing!r} in {file_part}")
        hits = [
            c
            for c in self._load_cases()
            if c.file == file_part and (c.name == title or c.name.endswith(" > " + title))
        ]
        if not hits:
            return ProofResult(ProofState.DELIVERED, True, "test exists")
        if any(c.outcome == "failed" for c in hits):
            return ProofResult(ProofState.PENDING, False, "junit: failing")
        if all(c.outcome == "passed" for c in hits):
            return ProofResult(ProofState.DELIVERED, False, "junit: passed")
        return ProofResult(ProofState.PENDING, True, "junit: skipped")


def _titles_missing(text: str, title: str, sep: str) -> str | None:
    """The first segment of ``title`` that does not appear in a test file's source, else None.

    Each title segment must appear in the source. A quote escaped in the literal is tolerated.
    """
    for seg in (s.strip() for s in title.split(sep)):
        if (
            seg not in text
            and seg.replace("'", "\\'") not in text
            and seg.replace('"', '\\"') not in text
        ):
            return seg
    return None


def _js_inventory(root: Path, patterns: Sequence[str], test_re: re.Pattern[str]) -> list[str]:
    """Every ``file#title`` that ``test_re`` finds; a title with ``${`` is computed, so skipped."""
    out: set[str] = set()
    for fp, text in _test_files(root, patterns):
        rel = fp.relative_to(root).as_posix()
        out |= {f"{rel}#{m['title']}" for m in test_re.finditer(text) if "${" not in m["title"]}
    return sorted(out)


#: A ``test("title", ...)`` call in a Playwright file. ``test.describe(...)`` does not match: the
#: character after ``test`` (and an optional ``.only``/``.skip``/...) must be the opening paren.
_PW_TEST_RE = re.compile(
    r"""\btest(?:\.(?:only|skip|fixme|fail|slow))?\(\s*(?P<q>["'`])(?P<title>(?:\\.|(?!(?P=q)).)*)(?P=q)"""
)
#: An ``it("title", ...)`` or ``test("title", ...)`` call in a vitest file. ``.each`` is not matched:
#: its title is a template, so it names no single test.
_VITEST_TEST_RE = re.compile(
    r"""\b(?:it|test)(?:\.(?:only|skip|todo|fails|concurrent|sequential))?\(\s*(?P<q>["'`])(?P<title>(?:\\.|(?!(?P=q)).)*)(?P=q)"""
)
_PW_SEP = " \u203a "  # Playwright joins a title path with a single right-pointing angle quote
_PW_PROJECT_RE = re.compile(r"^\[(?P<project>[^\]]+)\]\s+(?P<rest>.*)$")


def _pw_case(case: _JunitCase) -> _JunitCase:
    """Move a ``[project] `` name prefix, written by ``includeProjectInTestName``, to ``project``."""
    m = _PW_PROJECT_RE.match(case.name)
    if m is None:
        return replace(case, project=case.project or None)
    return replace(case, name=m["rest"], project=m["project"])


class PlaywrightAdapter:
    """Resolves ``path/x.visual.tsx#title`` against Playwright tests and their junit report (#112).

    For Playwright component tests (``*.visual.tsx``) and any other Playwright test file. The
    locator is the file relative to ``root`` and the test title: the leaf title, or the whole
    ``describe > test`` path to pin one when a leaf repeats. A leading ``[project] `` pins one
    Playwright project, which is how a viewport is named (``#[mobile] fits on a phone``); with none,
    every project that ran the test must pass.

    Without a report the test is DELIVERED by existence (declared), like the vitest kind. With
    Playwright's ``junit`` reporter output it is real: passing is DELIVERED, failing is PENDING with
    ``declared=False`` (so a principle guarded by it reads VIOLATED), skipped is PENDING declared.
    A locator whose file or title is not in the source is BROKEN.

    Report matching follows the reporter (checked against Playwright 1.59): ``classname`` is the
    spec file relative to ``testDir`` (so it matches a locator that ends with it), ``name`` is the
    title path joined by `` \u203a `` (prefixed ``[project] `` only with ``includeProjectInTestName``),
    and the project is the ``hostname`` of the ``testsuite``.
    """

    def __init__(self, root: Path, results: str | None, paths: list[str]) -> None:
        self._root = root
        self._results_path = results
        self._paths = paths
        self._cases: list[_JunitCase] | None = None

    def _load_cases(self) -> list[_JunitCase]:
        if self._cases is None:
            self._cases = [_pw_case(c) for c in _junit_cases(self._root, self._results_path)]
        return self._cases

    def inventory(self) -> list[str]:
        """Every ``file#title`` found by a ``test("...")`` call in the configured files (#112)."""
        return _js_inventory(self._root, self._paths, _PW_TEST_RE)

    def resolve(self, payload: str) -> ProofResult:
        file_part, sep, title = payload.partition("#")
        if not sep or not title:
            return ProofResult(
                ProofState.BROKEN, False, "playwright locator must be file#test title"
            )
        fp = self._root / file_part
        if not fp.exists():
            return ProofResult(ProofState.BROKEN, False, f"no file '{file_part}'")
        project: str | None = None
        m = _PW_PROJECT_RE.match(title)
        if m:
            project, title = m.group("project"), m.group("rest")
        title = title.replace(" > ", _PW_SEP)
        missing = _titles_missing(fp.read_text(encoding="utf-8"), title, _PW_SEP)
        if missing is not None:
            return ProofResult(ProofState.BROKEN, False, f"no test {missing!r} in {file_part}")
        hits = [
            c
            for c in self._load_cases()
            if (c.file == file_part or file_part.endswith("/" + c.file))
            and (c.name == title or c.name.endswith(_PW_SEP + title))
            and (project is None or c.project == project)
        ]
        if not hits:
            return ProofResult(ProofState.DELIVERED, True, "test exists")
        where = f" [{project}]" if project else ""
        if any(c.outcome == "failed" for c in hits):
            bad = sorted({c.project or "?" for c in hits if c.outcome == "failed"})
            return ProofResult(
                ProofState.PENDING, False, f"junit: failing{where} ({', '.join(bad)})"
            )
        if all(c.outcome == "passed" for c in hits):
            return ProofResult(ProofState.DELIVERED, False, f"junit: passed{where}")
        return ProofResult(ProofState.PENDING, True, f"junit: skipped{where}")


class FilesAdapter:
    """Resolves ``path`` to a verification script's existence.

    For proofs that are executable models/scripts, not pytest tests. Existence is a
    *declared* DELIVERED. A script existing is not a script passing; a run/result
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
    """Resolves ``who@date`` to a human sign-off: a functional acceptance, not a test.

    Some needs are accepted by a person, not proven by an automated test. This records
    that as a *declared* DELIVERED (``*``), visibly distinct from a machine-checked proof;
    it never goes BROKEN, because it is an assertion, like a tag.
    """

    def resolve(self, payload: str) -> ProofResult:
        who, _, date = payload.partition("@")
        detail = "accepted" + (f" by {who}" if who else "") + (f" on {date}" if date else "")
        return ProofResult(ProofState.DELIVERED, True, detail)


class ViewsAdapter:
    """Resolves ``client:id`` against the generated view inventory files (#100).

    A view in the inventory is a *declared* DELIVERED (``*``): the view exists, which says
    nothing about whether a need works. A view not in the inventory is BROKEN. A concrete URL
    (``web:/roast/sessions/42``) claims the ``$param`` view it fits. A child view and its parent
    are separate units: claiming one does not claim the other.
    """

    def __init__(self, root: Path, files: list[str]) -> None:
        self._paths = [root / f for f in files]
        self._inv: _views.ViewInventory | None = None
        self._error: str | None = None

    def load(self) -> _views.ViewInventory:
        """The merged inventory; empty when a file could not be read (``resolve`` says why)."""
        if self._inv is None:
            try:
                self._inv = _views.load(self._paths)
            except _views.ViewInventoryError as e:
                self._error = str(e)
                self._inv = _views.ViewInventory()
        return self._inv

    def inventory(self) -> list[str]:
        """Every view, as ``client:id``."""
        return sorted(v.key for v in self.load().views)

    def covers(self, payload: str) -> list[str]:
        """The views (as ``client:id``) a payload claims: the exact id, else every pattern fit."""
        client, _, raw_id = payload.partition(":")
        vid = _views.normalise_id(raw_id)
        same = [v for v in self.load().views if v.client == client]
        exact = [v.key for v in same if v.id == vid]
        if exact:
            return exact
        return sorted(v.key for v in same if _views.matches(v.id, vid))

    def resolve(self, payload: str) -> ProofResult:
        hits = self.covers(payload)
        if self._error is not None:
            return ProofResult(ProofState.UNRESOLVED, False, self._error)
        if not hits:
            return ProofResult(ProofState.BROKEN, False, f"no view '{payload}' in the inventory")
        return ProofResult(ProofState.DELIVERED, True, f"view {', '.join(hits)} exists")


class CoverageAdapter:
    """Resolves a category path against a catalog of existing categories (one per line).

    DELIVERED when a category matches (already covered: point them at it); PENDING when
    nothing matches (declared, not yet covered: an honest gap, not a build failure).
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
        """Every catalog category: the universe a coverage proof can point at (#54)."""
        return sorted(self._load())

    def resolve(self, payload: str) -> ProofResult:
        if payload in self._load():
            return ProofResult(ProofState.DELIVERED, True, f"covered by '{payload}'")
        return ProofResult(ProofState.PENDING, True, f"no category matches '{payload}'")


class FieldAdapter:
    """Resolves a field name against an upstream schema/sample JSON.

    Schema: ``{"surfaced": [...], "received": [...]}``. DELIVERED if the field is surfaced;
    PENDING otherwise, with a distinct detail for 'received but not surfaced' vs 'not
    received upstream'. A different fix. Never a hard failure.
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
        """Every field the upstream schema knows (surfaced or received): the universe (#54)."""
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

    A proof that asserts externally-observable behaviour: an HTTP request/response pair, a UI
    assertion, instead of binding to test internals (a pytest node, a Gherkin step), so it
    survives a reimplementation and describes what a user can observe. The assertion runs
    *outside* prodc (a harness, a probe); its pass/fail is recorded in a JSON results file
    (``{"<outcome key>": true|false}``, or ``{"<key>": {"passed": bool}}``), and prodc only reads
    that. Records-only, never a live call, never a hard failure of its own.

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

    def inventory(self) -> list[str]:
        """Every outcome key recorded in the results file, so ``suggest`` can offer it (#76)."""
        return sorted(self._load() or {})

    def resolve(self, payload: str) -> ProofResult:
        data = self._load()
        if data is None:
            return ProofResult(ProofState.BROKEN, False, f"no results file '{self._path.name}'")
        if payload not in data:
            return ProofResult(ProofState.PENDING, False, f"outcome '{payload}' not in results")
        if data[payload]:
            return ProofResult(ProofState.DELIVERED, False, f"outcome '{payload}' recorded passing")
        return ProofResult(ProofState.PENDING, False, f"outcome '{payload}' recorded failing")


#: Comparators an evalgate locator may use, strongest-looking first so ``>=``/``<=`` match
#: before the bare ``>``/``<`` when scanning the locator.
_EVAL_OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": lambda s, t: s >= t,
    "<=": lambda s, t: s <= t,
    ">": lambda s, t: s > t,
    "<": lambda s, t: s < t,
}
_EVAL_RE = re.compile(r"^(?P<key>.+?)(?P<op><=|>=|<|>)(?P<thr>[^<>=]+)$")


class EvalGateAdapter:
    """Resolves ``metric>=threshold`` against a recorded eval score (#75).

    A scored sibling of :class:`OutcomeAdapter`: where that reads a pass/fail bool, this reads a
    numeric score and gates it against a threshold carried in the locator (``accuracy>=0.9``), so
    one adapter serves many metrics and cutoffs (``>=``, ``<=``, ``>``, ``<``; ``<=`` for a loss
    you want below a bound). The score is produced by an eval harness *outside* prodc and recorded
    in a JSON file (``{"accuracy": {"score": 0.82}}`` or the bare ``{"accuracy": 0.82}``); prodc
    only reads it. Records-only, never runs the eval.

    DELIVERED when the comparison holds; PENDING when the score is recorded but does not meet the
    gate, or the metric is absent from a present file (recorded-below and not-yet-recorded are both
    "not green", as in :class:`OutcomeAdapter`); BROKEN when the results file is absent or the
    locator is malformed. The score, comparator and threshold go in the detail so the board shows
    how far off it is.
    """

    def __init__(self, root: Path, results: str) -> None:
        self._path = root / results
        self._data: dict[str, float] | None = None
        self._loaded = False

    def _load(self) -> dict[str, float] | None:
        if not self._loaded:
            self._loaded = True
            if self._path.exists():
                out: dict[str, float] = {}
                raw: object = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, val in cast("dict[str, object]", raw).items():
                        score = _as_score(val)
                        if score is not None:
                            out[key] = score
                self._data = out
        return self._data

    def inventory(self) -> list[str]:
        """One ``metric>=score`` locator payload per recorded metric (#75, #76).

        Each resolves DELIVERED against the current score, so a suggested gate is a starting point:
        raise the threshold to the real bar before relying on it.
        """
        return sorted(f"{key}>={score:g}" for key, score in (self._load() or {}).items())

    def resolve(self, payload: str) -> ProofResult:
        m = _EVAL_RE.match(payload.strip())
        if not m:
            return ProofResult(
                ProofState.BROKEN, False, f"malformed evalgate '{payload}' (want metric>=threshold)"
            )
        key = m.group("key").strip()
        op = m.group("op")
        try:
            threshold = float(m.group("thr").strip())
        except ValueError:
            return ProofResult(
                ProofState.BROKEN, False, f"evalgate threshold not a number '{payload}'"
            )
        data = self._load()
        if data is None:
            return ProofResult(ProofState.BROKEN, False, f"no results file '{self._path.name}'")
        if key not in data:
            return ProofResult(ProofState.PENDING, False, f"metric '{key}' not in results")
        score = data[key]
        passed = _EVAL_OPS[op](score, threshold)
        verdict = "pass" if passed else "below gate"
        detail = f"{key} {score:g} {op} {threshold:g} ({verdict})"
        return ProofResult(ProofState.DELIVERED if passed else ProofState.PENDING, False, detail)


class CommandProof:
    """Resolves a locator by running a user-supplied command: a proof hook (#70).

    The command comes only from the project config (trusted, like a git hook); the need's
    locator is passed to it as an argv element (never a shell string, never executed). The
    hook queries whatever external system it wants, in any language, and prints a small JSON
    object to stdout::

        {"state": "delivered" | "pending" | "broken" | "unresolved", "detail": "..."}

    A non-zero exit, a timeout, unparseable output, or an unknown ``state`` all resolve to
    UNRESOLVED ("could not read"). Never a false DELIVERED. This lets a team resolve a
    proof against any tool with a small script, with no per-provider code in prodc, and the
    core stays dependency-free.
    """

    def __init__(
        self,
        root: Path,
        command: list[str],
        timeout: float = 10.0,
        _runner: _HookRunner | None = None,
    ) -> None:
        self._root = root
        self._command = command
        self._timeout = timeout
        self._run: _HookRunner = _runner or _run_hook

    def resolve(self, payload: str) -> ProofResult:
        data = self._run(_hook_argv(self._command, payload), self._root, self._timeout)
        if not isinstance(data, dict):
            return ProofResult(ProofState.UNRESOLVED, False, "hook: could not read")
        d = cast("dict[str, object]", data)
        raw_state = d.get("state")
        raw_detail = d.get("detail")
        detail = raw_detail if isinstance(raw_detail, str) else ""
        try:
            state = ProofState(raw_state) if isinstance(raw_state, str) else None
        except ValueError:
            state = None
        if state is None:
            return ProofResult(ProofState.UNRESOLVED, False, f"hook: unknown state {raw_state!r}")
        return ProofResult(state, False, detail or f"hook: {state}")


class PrototypeAdapter:
    """Resolves ``ref@who@date`` to a prototype validated with users in discovery.

    For perception/experience needs with no pass/fail test: a prototype shown to users in
    an interview is real evidence of the need and the chosen direction. A *declared*
    DELIVERED (``*``), distinct from a shipped-feature test and from a human sign-off
    (accept). This validates the need/direction, not the implementation.
    """

    def resolve(self, payload: str) -> ProofResult:
        ref, _, rest = payload.partition("@")
        who, _, date = rest.partition("@")
        detail = "prototype " + (ref or "?")
        detail += f" shown to {who}" if who else ""
        detail += f" on {date}" if date else ""
        return ProofResult(ProofState.DELIVERED, True, detail)


class CitationAdapter:
    """Resolves ``ref@author@year`` to a cited published result: a declared DELIVERED (#75).

    A research question can be settled by citing a result a human vouches for and prodc cannot
    check (a published paper, a textbook theorem). Modelled on :class:`PrototypeAdapter`: a
    *declared* DELIVERED (``*``), never BROKEN, because it is an assertion, like a tag. Kept
    distinct from ``accept`` on purpose: ``accept`` records *who signed off``; a citation records
    *what external result settles it*, and ``ref`` (the thing a reader follows to check the claim)
    is the load-bearing payload ``accept`` has no slot for: ``accept:Smith2019@jorge@...`` would
    read as "jorge accepted it", hiding that the truth is "Smith 2019 shows it".
    """

    def resolve(self, payload: str) -> ProofResult:
        ref, _, rest = payload.partition("@")
        author, _, year = rest.partition("@")
        detail = "cites " + (ref or "?")
        detail += f" by {author}" if author else ""
        detail += f" ({year})" if year else ""
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

    @property
    def inner(self) -> Adapter:
        """The wrapped adapter, so a caller can tell what kind of proof it resolves."""
        return self._inner

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
    that is absent or renamed surfaces as a dangling (BROKEN) source: the provenance-side
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
    - ``#123``              : issue iid in the adapter's configured project
    - ``group/project#123`` : issue iid with an inline project path override

    Resolution outcomes:
    - ``ok=True``  with title/author/date: the issue exists and was read
    - ``ok=False`` with "not found" detail: the issue does not exist (BROKEN source)
    - ``ok=True``  with "unverified: …" detail: token absent, auth failed, or host
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
                cast("dict[str, object]", author).get("username", "")
                if isinstance(author, dict)
                else ""
            )
            created_at = str(d.get("created_at", ""))[:10]
            return SourceResult(True, f"#{iid_s} '{title}' by {author_name} at {created_at}")
        if status == 404:
            return SourceResult(False, f"#{iid_s} not found in {project}")
        if status in (401, 403):
            return SourceResult(True, f"unverified: auth failed (check {self._token_env})")
        return SourceResult(True, f"unverified: unexpected status {status} from GitLab")


class CommandSource:
    """Resolves a Source locator by running a user-supplied command: a source hook (#70).

    The command comes only from the project config (trusted); the locator is passed as an
    argv element, never executed. The hook resolves the locator against any system and
    prints a small JSON object to stdout::

        {"exists": true | false, "who": "...", "date": "...", "quote": "..."}

    ``exists: true`` resolves the source (ok=True, provenance in the detail); ``exists:
    false`` means the cited item is absent: a dangling (BROKEN) source (ok=False). A
    non-zero exit, a timeout, unparseable output, or a missing ``exists`` resolves to
    ``unverified`` (ok=True): a source we could not check is never flagged BROKEN, exactly
    as the GitLab adapter treats an absent token or an unreachable host.
    """

    def __init__(
        self,
        root: Path,
        command: list[str],
        timeout: float = 10.0,
        _runner: _HookRunner | None = None,
    ) -> None:
        self._root = root
        self._command = command
        self._timeout = timeout
        self._run: _HookRunner = _runner or _run_hook

    def resolve(self, payload: str) -> SourceResult:
        data = self._run(_hook_argv(self._command, payload), self._root, self._timeout)
        if not isinstance(data, dict):
            return SourceResult(True, "unverified: hook could not read")
        d = cast("dict[str, object]", data)
        exists = d.get("exists")
        if exists is False:
            detail = d.get("detail")
            return SourceResult(False, detail if isinstance(detail, str) else "not found")
        if exists is not True:
            return SourceResult(True, "unverified: hook gave no 'exists'")
        parts = [
            f"{label} {value}"
            for label, key in (("by", "who"), ("at", "date"))
            if isinstance(value := d.get(key), str) and value
        ]
        quote = d.get("quote")
        if isinstance(quote, str) and quote:
            parts.append(f'"{quote}"')
        return SourceResult(True, " ".join(parts) if parts else "exists")
