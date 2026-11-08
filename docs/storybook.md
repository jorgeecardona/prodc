# Storybook

Use this page to point needs at the Storybook stories that show them. prodc reads the
`index.json` that `storybook build` writes. It never reads your stories or app code.

## Set it up

1. Add a proof table to `prodc.toml`:

    ```toml
    [proofs.sb]
    kind = "storybook"
    root = "apps/website"          # where Storybook runs
    url = "https://sb.example.com" # optional: where the built Storybook is published
    ```

2. Build Storybook before you run prodc:

    ```bash
    npx storybook build
    ```

3. Point a need at a story. The id is the one in the story URL (`?path=/story/<id>`):

    ```yaml
    - id: CHK-3
      text: When a buyer's card is declined, they can see why and try another card
      proofs:
        - "sb:checkout-paymentform--declined"
    ```

4. Check the board:

    ```bash
    prodc status
    ```

## What the states mean

- `DELIVERED*`: the story is in the index. The component renders in that state. This does not
  prove the need works, so the `*` (declared) stays.
- `BROKEN`: no such story. A story id changes when its `title` or export name changes. Fix the
  locator to the new id; do not edit the need text.
- `UNRESOLVED`: the index is missing, empty, or in an unknown format. Run `storybook build`.

The detail line says when the index was built. A stale `storybook-static/` gives stale answers.

## One story per state

A need that covers several UI states lists one story for each:

```yaml
proofs:
  - "sb:projects-list--empty"
  - "sb:projects-list--loading"
  - "sb:projects-list--error"
```

A state with no story is a BROKEN proof, so a missing state shows on the board. A locator without
`--` (`sb:projects-list`) claims every story of the component.

## Components no need points at

```toml
[lint]
unjustified_stories = "warn"   # or "error"
```

`prodc lint` then reports each component with no story that a need points at. It works per
component, not per story, so variants do not each need their own need.

## In CI

The index is a build artifact (`storybook-static/` is usually gitignored). Build Storybook in
the same job, before `prodc lint`. Run the build only when stories change, to save pipeline
minutes; a moon task with `inputs` on `.storybook/**` and `**/*.stories.tsx` does that.

## Accessibility

Set `parameters.a11y.test = 'error'` in `.storybook/preview.ts`. An a11y violation then fails
the story's test. prodc does not read story test results yet; see
`docs/issues/08-11-2026-storybook-test-results.md` in the repository.
