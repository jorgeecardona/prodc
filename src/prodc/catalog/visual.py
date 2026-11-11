"""Visual-design catalog entries: the visual pack.

Each :class:`CatalogEntry` maps a rule from a published source (WCAG 2.2, Material 3) to a
principle template. Four entries have a test that checks them and carry a :class:`Recipe`.
``visual-palette-chosen`` has no test: a person picks the palette and signs it off with an
``accept:`` proof (``sign_off=True``).

The recipes are real guards run against crm's ``src/design/tokens.css``. Adapt the paths, the
pair table, and the status type to the adopting repo. A guard that fails on first run is
reporting real problems, not a broken recipe.
"""

from __future__ import annotations

from .model import CatalogEntry, Recipe

_CONTRAST_SNIPPET = r"""// src/design/contrast.ts: WCAG 2.2 contrast ratio for hex and rgb()/rgba() colours.
// https://www.w3.org/TR/WCAG22/#dfn-relative-luminance

export type Rgba = { r: number; g: number; b: number; a: number };

/** Parse #rgb, #rrggbb, rgb(r, g, b) or rgba(r, g, b, a). Throws on anything else. */
export function parseColor(value: string): Rgba {
  const v = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(v);
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join("") : hex[1];
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
      a: 1,
    };
  }
  const fn = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(v);
  if (fn) {
    return { r: +fn[1], g: +fn[2], b: +fn[3], a: fn[4] === undefined ? 1 : +fn[4] };
  }
  throw new Error(`cannot parse colour ${JSON.stringify(value)}`);
}

/** Paint a translucent colour over an opaque background. */
export function composite(fg: Rgba, bg: Rgba): Rgba {
  const mix = (f: number, b: number) => f * fg.a + b * (1 - fg.a);
  return { r: mix(fg.r, bg.r), g: mix(fg.g, bg.g), b: mix(fg.b, bg.b), a: 1 };
}

function channel(c8: number): number {
  const c = c8 / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(c: Rgba): number {
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}

/** Contrast ratio of fg on bg, unrounded. A translucent fg is composited over bg first. */
export function contrast(fg: string, bg: string): number {
  const back = parseColor(bg);
  if (back.a !== 1) throw new Error(`background ${bg} must be opaque`);
  const front = composite(parseColor(fg), back);
  const [hi, lo] = [luminance(front), luminance(back)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Read `--name: value;` declarations from one CSS block and resolve var() references. */
export function readTokens(css: string, selector: string): Map<string, string> {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const start = clean.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block`);
  const body = clean.slice(start, clean.indexOf("}", start));
  const raw = new Map<string, string>();
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) raw.set(m[1], m[2].trim());
  const resolve = (v: string, depth = 0): string => {
    const ref = /^var\((--[\w-]+)\)$/.exec(v);
    if (!ref) return v;
    const next = raw.get(ref[1]);
    if (next === undefined || depth > 10) throw new Error(`unresolved ${v}`);
    return resolve(next, depth + 1);
  };
  return new Map([...raw].map(([k, v]) => [k, resolve(v)]));
}

// src/design/contrast.guard.test.ts: text >= 4.5:1, large text and UI >= 3:1 (WCAG 2.2 SC 1.4.3, 1.4.11).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { contrast, readTokens } from "./contrast";

type Kind = "text" | "large" | "ui";
const MIN: Record<Kind, number> = { text: 4.5, large: 3, ui: 3 };

// Which token sits on which. Token files do not say it, so the pairs are listed by hand.
// Disabled controls are exempt (SC 1.4.3, 1.4.11). Placeholder text is not.
const PAIRS: Array<{ fg: string; bg: string; kind: Kind }> = [
  { fg: "--ink", bg: "--surface", kind: "text" },
  { fg: "--ink-muted", bg: "--surface", kind: "text" },
  { fg: "--ink-soft", bg: "--surface", kind: "text" },
  { fg: "--ink-faint", bg: "--surface", kind: "text" }, // placeholder text
  { fg: "--ink", bg: "--cream", kind: "text" },
  { fg: "--accent-fg", bg: "--accent", kind: "text" },
  { fg: "--on-inverse", bg: "--surface-inverse", kind: "text" },
  { fg: "--on-inverse-dim", bg: "--surface-inverse", kind: "text" },
  { fg: "--fg-danger", bg: "--bg-danger-soft", kind: "text" },
  { fg: "--fg-warn", bg: "--bg-warn-soft", kind: "text" },
  { fg: "--fg-success", bg: "--bg-success-soft", kind: "text" },
  { fg: "--fg-info", bg: "--bg-info-soft", kind: "text" },
  { fg: "--accent", bg: "--surface", kind: "ui" }, // focus ring
  { fg: "--border-strong", bg: "--surface", kind: "ui" }, // selected input border
];

const CSS = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8");
const THEMES = [":root", '[data-theme="dark"]'];

describe("colour contrast meets WCAG 2.2 AA", () => {
  it("computes the published reference ratios", () => {
    expect(contrast("#000", "#fff")).toBeCloseTo(21, 5);
    expect(contrast("#767676", "#fff")).toBeGreaterThanOrEqual(4.5); // 4.54
    expect(contrast("#777777", "#fff")).toBeLessThan(4.5); // 4.48, never rounded up
    expect(() => contrast("oklch(0.5 0.1 200)", "#fff")).toThrow(); // unparseable fails, not skipped
  });

  const tokensFor = (theme: string) => {
    const light = readTokens(CSS, ":root");
    return theme === ":root" ? light : new Map([...light, ...readTokens(CSS, theme)]);
  };
  const failures = (theme: string, kinds: Kind[]) => {
    const tokens = tokensFor(theme);
    return PAIRS.filter((p) => kinds.includes(p.kind)).flatMap(({ fg, bg, kind }) => {
      const ratio = contrast(tokens.get(fg) ?? fg, tokens.get(bg) ?? bg);
      return ratio < MIN[kind] ? [`${theme} ${fg} on ${bg}: ${ratio.toFixed(2)} < ${MIN[kind]}`] : [];
    });
  };

  it("text pairs meet 4.5:1, large text 3:1, in every theme", () => {
    expect(THEMES.flatMap((t) => failures(t, ["text", "large"]))).toEqual([]);
  });

  it("UI component and state pairs meet 3:1, in every theme", () => {
    expect(THEMES.flatMap((t) => failures(t, ["ui"]))).toEqual([]);
  });

  it("checks real pairs, not an empty table", () => {
    expect(PAIRS.length).toBeGreaterThanOrEqual(8);
  });
});
"""

