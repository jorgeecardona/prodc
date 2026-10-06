#!/usr/bin/env python
"""Benchmark the board on a synthetic project — measure before optimising (#62).

Builds an in-memory board of N needs with realistic text/who/client spread and times
``load``, ``resolve``, and each O(n²) matcher. Run before and after a change to the
matchers to see the effect:

    uv run python scripts/bench_board.py            # default sizes
    uv run python scripts/bench_board.py 1000 5000  # explicit sizes

Deterministic (seeded), dependency-free, never writes outside a temp dir.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

from prodc.config import Config
from prodc.dedup import duplicate_pairs, variant_suggestions, who_variants
from prodc.loader import load
from prodc.model import Need
from prodc.status import resolve

# A small vocabulary so some needs are genuinely similar (the matchers have work to do)
# and most are not (the short-circuit has a chance to fire).
_VERBS = ("export", "see", "filter", "schedule", "archive", "highlight", "log", "print")
_OBJECTS = ("orders", "the day's summary", "a roast", "the run sheet", "past-due invoices",
            "the packing list", "weekly totals", "a customer note")
_QUALIFIERS = ("to CSV", "on the board", "by date", "for one client", "", "in one click")
_WHOS = ("john", "John", "jacob", "Jacob", "max", "maxwell", "sales", "the owner")
_CLIENTS = ("sincerely", "acme", "globex", None)


def _synth_needs(n: int, seed: int = 7) -> list[Need]:
    rng = random.Random(seed)
    needs: list[Need] = []
    for i in range(n):
        text = f"{rng.choice(_VERBS)} {rng.choice(_OBJECTS)} {rng.choice(_QUALIFIERS)}".strip()
        needs.append(
            Need(
                id=f"N-{i}",
                text=text,
                who=rng.choice(_WHOS),
                client=rng.choice(_CLIENTS),
            )
        )
    return needs


def _write_project(root: Path, needs: list[Need]) -> Config:
    (root / "needs").mkdir(parents=True, exist_ok=True)
    (root / "prodc.toml").write_text('[prodc]\nneeds = ["needs/*.yaml"]\n', encoding="utf-8")
    lines = ["needs:"]
    for nd in needs:
        lines.append(f"  - id: {nd.id}")
        lines.append(f'    text: "{nd.text}"')
        lines.append(f"    who: {nd.who}")
        if nd.client is not None:
            lines.append(f"    client: {nd.client}")
    (root / "needs" / "board.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Config.load(root / "prodc.toml")


def _time(label: str, fn: object) -> float:
    start = time.perf_counter()
    fn()  # type: ignore[operator]
    elapsed = time.perf_counter() - start
    print(f"  {label:<22} {elapsed * 1000:8.1f} ms")
    return elapsed


def bench(n: int) -> None:
    needs = _synth_needs(n)
    print(f"\nboard of {n} needs")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_project(Path(tmp), needs)
        _time("load", lambda: load(cfg))
        _time("resolve", lambda: resolve(needs, {}))
        _time("duplicate_pairs", lambda: duplicate_pairs(needs, 0.6))
        _time("variant_suggestions", lambda: variant_suggestions(needs, 0.6))
        _time("who_variants", lambda: who_variants(needs, 0.6))


def main(argv: list[str]) -> int:
    # Default to the sizes that run in a few seconds; the matchers are still O(n²), so pass a
    # larger size explicitly (e.g. 5000) to watch that curve — expect it to be slow by design.
    sizes = [int(a) for a in argv] or [500, 1000]
    for n in sizes:
        bench(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
