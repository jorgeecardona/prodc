"""A need's ``path``: start, outcome, and a click budget, proven by a project test (#99)."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodc.cli.render import render_show
from prodc.config import Config
from prodc.loader import LoaderError, load
from prodc.model import ProofState
from prodc.report import render_markdown
from prodc.status import resolve

_TOML = '[prodc]\nfiles = ["needs/*.yaml"]\n\n[proofs.accept]\nkind = "accept"\n'

_NEEDS = """\
who: roaster
needs:
  - id: R-1
    text: arm a live roast from the preparation page
    path:
      start: /roast/preparation
      outcome: roast-live-armed
      max_clicks: 1
      proof: "accept:jorge@2026-10-24"
  - id: R-2
    text: see last week's roasts
    path:
      start: /roast
      outcome: /roast/history
      max_clicks: 2
  - id: R-3
    text: download the roast log
    path:
      start: /roast
      outcome: /roast/log
      max_clicks: 1
      proof: "nope:x"
"""


def _cfg(tmp_path: Path, needs: str = _NEEDS) -> Config:
    (tmp_path / "needs").mkdir()
    (tmp_path / "prodc.toml").write_text(_TOML, encoding="utf-8")
    (tmp_path / "needs" / "a.yaml").write_text(needs, encoding="utf-8")
    return Config.load(tmp_path / "prodc.toml")


def test_path_loads(tmp_path: Path) -> None:
    need = next(n for n in load(_cfg(tmp_path)).needs if n.id == "R-1")
    assert need.path is not None
    assert need.path.start == "/roast/preparation"
    assert need.path.outcome == "roast-live-armed"
    assert need.path.max_clicks == 1
    assert need.path.proof == "accept:jorge@2026-10-24"


def test_lint_warns_on_budget_without_proof(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    model = load(cfg)
    by_id = {r.need.id: r for r in resolve(list(model.needs), cfg.adapters, cfg.source_adapters)}
    assert by_id["R-1"].path_state is ProofState.DELIVERED
    assert not any("path" in w for w in by_id["R-1"].warnings)
    assert "path budget of 2 click(s) has no proof (#99)" in by_id["R-2"].warnings
    assert by_id["R-3"].path_state is ProofState.BROKEN
    assert "path proof 'nope:x' is BROKEN (#99)" in by_id["R-3"].warnings


def test_show_prints_the_path(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    model = load(cfg)
    r = next(
        r
        for r in resolve(list(model.needs), cfg.adapters, cfg.source_adapters)
        if r.need.id == "R-1"
    )
    assert (
        "  path: /roast/preparation → roast-live-armed, max 1 click, "
        "proof accept:jorge@2026-10-24 [DELIVERED]"
    ) in render_show(r)


def test_report_lists_paths(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    out = render_markdown(cfg, load(cfg))
    assert "## Paths" in out
    assert "| R-2 | /roast → /roast/history, max 2 clicks, no proof |" in out
    assert "| R-3 | /roast → /roast/log, max 1 click, proof nope:x [BROKEN] |" in out


@pytest.mark.parametrize("bad", ["-1", "two", "true"])
def test_max_clicks_must_be_a_whole_number(tmp_path: Path, bad: str) -> None:
    needs = (
        f"needs:\n  - id: X\n    text: t\n    path: {{start: a, outcome: b, max_clicks: {bad}}}\n"
    )
    with pytest.raises(LoaderError, match="max_clicks"):
        load(_cfg(tmp_path, needs))


def test_path_needs_start_and_outcome(tmp_path: Path) -> None:
    with pytest.raises(LoaderError, match=r"path\.outcome"):
        load(_cfg(tmp_path, "needs:\n  - id: X\n    text: t\n    path: {start: a}\n"))
