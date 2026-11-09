# Principles

A `Principle` is a standing commitment the product is built on. It is not validated like a need;
it is chosen. When a need contradicts a principle, the need is withdrawn `out_of_scope` citing it.

See [model](model.md) for the full noun reference and all fields.

## UX laws as design principles

[Laws of UX](https://lawsofux.com/) publishes research-backed interaction laws. A team can adopt
any of them as a `principle` with `scope: design`. Once listed, the board tracks it. Opt in by
listing it; nothing is assumed.

See [ux-laws.md](ux-laws.md) for the full catalog, including `prodc add principle --from-catalog`
usage and the checkable entries that ship with test snippets.

### How to adopt a law

1. Pick a law from [lawsofux.com](https://lawsofux.com/).
2. Write a `text` that is your own concrete rule. Do not copy the law's wording.
   - Bad: "Users spend most of their time on other sites."
   - Good: "Every dialog closes on Escape."
3. Add a `secondary` source pointing at the law's page. Never use `primary` for a published law.
4. If the rule can be checked by a test in your repo, add a `proofs` locator. prodc only links;
   the test lives in the consumer repo.
5. If the rule requires human review (a judgment call), leave `proofs` empty. The board reports
   the principle as STATED. Add an `accept`-declared proof to record a periodic review.

### YAML example

```yaml
# product/needs/principles.yaml

principles:

  - id: ux-fitts
    text: Every interactive element has a tap target of at least 44 x 44 CSS pixels.
    scope: design
    revised_at: "2026-01-01"
    sources:
      - kind: secondary
        date: 2024-11-01
        locator: "https://lawsofux.com/fittss-law/"
    proofs:
      - "test:tests/design/test_tap_targets.py::test_all_targets_meet_minimum"
```

Add `design` to `[principles].scopes` in your `prodc.toml`:

```toml
[principles]
scopes = ["product", "design"]
```

### Checkable laws

These laws have a concrete threshold that a test can verify.

| Law | Concrete rule | Guard |
|---|---|---|
| [Fitts](https://lawsofux.com/fittss-law/) | Tap targets are at least 44 x 44 CSS px (mobile) or 24 x 24 CSS px (desktop). | Computed style check on every interactive element. Must include at least one real component, not an empty selector sweep. |
| [Hick](https://lawsofux.com/hicks-law/) | No navigation menu has more than N items (set N in your rule). | Test counts rendered items in each nav component. |
| [Miller](https://lawsofux.com/millers-law/) | Lists longer than 7 items are either paginated or grouped. | Test checks that any list rendered beyond the threshold has a pager or section headers. |
| [Von Restorff](https://lawsofux.com/von-restorff-effect/) | Each form or modal has at most one primary action button. | Test counts elements with the primary-action class or role per form. |
| [Jakob](https://lawsofux.com/jakobs-law/) | Every dialog closes on Escape. | Keyboard event test on each dialog component. |
| [Postel](https://lawsofux.com/postels-law/) | Input fields accept leading/trailing whitespace and common alternate formats (e.g. phone with or without dashes). | Unit tests for the parsing functions. |
| [Doherty](https://lawsofux.com/doherty-threshold/) | Interactions respond or show a loading state within 400 ms. | Performance test; defer this proof on shared CI runners (mark `declared: false`) because timing is noisy there. |

### Judgment-only laws

These laws cannot be verified by a test. Write a concrete rule and leave `proofs` empty. The
board reports them as STATED, which is honest: the rule is recorded, not mechanically enforced.

To record a periodic review, add a declared proof with `accept`:

```yaml
  - id: ux-aesthetic-usability
    text: Visual polish is applied before usability research, not after.
    scope: design
    sources:
      - kind: secondary
        date: 2024-11-01
        locator: "https://lawsofux.com/aesthetic-usability-effect/"
    proofs:
      - "accept:design-review-2026-Q1"
```

An `accept` proof stays PENDING until a reviewer marks it delivered. It records that someone
checked the principle on a given date, without claiming the code enforces it mechanically.

Laws that fall in this category: Aesthetic-Usability Effect, Peak-End Rule, Zeigarnik Effect,
Tesler's Law, Goal-Gradient Effect, Serial Position Effect.

### Traps

**A guard that passes by finding nothing.** A test that queries `.primary-btn` and passes when
no components exist is not a guard. Include a fixed component in the test so the selector must
find at least one element.

**Copying the law's wording as `text`.** The `text` is your team's rule, not a quote. Write what
your app must do.
