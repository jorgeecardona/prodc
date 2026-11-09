"""UX-law catalog entries: the ux pack.

Each :class:`CatalogEntry` maps a law from https://lawsofux.com/ to a principle template
the team can adopt. Five laws have concrete, testable thresholds and carry a :class:`Recipe`
(ux-fitts, ux-hick, ux-von-restorff, ux-miller, ux-jakob). The rest are ``checkable=False``
with no recipe: they require judgment, not a test.

Adopt an entry with ``prodc add principle --from-catalog <id>``. The command writes the
rendered text, a secondary source pointing at the law page, and prints the recipe snippet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Recipe:
    """A placeholder test recipe for a checkable UX-law principle.

    ``kind`` names the test framework. ``snippet`` is a placeholder to replace with a real
    guard from the consumer repo (e.g. from crm or tyko). ``proof_locator_hint`` suggests
    the locator prefix and path to put under ``proofs:`` in the principle YAML.
    """

    kind: Literal["vitest", "playwright", "pytest"]
    summary: str
    snippet: str
    proof_locator_hint: str


@dataclass(frozen=True)
class CatalogEntry:
    """One principle template from a named pack.

    ``id`` is globally unique across all packs and is the id written to the YAML when the
    team adopts the entry. ``text_template`` uses ``{slot}`` placeholders for values the team
    fills in (e.g. ``{N}`` for a numeric threshold). ``checkable`` is True when the rule can
    be verified by a test; a checkable entry must carry a ``recipe``.
    """

    id: str
    pack: str
    title: str
    url: str
    text_template: str
    checkable: bool
    recipe: Recipe | None


# -- checkable entries -------------------------------------------------------

_FITTS = CatalogEntry(
    id="ux-fitts",
    pack="ux",
    title="Fitts's Law",
    url="https://lawsofux.com/fittss-law/",
    text_template=(
        "Every interactive element has a touch/click target of at least 24 x 24 CSS px "
        "(WCAG 2.5.8 desktop) and 44 x 44 CSS px on mobile."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Test the pure button-style function: every size variant sets minHeight >= 24px.",
        # Real guard from crm: apps/website/src/design/fittssLaw.guard.test.ts
        # jsdom has no layout engine; test the pure style function instead of a rendered bounding box.
        snippet="""\
// src/design/fittssLaw.guard.test.ts
import { describe, expect, it } from "vitest";
import { buttonVisualStyle, type ButtonSize } from "./primitives/Button";

const SIZES: ButtonSize[] = ["sm", "md", "lg"];

describe("interactive targets meet the 24x24px minimum (WCAG 2.5.8)", () => {
  it("every size variant sets minHeight >= 24px", () => {
    for (const size of SIZES) {
      const style = buttonVisualStyle({ size });
      expect(
        style.minHeight,
        `size "${size}" minHeight ${style.minHeight} is below the 24px WCAG minimum`,
      ).toBeGreaterThanOrEqual(24);
    }
  });

  it("icon-only buttons set minWidth >= 24px (they form a square target)", () => {
    for (const size of SIZES) {
      const style = buttonVisualStyle({ size, iconOnly: true });
      expect(style.minWidth).toBeGreaterThanOrEqual(24);
    }
  });

  it("checks a real primitive, not an empty fixture", () => {
    const style = buttonVisualStyle({ variant: "primary", size: "md" });
    expect(style.minHeight).toBeDefined();
    expect(SIZES.length).toBeGreaterThan(0);
  });
});
""",
        proof_locator_hint="vitest:src/design/fittssLaw.guard.test.ts::interactive targets meet the 24x24px minimum (WCAG 2.5.8) > every size variant sets minHeight >= 24px",
    ),
)

_HICK = CatalogEntry(
    id="ux-hick",
    pack="ux",
    title="Hick's Law",
    url="https://lawsofux.com/hicks-law/",
    text_template="No top-level navigation menu shows more than {N} items at once.",
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Count top-level nav items per role; each must stay at or below the threshold set when the principle was written.",
        # Real guard from crm: apps/website/src/design/hicksLaw.guard.test.ts
        # Thresholds are the counts at adoption time; the guard prevents growth beyond them.
        snippet="""\
// src/design/hicksLaw.guard.test.ts
import { describe, expect, it } from "vitest";
import { sectionsForRole } from "../lib/navLens";

// Replace MAX_NAV_ITEMS with the current count per role in your app.
const MAX_NAV_ITEMS = {N};

