# Visual rules

The visual pack turns published colour rules (WCAG 2.2, Material 3) into principles with a test
recipe each. Use it so a model's colour choices are checked by a test, not by taste.

## Adopt the pack

1. Declare the scope and the pack in `prodc.toml`:

   ```toml
   [principles]
   scopes = ["product", "visual"]
   packs = ["visual"]
   ```

2. Adopt an entry. The command writes the principle, a `secondary` source pointing at the rule,
   and prints the test recipe:

   ```bash
   prodc add principle --from-catalog visual-contrast-text --file product/needs/principles.yaml
   ```

3. Copy the recipe into your repo, adapt the paths, and add the printed locator under `proofs:`.

4. Run `prodc lint`. It lists every entry of the pack you have not adopted or declined.

Decline an entry you considered and do not need:

```bash
prodc add principle --from-catalog visual-color-roles --decline "no design system yet" --file product/needs/principles.yaml
```

## Catalog

| Id | Rule | Proof | Source |
|---|---|---|---|
| visual-contrast-text | Text at least 4.5:1, large text at least 3:1, in every theme | vitest guard | [WCAG 2.2 SC 1.4.3](https://www.w3.org/TR/WCAG22/#contrast-minimum) |
| visual-contrast-ui | Control and state information at least 3:1 | vitest guard | [WCAG 2.2 SC 1.4.11](https://www.w3.org/TR/WCAG22/#non-text-contrast) |
| visual-not-color-alone | Every status has its own text label or icon | vitest guard | [WCAG 2.2 SC 1.4.1](https://www.w3.org/TR/WCAG22/#use-of-color) |
| visual-color-roles | No colour literal outside the token files | vitest guard | [Material 3 color](https://developer.android.com/design/ui/mobile/guides/styles/color) |
| visual-palette-chosen | A person picks the palette from several candidates | `accept:` sign-off | [Anthropic cookbook](https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics) |

## The contrast recipe

The guard computes the WCAG 2.2 contrast ratio for a table of token pairs:

- It compares the raw ratio. 4.48 fails 4.5; it is never rounded up.
- It paints an `rgba()` token over its background before it measures.
- It fails on a colour it cannot parse (for example `oklch()`). It never skips one.
- It checks every theme block (`:root` and `[data-theme="dark"]`).
- It tests itself first: `#000` on `#fff` is 21, `#767676` passes at 4.54, `#777777` fails at
  4.48.

You list the pairs by hand, because a token file does not say which colour sits on which.
Disabled controls are exempt. Placeholder text is not.

A guard that fails on its first run is reporting real problems. On crm it reported placeholder
text (`--ink-faint`) at 2.78:1 on white.

## The palette sign-off

No test can check that a person, not a model, picked the palette. Models tend to pick the same
safe colours, and banning one default only moves them to the next one. So
`visual-palette-chosen` is a sign-off entry:

1. Generate several palettes with different hue anchors and show them side by side (for example
   as Storybook stories).
2. The person picks one. Fill the slots in the principle text: `{palette}`, `{who}`, `{N}`.
3. Add the proof `accept:<who>@<date>`.
4. Add the person's own words as a `primary` source by editing the YAML. Agents never add a
   `primary` source with `prodc add`.

Lint warns about unfilled slots until step 2 is done.

## Upgrading

A new entry in a pack you declared shows up in `prodc lint` after an upgrade. With
`[lint].missing_catalog_principles = "error"`, that fails CI until you adopt or decline it.
