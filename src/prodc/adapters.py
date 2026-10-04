"""Proof adapters: resolve a locator payload to a :class:`ProofState`.

An adapter reads a repo as it already is (Gherkin titles, pytest node ids). Status
comes from a test-results artifact (cucumber-json / junit) when configured and
present; otherwise it reports a *declared* state (from tags or existence) and says so.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
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
        status = cast("dict[str, object]", result).get("status") if isinstance(result, dict) else None
        if status != "passed":
            return False
    return True


@dataclass(frozen=True)
class ProofResult:
    state: ProofState
    declared: bool  # True when the state rests on tags/existence, not a results artifact
    detail: str


class Adapter(Protocol):
    def resolve(self, payload: str) -> ProofResult: ...


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
                        found.append(
                            _Scenario(fp.name, m.group(1), frozenset(pending))
                        )
                        pending = set()
                    elif stripped and not stripped.startswith("#"):
                        pending = set()
        self._scenarios = found
        return found

    def _load_results(self) -> dict[str, bool]:
        """Map scenario name -> passed, from a cucumber-json report if configured."""
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
                        elements = cast("dict[str, object]", feature).get("elements")
                        if not isinstance(elements, list):
                            continue
                        for el in cast("list[object]", elements):
                            if not isinstance(el, dict):
                                continue
                            el_d = cast("dict[str, object]", el)
                            name = el_d.get("name")
                            steps = el_d.get("steps")
                            if isinstance(name, str) and isinstance(steps, list):
                                out[name] = _steps_passed(cast("list[object]", steps))
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
            states = [results.get(s.title) for s in matches]
            if all(v is True for v in states):
                return ProofResult(ProofState.DELIVERED, False, "results: passed")
            if any(v is False for v in states):
                return ProofResult(ProofState.PENDING, False, "results: failing")
            # matched scenarios absent from the report → declared only
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