describe("the main nav has at most {N} top-level sections per role", () => {
  it("primary role sees at most {N} sections", () => {
    const sections = sectionsForRole("primary");
    expect(
      sections.length,
      `primary role now has ${sections.length} nav sections (threshold {N}) — ` +
        "update this guard and the principle YAML if the addition is intentional",
    ).toBeLessThanOrEqual(MAX_NAV_ITEMS);
  });

  it("watches a real nav lens: sections are non-empty and named", () => {
    const sections = sectionsForRole("primary");
    expect(sections.length).toBeGreaterThan(0);
    for (const s of sections) {
      expect(s).toMatch(/^\\//);
    }
  });
});
""",
        proof_locator_hint="vitest:src/design/hicksLaw.guard.test.ts::the main nav has at most {N} top-level sections per role > primary role sees at most {N} sections",
    ),
)

_VON_RESTORFF = CatalogEntry(
    id="ux-von-restorff",
    pack="ux",
    title="Von Restorff Effect",
    url="https://lawsofux.com/von-restorff-effect/",
    text_template=(
        "Each form or dialog has at most one primary-action button. "
        "Secondary actions use a lower-emphasis style."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Grep form/dialog source files for variant=\"primary\"; each file must have at most one.",
        # Real guard from crm: apps/website/src/design/vonRestorff.guard.test.ts
        # jsdom has no layout; scan source files statically for variant="primary" in JSX.
        snippet="""\
// src/design/vonRestorff.guard.test.ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const FORM_PATTERN = /(?:Form|Dialog|Modal)\\.tsx$/;
const PRIMARY_BUTTON = /variant="primary"/g;

function formFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...formFiles(full));
    else if (FORM_PATTERN.test(entry)) out.push(full);
  }
  return out;
}

describe("at most one primary button per form or dialog", () => {
  it("no form or dialog file contains more than one variant=\\"primary\\" button", () => {
    const offenders: string[] = [];
    for (const file of formFiles(SRC)) {
      const src = readFileSync(file, "utf8");
      const count = (src.match(PRIMARY_BUTTON) ?? []).length;
      if (count > 1) offenders.push(`${relative(SRC, file)} (${count} primary buttons)`);
    }
    expect(offenders).toEqual([]);
  });

  it("watches a real tree: at least 10 form/dialog files must exist", () => {
    expect(formFiles(SRC).length).toBeGreaterThanOrEqual(10);
  });
});
""",
        proof_locator_hint="vitest:src/design/vonRestorff.guard.test.ts::at most one primary button per form or dialog > no form or dialog file contains more than one variant=\"primary\" button",
    ),
)

_MILLER = CatalogEntry(
    id="ux-miller",
    pack="ux",
    title="Miller's Law",
    url="https://lawsofux.com/millers-law/",
    text_template=(
        "Lists that can exceed {N} items are paginated or grouped into sections. "
        "No flat list renders more than {N} rows without a pager or section heading."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Assert that any list beyond the threshold has pagination or section headers.",
        # TODO: replace with the guard from crm/tyko once it is extracted.
        snippet="""\
// tests/design/list-paging.test.ts
import { render } from '@testing-library/react'
import { ItemList } from '../src/ItemList'

const THRESHOLD = {N}
const items = Array.from({ length: THRESHOLD + 1 }, (_, i) => ({ id: i, label: `Item ${i}` }))

test('long list shows a pager or section headers', () => {
  const { container } = render(<ItemList items={items} />)
  const hasPager = container.querySelector('[aria-label="pagination"]') !== null
  const hasGroups = container.querySelectorAll('[role="group"]').length > 1
  expect(hasPager || hasGroups).toBe(true)
})
""",
        proof_locator_hint="vitest:tests/design/list-paging.test.ts::long list shows a pager or section headers",
    ),
)

_JAKOB = CatalogEntry(
    id="ux-jakob",
    pack="ux",
    title="Jakob's Law",
    url="https://lawsofux.com/jakobs-law/",
    text_template=(
        "Dialogs close on Escape. The Enter key submits the focused form. "
        "The site logo links to the home page."
    ),
    checkable=True,
    recipe=Recipe(
        kind="playwright",
        summary="Verify Escape closes dialogs, Enter submits forms, and the logo links home.",
        # TODO: replace with the guard from crm/tyko once it is extracted.
        snippet="""\
// tests/design/conventions.spec.ts
import { test, expect } from '@playwright/test'

test('Escape closes the dialog', async ({ page }) => {
  await page.goto('/')
  await page.click('[data-testid="open-dialog"]')
  await expect(page.locator('[role="dialog"]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[role="dialog"]')).not.toBeVisible()
})

