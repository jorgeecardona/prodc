"""``prodc`` command line: one verb, ``status`` — the board.

Prints the gap between needs and what the test suite proves, sorted by what needs
attention first. Exit 1 on a BROKEN proof; ``--strict`` also on an opinion. A HOLE
never fails — it is the honest gap you want people to keep writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError
from .loader import LoaderError, load_needs
from .model import Need, NeedResult, NeedState, SourceKind
from .status import Summary, resolve, summarize

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
}


def _priority(r: NeedResult) -> int:
    if r.need.must and r.state is NeedState.HOLE:
        return 0
    return {
        NeedState.BROKEN: 1,
        NeedState.PENDING: 2,
        NeedState.HOLE: 3,
        NeedState.DELIVERED: 4,
    }[r.state]


# Warrant strength, strongest first: interview > artifact > internal (Torres).
_WARRANT_ORDER = (SourceKind.INTERVIEW, SourceKind.ARTIFACT, SourceKind.INTERNAL)


def _warrant(need: Need) -> str:
    """The warrant column: the strongest source kind, or 'opinion' when unsourced."""
    if need.is_opinion:
        return "opinion"
    kinds = {s.kind for s in need.sources}
    strongest = next(k for k in _WARRANT_ORDER if k in kinds)
    if strongest is SourceKind.INTERVIEW:
        who = next((s.who for s in need.sources if s.kind is SourceKind.INTERVIEW and s.who), None)
        return f"interview:{who}" if who else "interview"
    return strongest.value


def _summary_line(s: Summary) -> str:
    """The leading gap-count line: what needs attention, and overall coverage."""
    parts: list[str] = []
    if s.must_hole:
        parts.append(f"{s.must_hole} must-HOLE")
    if s.broken:
        parts.append(f"{s.broken} BROKEN")
    if s.pending:
        parts.append(f"{s.pending} PENDING")
    if s.hole - s.must_hole:
        parts.append(f"{s.hole - s.must_hole} HOLE")
    if s.opinion:
        parts.append(f"{s.opinion} opinion")
    gaps = "  ·  ".join(parts) if parts else "no gaps"
    return f"gaps: {gaps}    coverage {s.delivered}/{s.total} ({round(s.coverage * 100)}%)"


def _render(results: list[NeedResult]) -> str:
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)

    out: list[str] = []
    # The Toulmin split: GROUNDS (does a test prove it?) vs WARRANT (user signal it
    # matters?). A need can be green on one and empty on the other — that gap is the point.
    out.append(f"  {'':2} {'id':<9} {'GROUNDS':<10}{'':5} {'need':<48}  WARRANT")
    for who in sorted(groups):
        rs = sorted(groups[who], key=_priority)
        label = next((x.need.label for x in rs if x.need.label), None)
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "  ·  ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        title = f"{who}" + (f" ({label})" if label else "")
        out.append(f"\n{title}    {head}")
        for r in rs:
            bang = "!!" if r.need.must else "  "
            star = "*" if r.declared and r.state is NeedState.DELIVERED else " "
            nm = f"{r.delivered}/{r.total}" if r.total else ""
            out.append(
                f"  {bang} {r.need.id:<9} {_LABEL[r.state]:<9}{star} {nm:<5} "
                f"{r.need.text[:48]:<48}  {_warrant(r.need)}"
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


def _to_json(results: list[NeedResult], summary: Summary) -> str:
    payload = {
        "summary": {
            "total": summary.total,
            "delivered": summary.delivered,
            "pending": summary.pending,
            "hole": summary.hole,
            "must_hole": summary.must_hole,
            "broken": summary.broken,
            "opinion": summary.opinion,
            "coverage": round(summary.coverage, 4),
        },
        "needs": [
            {
                "id": r.need.id,
                "who": r.need.who,
                "text": r.need.text,
                "must": r.need.must,
                "state": r.state.value,
                "grounds": r.state.value,
                "warrant": _warrant(r.need),
                "delivered": r.delivered,
                "total": r.total,
                "declared": r.declared,
                "opinion": r.need.is_opinion,
                "only_internal": r.need.only_internal,
                "detail": r.detail,
                "warnings": r.warnings,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)


def _cmd_status(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return 2
    try:
        cfg = Config.load(cfg_path)
        needs = load_needs(cfg)
    except (ConfigError, LoaderError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return 2
    results = resolve(needs, cfg.adapters)
    summary = summarize(results)

    if args.json:
        print(_to_json(results, summary))
    else:
        commit = _git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(_summary_line(summary))
        print(_render(results))

    return _exit_code(args, summary)


def _exit_code(args: argparse.Namespace, summary: Summary) -> int:
    """Gate: 0 unless a threshold is crossed; HOLE never fails.

    Default fails on any BROKEN; ``--max-dangling N`` tolerates N; ``--min-coverage F``
    fails when delivered/total < F; ``--strict`` fails on any opinion.
    """
    if args.max_dangling is not None:
        if summary.broken > args.max_dangling:
            return 1
    elif summary.broken:
        return 1
    if args.min_coverage is not None and summary.coverage < args.min_coverage:
        return 1
    if args.strict and summary.opinion:
        return 1
    return 0


def _git_rev(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if ref.startswith("ref:"):
        target = root / ".git" / ref[4:].strip()
        try:
            return target.read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return None
    return ref[:7]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prodc", description="Product management as code.")
    parser.add_argument("--version", action="version", version=f"prodc {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status", help="show the needs board")
    st.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    st.add_argument("--json", action="store_true", help="machine-readable output")
    st.add_argument("--strict", action="store_true", help="also exit 1 on opinions")
    st.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        metavar="FRAC",
        help="gate: exit 1 if delivered/total < FRAC (0..1)",
    )
    st.add_argument(
        "--max-dangling",
        type=int,
        default=None,
        metavar="N",
        help="gate: tolerate up to N broken locators instead of failing on any",
    )
    st.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