_CONTRAST_TEXT = CatalogEntry(
    id="visual-contrast-text",
    pack="visual",
    scope="visual",
    title="Contrast (Minimum), WCAG 2.2 SC 1.4.3",
    url="https://www.w3.org/TR/WCAG22/#contrast-minimum",
    text_template=(
        "Text has a contrast ratio of at least 4.5:1 against its background, and large text "
        "(18pt, or 14pt bold) at least 3:1, in every theme. Placeholder text counts. Text on a "
        "disabled control and logotypes are exempt."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary=(
            "Compute the WCAG ratio for each listed text/background token pair in every theme. "
            "The pair table is by hand: token files do not say which colour sits on which."
        ),
        snippet=_CONTRAST_SNIPPET,
        proof_locator_hint=(
            "vitest:src/design/contrast.guard.test.ts::colour contrast meets WCAG 2.2 AA > "
            "text pairs meet 4.5:1, large text 3:1, in every theme"
        ),
    ),
)

_CONTRAST_UI = CatalogEntry(
    id="visual-contrast-ui",
    pack="visual",
    scope="visual",
    title="Non-text Contrast, WCAG 2.2 SC 1.4.11",
    url="https://www.w3.org/TR/WCAG22/#non-text-contrast",
    text_template=(
        "The visual information needed to identify a control and its state (input border, "
        "focus ring, selected state) and the parts of a graphic needed to understand it have a "
        "contrast ratio of at least 3:1 against adjacent colours. Disabled controls and "
        "decorative borders are exempt."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="The same contrast guard as visual-contrast-text; list the pairs with kind 'ui'.",
        snippet=_CONTRAST_SNIPPET,
        proof_locator_hint=(
            "vitest:src/design/contrast.guard.test.ts::colour contrast meets WCAG 2.2 AA > "
            "UI component and state pairs meet 3:1, in every theme"
        ),
    ),
)

