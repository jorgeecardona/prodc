# UX Laws

The ux pack maps every law on [lawsofux.com](https://lawsofux.com/) to a principle template.
Adopt any entry as a `design` principle with one command:

```bash
prodc add principle --from-catalog ux-fitts --file product/needs/principles.yaml
```

The command writes the principle YAML, adds a `secondary` source pointing at the law page,
and prints a placeholder test snippet you replace with a real guard from your repo.

Decline a law you have considered but do not need:

```bash
prodc add principle --from-catalog ux-fitts --decline "not relevant for desktop-only tool"
```

A declined entry is marked `withdrawn: out_of_scope` and counts as covered for lint purposes.

---

## Catalog

| Id | Title | Checkable | URL |
|---|---|---|---|
| ux-fitts | Fitts's Law | yes | <https://lawsofux.com/fittss-law/> |
| ux-hick | Hick's Law | yes | <https://lawsofux.com/hicks-law/> |
| ux-von-restorff | Von Restorff Effect | yes | <https://lawsofux.com/von-restorff-effect/> |
| ux-miller | Miller's Law | yes | <https://lawsofux.com/millers-law/> |
| ux-jakob | Jakob's Law | yes | <https://lawsofux.com/jakobs-law/> |
| ux-aesthetic-usability | Aesthetic-Usability Effect | no | <https://lawsofux.com/aesthetic-usability-effect/> |
| ux-choice-overload | Choice Overload | no | <https://lawsofux.com/choice-overload/> |
| ux-chunking | Chunking | no | <https://lawsofux.com/chunking/> |
| ux-cognitive-load | Cognitive Load | no | <https://lawsofux.com/cognitive-load/> |
| ux-doherty | Doherty Threshold | no | <https://lawsofux.com/doherty-threshold/> |
| ux-flow | Flow | no | <https://lawsofux.com/flow/> |
| ux-goal-gradient | Goal-Gradient Effect | no | <https://lawsofux.com/goal-gradient-effect/> |
| ux-law-of-common-region | Law of Common Region | no | <https://lawsofux.com/law-of-common-region/> |
| ux-law-of-pragnanz | Law of Pragnanz | no | <https://lawsofux.com/law-of-pr%C3%A4gnanz/> |
| ux-law-of-proximity | Law of Proximity | no | <https://lawsofux.com/law-of-proximity/> |
| ux-law-of-similarity | Law of Similarity | no | <https://lawsofux.com/law-of-similarity/> |
| ux-law-of-uniform-connectedness | Law of Uniform Connectedness | no | <https://lawsofux.com/law-of-uniform-connectedness/> |
| ux-mental-model | Mental Model | no | <https://lawsofux.com/mental-model/> |
| ux-occams-razor | Occam's Razor | no | <https://lawsofux.com/occams-razor/> |
| ux-paradox-of-active-user | Paradox of the Active User | no | <https://lawsofux.com/paradox-of-the-active-user/> |
| ux-pareto | Pareto Principle | no | <https://lawsofux.com/pareto-principle/> |
| ux-parkinsons | Parkinson's Law | no | <https://lawsofux.com/parkinsons-law/> |
| ux-peak-end | Peak-End Rule | no | <https://lawsofux.com/peak-end-rule/> |
| ux-postels | Postel's Law | no | <https://lawsofux.com/postels-law/> |
| ux-selective-attention | Selective Attention | no | <https://lawsofux.com/selective-attention/> |
| ux-serial-position | Serial Position Effect | no | <https://lawsofux.com/serial-position-effect/> |
| ux-teslers | Tesler's Law | no | <https://lawsofux.com/teslers-law/> |
| ux-working-memory | Working Memory | no | <https://lawsofux.com/working-memory/> |
| ux-zeigarnik | Zeigarnik Effect | no | <https://lawsofux.com/zeigarnik-effect/> |

## Checkable vs. judgment-only

**Checkable** means the rule has a concrete threshold a test can verify. prodc prints a
placeholder snippet when you adopt the entry. Replace the snippet with a real guard from
your repo.

**Judgment-only** (checkable = no) means the rule requires human review. Leave `proofs`
empty. The board reports the principle as STATED. Add an `accept`-declared proof to record
a periodic review.

## Text templates

The `text_template` for each entry is a starting point. Replace every `{slot}` placeholder
with a concrete value before the YAML is committed. For example, `ux-hick` ships with
`{N}` for the item count threshold. Set a real number your team agrees on.

A principle whose text still contains `{slot}` is flagged by `prodc lint`.
