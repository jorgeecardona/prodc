"""``prodc`` command line: the board (``status``) and its sibling commands.

Prints the gap between needs and what the test suite proves, sorted by what needs
attention first. Exit 1 on a BROKEN proof; ``--strict`` also on an opinion. A HOLE
never fails — it is the honest gap you want people to keep writing.

This package splits the former single ``cli`` module into ``app`` (argparse + dispatch),
``commands`` (the handlers), ``render`` (text renderers), ``serialize`` (JSON), and
``common`` (shared helpers). The public surface is unchanged: ``from prodc.cli import main``.
"""

from __future__ import annotations

from .app import main

__all__ = ["main"]
