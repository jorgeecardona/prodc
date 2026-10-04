"""``prodc`` command line: one verb, ``status`` — the board.

Prints the gap between needs and what the test suite proves, sorted by what needs
attention first. Exit 1 on a BROKEN proof; ``--strict`` also on an opinion. A HOLE
never fails — it is the honest gap you want people to keep writing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from . import __version__
from .config import Config, ConfigError
from .loader import LoaderError, load_needs
from .model import Need, NeedResult, NeedState, SourceKind
from .status import Recurrence, Summary, orphans, recurrence, resolve, summarize

_LABEL = {
    NeedState.DELIVERED: "DELIVERED",
    NeedState.PENDING: "PENDING",
    NeedState.HOLE: "HOLE",
    NeedState.BROKEN: "BROKEN",
    NeedState.UNRESOLVED: "UNRESOLVED",
}


def _priority(r: NeedResult) -> int:
    if r.need.must and r.state is NeedState.HOLE:
        return 0
    return {
        NeedState.BROKEN: 1,
        NeedState.PENDING: 2,
        NeedState.UNRESOLVED: 3,
        NeedState.HOLE: 4,
        NeedState.DELIVERED: 5,
    }[r.state]


# Warrant strength, strongest first: interview > artifact > proxy > internal (Torres).
# proxy = the author is a plausible user guessing as that user — weaker than a document,
# stronger than a bare internal assertion.
_WARRANT_ORDER = (
    SourceKind.INTERVIEW,
    SourceKind.ARTIFACT,
    SourceKind.PROXY,
    SourceKind.INTERNAL,
)


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


def _provenance_counts(results: list[NeedResult]) -> dict[str, int]:
    """How many needs carry each warrant strength (interview/artifact/internal/opinion)."""
    counts = {"interview": 0, "artifact": 0, "proxy": 0, "internal": 0, "opinion": 0}
    for r in results:
        counts[_warrant(r.need).split(":", 1)[0]] += 1
    return counts


def _provenance_line(results: list[NeedResult]) -> str:
    """Per-persona provenance mix — makes internal-only ('0 OPINION' but unvalidated) visible.

    OPINION (no source) stays distinct from a weak INTERNAL source; the headline a PM
    wants is how many needs trace to a real user (interview), not just 'has any source'.
    """
    counts = _provenance_counts(results)
    return "provenance: " + "  ·  ".join(f"{counts[k]} {k}" for k in counts)


def _summary_line(s: Summary) -> str:
    """The leading gap-count line: what needs attention, and overall coverage."""
    parts: list[str] = []
    if s.must_hole:
        parts.append(f"{s.must_hole} must-HOLE")
    if s.broken:
        parts.append(f"{s.broken} BROKEN")
    if s.unresolved:
        parts.append(f"{s.unresolved} UNRESOLVED")
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

    # Size the need column to the terminal; ~54 cols go to the fixed id/state/nm
    # prefix and the warrant suffix. Falls back to 100 cols when there is no tty.
    width = max(30, shutil.get_terminal_size(fallback=(100, 24)).columns - 54)

    out: list[str] = []
    # The Toulmin split: GROUNDS (does a test prove it?) vs WARRANT (user signal it
    # matters?). A need can be green on one and empty on the other — that gap is the point.
    out.append(f"  {'':2} {'id':<9} {'GROUNDS':<10}{'':5} {'need':<{width}}  WARRANT")
    out.append(
        "  legend: * declared (no results artifact)  ·  !! must  ·  "
        "GROUNDS = test proof  ·  WARRANT = evidence source"
    )
    for who in sorted(groups):
        rs = sorted(groups[who], key=_priority)
        label = next((x.need.label for x in rs if x.need.label), None)
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "  ·  ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        title = f"{who}" + (f" ({label})" if label else "")
        out.append(f"\n{title}    {head}")
        out.append(f"    {_provenance_line(rs)}")
        for r in rs:
            bang = "!!" if r.need.must else "  "
            star = "*" if r.declared and r.state is NeedState.DELIVERED else " "
            nm = f"{r.delivered}/{r.total}" if r.total else ""
            out.append(
                f"  {bang} {r.need.id:<9} {_LABEL[r.state]:<9}{star} {nm:<5} "
                f"{r.need.text[:width]:<{width}}  {_warrant(r.need)}"
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


def _render_orphans(orphan_map: dict[str, list[str]]) -> str:
    """The reverse report: proof units that no need references."""
    total = sum(len(v) for v in orphan_map.values())
    out = [f"\norphan proofs (claimed by no need): {total}"]
    for name in sorted(orphan_map):
        for sid in orphan_map[name]:
            out.append(f"     {name}:{sid}")
    return "\n".join(out)


def _render_recurrence(recs: list[Recurrence]) -> str:
    """Baselines shared across clients, most-shared first — the #32 recurrence view."""
    out = [f"\nrecurrence (needs shared across clients): {len(recs)}"]
    for rec in recs:
        who = f" — {', '.join(rec.clients)}" if rec.clients else ""
        out.append(
            f"  {rec.baseline.id:<12} {rec.count} client{'s' if rec.count != 1 else ''}{who}"
            f"    {rec.baseline.text[:60]}"
        )
    return "\n".join(out)


