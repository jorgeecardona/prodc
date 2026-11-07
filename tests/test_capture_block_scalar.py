"""``capture`` keeps a block-scalar line that starts with ``#`` inside its source."""

from __future__ import annotations

from pathlib import Path

import yaml

from prodc.cli import main

_NEEDS = """needs:
  - id: M-8
    text: t
    sources:
      - kind: assumption
        date: 2026-11-06
        quote: >
          no GQA (gitlab:x#32,
          #33).

  - id: M-9
    text: u
"""


def test_capture_keeps_a_hash_line_of_a_block_scalar(tmp_path: Path) -> None:
    needs = tmp_path / "needs.yaml"
    needs.write_text(_NEEDS, encoding="utf-8")
    cfg = tmp_path / "prodc.toml"
    cfg.write_text('[prodc]\nneeds = ["needs.yaml"]\n', encoding="utf-8")
    args = ["capture", "M-8", "--config", str(cfg), "--kind", "secondary"]
    args += ["--date", "2026-11-07", "--locator", "https://x/1"]
    assert main(args) == 0
    text = needs.read_text(encoding="utf-8")
    sources = yaml.safe_load(text)["needs"][0]["sources"]
    assert sources[0]["quote"].strip() == "no GQA (gitlab:x#32, #33)."
    assert sources[1]["locator"] == "https://x/1"
    assert text.count("#33).") == 1
