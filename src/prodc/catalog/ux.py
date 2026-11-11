"""UX-law catalog entries: the ux pack.

Each :class:`CatalogEntry` maps a law from https://lawsofux.com/ to a principle template
the team can adopt. Five laws have concrete, testable thresholds and carry a :class:`Recipe`
(ux-fitts, ux-hick, ux-von-restorff, ux-miller, ux-jakob). The rest are ``checkable=False``
with no recipe: they require judgment, not a test.

Adopt an entry with ``prodc add principle --from-catalog <id>``. The command writes the
rendered text, a secondary source pointing at the law page, and prints the recipe snippet.
"""

from __future__ import annotations

from .model import CatalogEntry, Recipe

# -- checkable entries -------------------------------------------------------

_FITTS = CatalogEntry(
    id="ux-fitts",
    pack="ux",
    scope="design",
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
    scope="design",
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
    scope="design",
    title="Von Restorff Effect",
    url="https://lawsofux.com/von-restorff-effect/",
    text_template=(
        "Each form or dialog has at most one primary-action button. "
        "Secondary actions use a lower-emphasis style."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary='Grep form/dialog source files for variant="primary"; each file must have at most one.',
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
        proof_locator_hint='vitest:src/design/vonRestorff.guard.test.ts::at most one primary button per form or dialog > no form or dialog file contains more than one variant="primary" button',
    ),
)

_MILLER = CatalogEntry(
    id="ux-miller",
    pack="ux",
    scope="design",
    title="Miller's Law",
    url="https://lawsofux.com/millers-law/",
    text_template=(
        "Lists that can exceed {N} items are paginated or grouped into sections. "
        "No flat list renders more than {N} rows without a pager or section heading."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Assert that the page-size constant used by your list components stays at or below the agreed threshold.",
        # Real guard from crm: apps/website/src/design/millerLaw.guard.test.ts
        # The guard tests a named constant, not a rendered component; jsdom has no virtual scroll.
        # Adapt PAGE_SIZE_CONSTANT and the import path for your app.
        snippet="""\
// src/design/millerLaw.guard.test.ts
import { describe, expect, it } from "vitest";
import { PAGE_SIZE_CONSTANT } from "./primitives/pageSize";
// Replace PAGE_SIZE_CONSTANT with the constant your list component uses, e.g. DESKTOP_PAGE_SIZE.

const LIMIT = {N};

describe("Miller's Law: list page cap stays within agreed bounds", () => {
  it(`page cap is at most ${LIMIT} rows`, () => {
    expect(
      PAGE_SIZE_CONSTANT,
      `PAGE_SIZE_CONSTANT (${PAGE_SIZE_CONSTANT}) exceeds the ${LIMIT}-row cap — ` +
        "update this guard and the ux-miller principle YAML if the change is intentional",
    ).toBeLessThanOrEqual(LIMIT);
  });

  it("watches a real module: PAGE_SIZE_CONSTANT is defined and positive", () => {
    // Proves the import resolved and the module exports a real value.
    expect(typeof PAGE_SIZE_CONSTANT).toBe("number");
    expect(PAGE_SIZE_CONSTANT).toBeGreaterThan(0);
  });
});
""",
        proof_locator_hint="vitest:src/design/millerLaw.guard.test.ts::Miller's Law: list page cap stays within agreed bounds > page cap is at most {N} rows",
    ),
)

_JAKOB = CatalogEntry(
    id="ux-jakob",
    pack="ux",
    scope="design",
    title="Jakob's Law",
    url="https://lawsofux.com/jakobs-law/",
    text_template=(
        "Dialogs close on Escape. The Enter key submits the focused form. "
        "The site logo links to the home page."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Source-scan every dialog/modal file for Escape handling and check the logo link in the nav component.",
        # Real guard from crm: apps/website/src/design/jakobLaw.guard.test.ts
        # jsdom has no global keydown dispatch in this setup; source scanning is the only way
        # to verify the structural invariants without spinning up a browser.
        # Adapt DIALOG_HOOK and the logo assertion to your app's conventions.
        snippet="""\
// src/design/jakobLaw.guard.test.ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const DIALOG_PATTERN = /(?:Dialog|Modal)\\.tsx$/;

// The shared hook (or keyword) every dialog must use to wire Escape.
// Adapt to match your app: a hook name, an imported function, or a bare string like "Escape".
const DIALOG_HOOK = "useDialogFocus";

function dialogFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...dialogFiles(full));
    else if (DIALOG_PATTERN.test(entry)) out.push(full);
  }
  return out;
}

describe("Jakob's Law: app conventions match user expectations", () => {
  it("every dialog and modal file uses the shared Escape handler", () => {
    const offenders: string[] = [];
    for (const file of dialogFiles(SRC)) {
      const src = readFileSync(file, "utf8");
      if (!src.includes(DIALOG_HOOK)) offenders.push(relative(SRC, file));
    }
    expect(
      offenders,
      `These dialogs do not use ${DIALOG_HOOK}; Escape will not close them:\\n  ${offenders.join("\\n  ")}`,
    ).toEqual([]);
  });

  it("the logo in Nav.tsx links to the home route", () => {
    const nav = readFileSync(join(SRC, "components/Nav.tsx"), "utf8");
    // Adapt the regex to match your logo link. The pattern matches the home
    // route href within 300 characters before the logo element.
    expect(nav, "logo in Nav.tsx must link to the home route").toMatch(
      /to="\\/[^"]*"[\\s\\S]{1,300}<(?:Logo|Wordmark|SiteLogo)/,
    );
  });

  it("watches a real tree: at least 4 dialog/modal files must exist", () => {
    expect(
      dialogFiles(SRC).length,
      "fewer than 4 dialog/modal files found — the guard may not be scanning the right directory",
    ).toBeGreaterThanOrEqual(4);
  });
});
""",
        proof_locator_hint="vitest:src/design/jakobLaw.guard.test.ts::Jakob's Law: app conventions match user expectations > every dialog and modal file uses the shared Escape handler",
    ),
)

# -- non-checkable entries ---------------------------------------------------


def _nc(id: str, title: str, url: str, text_template: str) -> CatalogEntry:
    """Build a non-checkable catalog entry (no recipe)."""
    return CatalogEntry(
        id=id,
        pack="ux",
        scope="design",
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
