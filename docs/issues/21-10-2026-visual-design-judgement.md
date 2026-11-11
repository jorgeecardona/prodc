---
title: "Visual needs need a designer's eye: a judge that is not Claude"
status: open
scope: "?"
verify: inspect
area: model
---

## Need

The PM's own words (primary, 21-10-2026):

> "when it comes to visual needs I really need something like the eye of a designer, and I don't
> really trust in claude skills for that [...] users use the product thanks to the fact that they
> can see the product, also, affordance relies in visual cues and visual order. Things like
> consistent elements, spacing, colors, that's something claude is shit at, so we need some
> external tool to systematize that in a better way."

Restated as a need: when a product need is visual (affordance, visual order, consistent elements,
spacing, colour), the PM needs that need judged by something with a designer's eye, so "done"
does not rest on Claude's own opinion of how it looks.

## Why it matters

- Users use the product by seeing it. Affordance is carried by visual cues and visual order.
- Today a visual need can only be "done" by a test proof. A test can check that a button exists,
  not that it reads as a button, sits on the spacing grid, or uses the palette consistently.
- The coding agent is the PM (see the silent goal), and the agent is weak exactly here. A visual
  need closed by the agent alone is an opinion, not evidence.

## Constraint

prodc records structure; it does not call external services. So prodc does not *contain* the
designer brain. It must be able to record that a visual need was judged, by what judge, against
which screenshot/version, and with what verdict: the same way a test proof is recorded.

## Wireframes (21-10-2026)

prodc *uses* wireframes, never *creates* them.

- A wireframe is the visual expectation: layout, visual order, which elements are where. Without
  one, the judge can only say "looks good": an opinion again. With one, it compares the
  screenshot against something concrete.
- A wireframe is a solution, so it hangs on the **decision** that serves the visual need (the
  decision noun is the chosen solution). A need may also reference one as evidence of intent.
- The judge's verdict records which wireframe (path + version) it compared against.
- Creating the wireframe is the PM's job (secondary, 21-10-2026: PMs at Jorge's company used to
  draw wireframes themselves and now prototype with Claude). In prodc the agent is the PM, so the
  agent makes it: outside prodc; prodc records the file. Wireframe or prototype, either counts.
- If Claude made the prototype, Claude cannot also judge it: one more reason the judge is external.

## Idea, not solved: wireframes as code

PM's own framing: "an idea I think will be cool but I still don't know how to solve". It is an
idea in the sense of `21-10-2026-draft-decision-idea.md` (a solution with no settled need/shape).

The thought: prodc is PM-as-code, so the wireframe should be code too: a text file in the repo,
diffable, writable by the agent, referenced by a decision.

What a text wireframe can and cannot carry: it is the element tree in visual order (close to bare
HTML without CSS). It is low-fidelity on purpose, so it checks **structure, order, and which
elements exist**: not spacing or colour. Those come from design tokens + a real screenshot.

Formats found (21-10-2026 search; project activity not checked):
- PlantUML **Salt**: the oldest, most stable text wireframe grammar
  (https://help.gocapable.com/diagrams/wireframe-plantuml.html).
- **WireDSL**: declarative "wireframes as code", exports SVG/PNG/PDF, AI-oriented
  (https://github.com/wire-dsl/wire-dsl).
- **wiremd**: markdown wireframes (https://github.com/akonan/wiremd/).
- Mermaid: no wireframe type, only a request (https://github.com/mermaid-js/mermaid/issues/1184).
- Plain ASCII: no parseable standard found. Good as the PM's quick human sketch; a judge cannot
  reliably read it (what is a button vs a box), and alignment is fragile.

Leaning: ASCII for the sketch, a structured format (Salt / WireDSL / a small prodc YAML of
screens → regions → elements) when a judge must check it. Not decided.

## Open (not decided)

- What the external judge is: a trained model / network, a rule-based visual linter (spacing grid,
  token usage, contrast), a human designer review, or a mix. Needs research.
- Proof kind: a visual-review verdict as a new proof alongside tests, or an attestation
  (`attest`) by a named judge.
- How "consistent" is defined: against a design system (tokens, components) the product owns.
- Whether a visual need is a need flag (`visual: true`) or derived from its flow/role.
- What the judge looks at: a `storybook` proof gives one stable URL per component state
  (`?path=/story/<id>`). That is the page a judge screenshots (08-11-2026).

## Colour rules shipped (11-11-2026)

The rule layer for colour shipped as the `visual` catalog pack ([docs/visual.md](../visual.md)):
contrast (SC 1.4.3, 1.4.11), not colour alone (SC 1.4.1), colour roles, and a palette picked by a
person and signed off with an `accept:` proof. That answers two Open items for colour: the judge
is a mix (rule-based guard plus a human pick), and "consistent" means "against the product's
tokens".

Still open: a verdict on a visual need (not a principle) against a screenshot or wireframe, the
`status` listing, and spacing, visual order and element consistency.

Parked from the pack: an even scale of colour steps (Radix defines 12 steps with one use each,
not "even OKLCH"), and dark surfaces ("lighter with elevation" is Material 2 wording; no
threshold for "desaturated").

## Done when

A visual need on a real board can be closed only by a recorded verdict from a non-Claude judge,
and `status` shows which visual needs lack one.