_NOT_COLOR_ALONE = CatalogEntry(
    id="visual-not-color-alone",
    pack="visual",
    scope="visual",
    title="Use of Color, WCAG 2.2 SC 1.4.1",
    url="https://www.w3.org/TR/WCAG22/#use-of-color",
    text_template=(
        "No status, state, or action is shown by colour alone: every status variant also has its "
        "own text label or icon."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary=(
            "Walk every value of the status type (kept exhaustive with `satisfies`) and check "
            "each has a non-empty label and no two share one."
        ),
        snippet=r"""// src/design/notColorAlone.guard.test.ts: every status has its own text label (WCAG 2.2 SC 1.4.1).
import { describe, expect, it } from "vitest";
import { type OrderLifecycle, orderStatusLabel } from "./primitives/OrderStatusPill";

// Every value of the status type. `satisfies` makes TypeScript fail when a status is added
// to the type and not here, so the guard stays exhaustive.
const ALL = {
  open: true,
  packed: true,
  out_for_delivery: true,
  delivered: true,
  cancelled: true,
} satisfies Record<OrderLifecycle, true>;

describe("status is never shown by colour alone", () => {
  it("every status renders a non-empty text label", () => {
    for (const status of Object.keys(ALL)) {
      expect(orderStatusLabel(status).trim(), `${status} has no label`).not.toBe("");
    }
  });

  it("no two statuses share a label, so the text tells them apart without colour", () => {
    const labels = Object.keys(ALL).map((s) => orderStatusLabel(s));
    expect(new Set(labels).size).toBe(labels.length);
  });
});
""",
        proof_locator_hint=(
            "vitest:src/design/notColorAlone.guard.test.ts::status is never shown by colour "
            "alone > no two statuses share a label, so the text tells them apart without colour"
        ),
    ),
)

_COLOR_ROLES = CatalogEntry(
    id="visual-color-roles",
    pack="visual",
    scope="visual",
    title="Color roles (Material 3)",
    url="https://developer.android.com/design/ui/mobile/guides/styles/color",
    text_template=(
        "Every colour in the UI comes from a role token ({token_file}). No hex, rgb(), hsl() or "
        "oklch() literal appears outside the token files."
    ),
    checkable=True,
    recipe=Recipe(
        kind="vitest",
        summary="Scan every .css/.ts/.tsx source outside the token files for a colour literal.",
        snippet=r"""// src/design/colorRoles.guard.test.ts: colours come from role tokens, never raw literals.
// Material 3: "use tokens instead of hard-coded color values".
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const TOKEN_FILES = new Set(["design/tokens.css"]); // the only files allowed to hold literals
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : files(path);
    return /\.(css|tsx?)$/.test(name) && !/\.(test|stories)\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("colours come from role tokens", () => {
  it("no colour literal outside the token files", () => {
    const hits = files(SRC)
      .filter((f) => !TOKEN_FILES.has(relative(SRC, f)))
      .flatMap((f) =>
        readFileSync(f, "utf8")
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .split("\n")
          .flatMap((line, i) => (LITERAL.test(line) ? [`${relative(SRC, f)}:${i + 1}`] : [])),
      );
    expect(hits).toEqual([]);
  });

  it("watches a real tree", () => {
    expect(files(SRC).length).toBeGreaterThan(10);
  });
});
""",
        proof_locator_hint=(
            "vitest:src/design/colorRoles.guard.test.ts::colours come from role tokens > "
            "no colour literal outside the token files"
        ),
    ),
)

_PALETTE_CHOSEN = CatalogEntry(
    id="visual-palette-chosen",
    pack="visual",
    scope="visual",
    title="A person picks the palette",
    url="https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics",
    text_template=(
        "The palette is {palette}, picked by {who} from {N} candidates with different hue "
        "anchors shown side by side. A model does not pick the palette alone."
    ),
    checkable=False,
    recipe=None,
    sign_off=True,
)

VISUAL_CATALOG: tuple[CatalogEntry, ...] = (
    _CONTRAST_TEXT,
    _CONTRAST_UI,
    _NOT_COLOR_ALONE,
    _COLOR_ROLES,
    _PALETTE_CHOSEN,
)
"""The visual pack. Adopt with ``prodc add principle --from-catalog <id>``."""
