"""``prodc`` command line: one verb, ``status`` — the board.

Reads the gap between what a named person asked for (needs) and what the test
suite proves (proofs), and prints it sorted by what needs attention first.
Exit 1 on a BROKEN proof; ``--strict`` also exits 1 on an opinion (a need with no
source). A HOLE never fails — it is the honest gap you want people to keep writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError
from .loader import LoaderError, load_needs
from .model import NeedResult, NeedState
from .status import resolve

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


def _provenance(r: NeedResult) -> str:
    if r.need.is_opinion:
        return "OPINION"
    if r.need.only_internal:
        return "INTERNAL"
    who = next((s.who for s in r.need.sources if s.who), None)
    return f"src:{who}" if who else "src"


def _render(results: list[NeedResult]) -> str:
    groups: dict[str, list[NeedResult]] = {}
    for r in results:
        groups.setdefault(r.need.who or "(unassigned)", []).append(r)

    out: list[str] = []
    for who in sorted(groups):
        rs = sorted(groups[who], key=_priority)
        label = next((x.need.label for x in rs if x.need.label), None)
        counts = {s: sum(1 for r in rs if r.state is s) for s in NeedState}
        head = "  ·  ".join(f"{counts[s]} {_LABEL[s]}" for s in NeedState if counts[s])
        opinions = sum(1 for r in rs if r.need.is_opinion)
        title = f"{who}" + (f" ({label})" if label else "")
        out.append(f"\n{title}    {head}")
        if opinions:
            out.append(f"    OPINION (no source): {opinions}")
        for r in rs:
            bang = "!!" if r.need.must else "  "
            star = "*" if r.declared and r.state is NeedState.DELIVERED else " "
            nm = f"{r.delivered}/{r.total}" if r.total else ""
            out.append(
                f"  {bang} {r.need.id:<9} {_LABEL[r.state]:<9}{star} {nm:<5} "
                f"{r.need.text[:48]:<48}  {_provenance(r)}"
            )
            for w in r.warnings:
                out.append(f"       ⚠ {w}")
    return "\n".join(out)


def _to_json(results: list[NeedResult]) -> str:
    payload = [
        {
            "id": r.need.id,
            "who": r.need.who,
            "text": r.need.text,
            "must": r.need.must,
            "state": r.state.value,
            "delivered": r.delivered,
            "total": r.total,
            "declared": r.declared,
            "opinion": r.need.is_opinion,
            "only_internal": r.need.only_internal,
            "detail": r.detail,
            "warnings": r.warnings,
        }
        for r in results
    ]
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

    if args.json:
        print(_to_json(results))
    else:
        commit = _git_rev(cfg.root)
        print(f"prodc status — {cfg.root.name}{f' @ {commit}' if commit else ''}")
        print(_render(results))

    broken = any(r.state is NeedState.BROKEN for r in results)
    opinion = any(r.need.is_opinion for r in results)
    if broken:
        return 1
    if args.strict and opinion:
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
    st.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