test('logo links to home', async ({ page }) => {
  await page.goto('/about')
  await page.click('[data-testid="site-logo"]')
  await expect(page).toHaveURL('/')
})
""",
        proof_locator_hint="playwright:tests/design/conventions.spec.ts::Escape closes the dialog",
    ),
)

# -- non-checkable entries ---------------------------------------------------

def _nc(id: str, title: str, url: str, text_template: str) -> CatalogEntry:
    """Build a non-checkable catalog entry (no recipe)."""
    return CatalogEntry(
        id=id,
        pack="ux",
        title=title,
        url=url,
        text_template=text_template,
        checkable=False,
        recipe=None,
    )


UX_CATALOG: tuple[CatalogEntry, ...] = (
    _FITTS,
    _HICK,
    _VON_RESTORFF,
    _MILLER,
    _JAKOB,
    _nc(
        "ux-aesthetic-usability",
        "Aesthetic-Usability Effect",
        "https://lawsofux.com/aesthetic-usability-effect/",
        "Visual polish is applied before usability research, not after.",
    ),
    _nc(
        "ux-choice-overload",
        "Choice Overload",
        "https://lawsofux.com/choice-overload/",
        "No decision screen offers more than {N} options without a guided recommendation.",
    ),
    _nc(
        "ux-chunking",
        "Chunking",
        "https://lawsofux.com/chunking/",
        "Related items are grouped visually so users can process them as single units.",
    ),
    _nc(
        "ux-cognitive-load",
        "Cognitive Load",
        "https://lawsofux.com/cognitive-load/",
        "Each screen has one primary goal. Supporting information is secondary or hidden until needed.",
    ),
    _nc(
        "ux-doherty",
        "Doherty Threshold",
        "https://lawsofux.com/doherty-threshold/",
        "Every interaction responds or shows a loading indicator within 400 ms.",
    ),
    _nc(
        "ux-flow",
        "Flow",
        "https://lawsofux.com/flow/",
        "Task difficulty is matched to user skill: not so easy it is boring, not so hard it blocks.",
    ),
    _nc(
        "ux-goal-gradient",
        "Goal-Gradient Effect",
        "https://lawsofux.com/goal-gradient-effect/",
        "Progress indicators show how much of the task is complete, accelerating effort near the end.",
    ),
    _nc(
        "ux-law-of-common-region",
        "Law of Common Region",
        "https://lawsofux.com/law-of-common-region/",
        "Elements inside a visible boundary are perceived as a group.",
    ),
    _nc(
        "ux-law-of-pragnanz",
        "Law of Pragnanz",
        "https://lawsofux.com/law-of-pr%C3%A4gnanz/",
        "Visual elements are as simple as their meaning allows.",
    ),
    _nc(
        "ux-law-of-proximity",
        "Law of Proximity",
        "https://lawsofux.com/law-of-proximity/",
        "Related controls are placed close together; unrelated controls are separated by space.",
    ),
    _nc(
        "ux-law-of-similarity",
        "Law of Similarity",
        "https://lawsofux.com/law-of-similarity/",
        "Controls with the same visual treatment perform the same kind of action.",
    ),
    _nc(
        "ux-law-of-uniform-connectedness",
        "Law of Uniform Connectedness",
        "https://lawsofux.com/law-of-uniform-connectedness/",
        "Items that are visually connected (by a line, enclosure, or shared background) are related.",
    ),
    _nc(
        "ux-mental-model",
        "Mental Model",
        "https://lawsofux.com/mental-model/",
        "The interface matches users' prior expectations from similar products.",
    ),
    _nc(
        "ux-occams-razor",
        "Occam's Razor",
        "https://lawsofux.com/occams-razor/",
        "When two designs solve the problem equally well, the simpler one ships.",
    ),
    _nc(
        "ux-paradox-of-active-user",
        "Paradox of the Active User",
        "https://lawsofux.com/paradox-of-the-active-user/",
        "Onboarding is short and skippable; core tasks work without reading documentation.",
    ),
    _nc(
        "ux-pareto",
        "Pareto Principle",
        "https://lawsofux.com/pareto-principle/",
        "The {N} most common tasks are optimised first; the remaining tasks are reachable but not featured.",
    ),
    _nc(
        "ux-parkinsons",
        "Parkinson's Law",
        "https://lawsofux.com/parkinsons-law/",
        "Forms have no optional fields unless a user explicitly requests them.",
    ),
    _nc(
        "ux-peak-end",
        "Peak-End Rule",
        "https://lawsofux.com/peak-end-rule/",
        "The most important moment and the last moment of a task are designed deliberately.",
    ),
    _nc(
        "ux-postels",
        "Postel's Law",
        "https://lawsofux.com/postels-law/",
        "Input fields accept leading/trailing whitespace and common alternate formats.",
    ),
    _nc(
        "ux-selective-attention",
        "Selective Attention",
        "https://lawsofux.com/selective-attention/",
        "Critical status changes use motion or color contrast, not only text.",
    ),
    _nc(
        "ux-serial-position",
        "Serial Position Effect",
        "https://lawsofux.com/serial-position-effect/",
        "The most important actions are placed at the start or end of a list or toolbar.",
    ),
    _nc(
        "ux-teslers",
        "Tesler's Law",
        "https://lawsofux.com/teslers-law/",
        "Complexity that cannot be removed from the domain is absorbed by the system, not the user.",
    ),
    _nc(
        "ux-working-memory",
        "Working Memory",
        "https://lawsofux.com/working-memory/",
        "Users are not required to remember information from one screen to use it on another.",
    ),
    _nc(
        "ux-zeigarnik",
        "Zeigarnik Effect",
        "https://lawsofux.com/zeigarnik-effect/",
        "Incomplete tasks are surfaced on return so users can resume where they left off.",
    ),
)
