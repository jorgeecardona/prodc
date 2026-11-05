---
title: "Report: HTML output and PDF path (follow-up to `prodc report`)"
status: open
scope: "M"
verify: test
area: cli
---

## What is done (0.3.x)

- `prodc report` renders the resolved board as a **markdown** document: summary line, needs grouped
  by who, goals/releases/roster/handoffs/recurrence sections, and the open-questions brief. Reuses
  the status engine (`report.render_markdown`), so it never drifts from `prodc status`. `-o/--output`
  writes a file; `--client` scopes it. Dependency-free.

## Status

Items 1 and 2 are done: the self-contained HTML viewer shipped in 0.3.x and is the
print-to-PDF path (GitLab #66, closed). Item 3 is open as GitLab #67.

## What was deferred

1. **Self-contained HTML (`--format html`)** — one file, inline CSS, no new dependency (generate the
   HTML directly rather than pulling a markdown→HTML converter). This is the format a non-technical
   PM actually double-clicks. Keep the same sections as the markdown renderer; share the data-gathering
   so the two never diverge.
2. **PDF** — intentionally NOT built into prodc: a PDF engine (weasyprint/reportlab) or a pandoc
   subprocess would break the pyyaml-only rule. Document the path instead: `prodc report -o status.md`
   then pandoc, or open the `--format html` output and print-to-PDF from the browser. Revisit only if
   there is real demand for a built-in, and even then as an optional extra, never a core dependency.
3. **Polish** — a title/subtitle override, hiding empty sections by flag, and a `--only-open` mode
   that emits just the brief (the pre-meeting agenda as a shareable file).