def _to_json(
    results: list[NeedResult],
    summary: Summary,
    orphan_map: dict[str, list[str]],
    recs: list[Recurrence],
) -> str:
    payload = {
        "summary": {
            "total": summary.total,
            "delivered": summary.delivered,
            "pending": summary.pending,
            "hole": summary.hole,
            "must_hole": summary.must_hole,
            "broken": summary.broken,
            "unresolved": summary.unresolved,
            "opinion": summary.opinion,
            "coverage": round(summary.coverage, 4),
            "orphans": sum(len(v) for v in orphan_map.values()),
        },
        "orphans": orphan_map,
        "recurrence": [
            {
                "baseline": rec.baseline.id,
                "text": rec.baseline.text,
                "count": rec.count,
                "clients": list(rec.clients),
            }
            for rec in recs
        ],
        "needs": [
            {
                "id": r.need.id,
                "who": r.need.who,
                "text": r.need.text,
                "must": r.need.must,
                "state": r.state.value,
                "grounds": r.state.value,
                "warrant": _warrant(r.need),
                "client": r.need.client,
                "variant_of": r.need.variant_of,
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


def _load_or_report(args: argparse.Namespace) -> tuple[Config, list[Need]] | None:
    """Load config + needs, or print the error to stderr and return None."""
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"prodc: no config at {cfg_path}", file=sys.stderr)
        return None
    try:
        cfg = Config.load(cfg_path)
        return cfg, load_needs(cfg)
    except (ConfigError, LoaderError) as exc:
        print(f"prodc: {exc}", file=sys.stderr)
        return None


def _cmd_status(args: argparse.Namespace) -> int:
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, needs = loaded
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    summary = summarize(results)
    orphan_map = orphans(needs, cfg.adapters)
    recs = recurrence(needs)

    if args.json:
        print(_to_json(results, summary, orphan_map, recs))
    else:
        commit = _git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(_summary_line(summary))
        print(_render(results))
        if recs:
            print(_render_recurrence(recs))
        if orphan_map:
            print(_render_orphans(orphan_map))

    return _exit_code(args, summary, sum(len(v) for v in orphan_map.values()))


def _exit_code(args: argparse.Namespace, summary: Summary, orphan_total: int) -> int:
    """Gate: 0 unless a threshold is crossed; HOLE never fails.

    Default fails on any BROKEN; ``--max-dangling N`` tolerates N; ``--min-coverage F``
    fails when delivered/total < F; ``--max-orphans N`` fails above N unclaimed proofs;
    ``--strict`` fails on any opinion.
    """
    if args.max_dangling is not None:
        if summary.broken > args.max_dangling:
            return 1
    elif summary.broken:
        return 1
    if args.min_coverage is not None and summary.coverage < args.min_coverage:
        return 1
    if args.max_orphans is not None and orphan_total > args.max_orphans:
        return 1
    if args.strict and summary.opinion:
        return 1
    return 0


def _render_show(r: NeedResult) -> str:
    """One need as a citable answer — the artifact you drop into a thread."""
    need = r.need
    who = (need.who + (f" ({need.label})" if need.label else "")) if need.who else "(unassigned)"
    nm = f"  {r.delivered}/{r.total}" if r.total else ""
    lines = [
        f"{need.id}{'  !!' if need.must else ''}  {need.text}",
        f"  who: {who}",
        f"  grounds: {_LABEL[r.state]}{nm}    warrant: {_warrant(need)}",
    ]
    if need.sources:
        lines.append("  sources:")
        for s in need.sources:
            bits = [s.kind.value]
            bits += [f"{k}={v}" for k, v in (("who", s.who), ("date", s.date),
                                             ("locator", s.locator)) if v]
            line = "    - " + "  ".join(bits)
            lines.append(line + (f'  "{s.quote}"' if s.quote else ""))
    else:
        lines.append("  sources: (none — opinion)")
    if need.children:
        lines.append(f"  children: {', '.join(need.children)}")
    if need.proofs:
        lines.append("  proofs:")
        lines += [f"    - {d}" for d in r.detail]
    elif not need.children:
        lines.append("  proofs: (none — HOLE)")
    lines += [f"  ⚠ {w}" for w in r.warnings]
    return "\n".join(lines)


def _show_json(r: NeedResult) -> str:
    need = r.need
    return json.dumps(
        {
            "id": need.id,
            "text": need.text,
            "who": need.who,
            "label": need.label,
            "must": need.must,
            "state": r.state.value,
            "grounds": r.state.value,
            "warrant": _warrant(need),
            "delivered": r.delivered,
            "total": r.total,
            "declared": r.declared,
            "opinion": need.is_opinion,
            "only_internal": need.only_internal,
            "sources": [
                {"kind": s.kind.value, "who": s.who, "date": s.date,
                 "quote": s.quote, "locator": s.locator}
                for s in need.sources
            ],
            "proofs": list(need.proofs),
            "children": list(need.children),
            "detail": r.detail,
            "warnings": r.warnings,
        },
        indent=2,
    )


def _cmd_show(args: argparse.Namespace) -> int:
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, needs = loaded
    by_id = {r.need.id: r for r in resolve(needs, cfg.adapters, cfg.source_adapters)}
    r = by_id.get(args.need_id)
    if r is None:
        print(f"prodc: no need '{args.need_id}'", file=sys.stderr)
        return 2
    print(_show_json(r) if args.json else _render_show(r))
    return 0


@dataclass(frozen=True)
class _RepoRow:
    """One repo's line in the portfolio roll-up."""

    repo: str
    delivered: int
    total: int
    must_hole: int
    broken: int
    coverage: float
    provenance: dict[str, int]
    error: str | None = None


def _repo_row(config_path: str) -> _RepoRow:
    p = Path(config_path)
    name = p.parent.name or str(p)
    try:
        cfg = Config.load(p)
        needs = load_needs(cfg)
    except (ConfigError, LoaderError, OSError) as exc:
        return _RepoRow(name, 0, 0, 0, 0, 0.0, {}, error=str(exc))
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    s = summarize(results)
    return _RepoRow(
        repo=cfg.root.name,
        delivered=s.delivered,
        total=s.total,
        must_hole=s.must_hole,
        broken=s.broken,
        coverage=round(s.coverage, 4),
        provenance=_provenance_counts(results),
    )


def _render_portfolio(rows: list[_RepoRow]) -> str:
    out = [f"  {'repo':<18} {'cov':>4}  {'must-HOLE':>9}  {'BROKEN':>6}   prov intv/art/prx/int/op"]
    for row in rows:
        if row.error is not None:
            out.append(f"  {row.repo:<18} error: {row.error}")
            continue
        p = row.provenance
        prov = f"{p['interview']}/{p['artifact']}/{p['proxy']}/{p['internal']}/{p['opinion']}"
        cov = f"{round(row.coverage * 100)}%"
        out.append(
            f"  {row.repo:<18} {cov:>4}  {row.must_hole:>9}  {row.broken:>6}   {prov}"
        )
    return "\n".join(out)


def _cmd_portfolio(args: argparse.Namespace) -> int:
    """Roll up many repos into one scoreboard — coverage, must-HOLEs, provenance per repo."""
    rows = [_repo_row(path) for path in args.configs]
    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        print(_render_portfolio(rows))
    return 2 if any(r.error is not None for r in rows) else 0


def _cmd_diff(args: argparse.Namespace) -> int:
    """Diff the current board against a prior `status --json` snapshot."""
    loaded = _load_or_report(args)
    if loaded is None:
        return 2
    cfg, needs = loaded
    current = {r.need.id: r.state.value for r in resolve(needs, cfg.adapters, cfg.source_adapters)}

    snap = Path(args.snapshot)
    try:
        payload: object = json.loads(snap.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"prodc: cannot read snapshot {snap}: {exc}", file=sys.stderr)
        return 2
    raw_needs = cast("dict[str, object]", payload).get("needs") if isinstance(payload, dict) else None
    old: dict[str, str] = {}
    for n in cast("list[object]", raw_needs) if isinstance(raw_needs, list) else []:
        if isinstance(n, dict):
            entry = cast("dict[str, object]", n)
            nid, st = entry.get("id"), entry.get("state")
            if isinstance(nid, str) and isinstance(st, str):
                old[nid] = st

    new = {i: current[i] for i in sorted(current.keys() - old.keys())}
    removed = sorted(old.keys() - current.keys())
    changed = {
        i: [old[i], current[i]] for i in sorted(old.keys() & current.keys()) if old[i] != current[i]
    }
    if args.json:
        print(json.dumps({"new": new, "removed": removed, "changed": changed}, indent=2))
        return 0
    if not (new or removed or changed):
        print("no changes since snapshot")
        return 0
    out: list[str] = []
    for i, st in new.items():
        out.append(f"  new      {i:<10} ({st})")
    for i in removed:
        out.append(f"  removed  {i}")
    for i, (was, now) in changed.items():
        out.append(f"  changed  {i:<10} {was} → {now}")
    print("\n".join(out))
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
    st.add_argument(
        "--max-orphans",
        type=int,
        default=None,
        metavar="N",
        help="gate: exit 1 if more than N proof scenarios are claimed by no need",
    )
    st.set_defaults(func=_cmd_status)

    sh = sub.add_parser("show", help="show one need as a citable answer")
    sh.add_argument("need_id", help="the need id to show, e.g. N-1")
    sh.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    sh.add_argument("--json", action="store_true", help="machine-readable output")
    sh.set_defaults(func=_cmd_show)

    pf = sub.add_parser("portfolio", help="roll up many repos into one scoreboard")
    pf.add_argument("configs", nargs="+", metavar="PRODC_TOML", help="one or more prodc.toml paths")
    pf.add_argument("--json", action="store_true", help="machine-readable output")
    pf.set_defaults(func=_cmd_portfolio)

    df = sub.add_parser("diff", help="diff the current board against a prior status --json snapshot")
    df.add_argument("snapshot", help="path to a saved `prodc status --json` file")
    df.add_argument("--config", default="prodc.toml", help="path to prodc.toml")
    df.add_argument("--json", action="store_true", help="machine-readable output")
    df.set_defaults(func=_cmd_diff)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
