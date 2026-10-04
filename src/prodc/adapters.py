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
from typing import Protocol, cast

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

    def resolve(self, payload: str) -> ProofResult:
        scenarios = self._load()
        if payload.startswith("tag:"):
            want = payload[4:]
            matches = [s for s in scenarios if want in s.tags]
        else:
            file_part, _, title = payload.partition("#")
            matches = [
                s for s in scenarios if s.title == title and (not file_part or s.file == file_part)
            ]
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
        file_part, _, node = payload.partition("::")
        func = node.split("[")[0]  # strip parametrisation
        fp = self._root / file_part
        if not fp.exists():
            return ProofResult(ProofState.BROKEN, False, f"no file '{file_part}'")
        if func and f"def {func}" not in fp.read_text(encoding="utf-8"):
            return ProofResult(ProofState.BROKEN, False, f"no test '{func}' in {file_part}")
        results = self._load_results()
        if func in results:
            ok = results[func]
            return ProofResult(
                ProofState.DELIVERED if ok else ProofState.PENDING,
                False,
                "junit: passed" if ok else "junit: failing",
            )
        return ProofResult(ProofState.DELIVERED, True, "test exists")
