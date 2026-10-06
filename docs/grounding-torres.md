# Grounding notes: Teresa Torres, *Continuous Discovery Habits* (2021)

Source: Teresa Torres, *Continuous Discovery Habits: Discover Products That Create Customer Value and Business Value*, Product Talk LLC, 2021.
Purpose: Extract structural material to model a product-management workflow as a state machine for prodc.

---

## 1. The discovery lifecycle / cadence

Torres defines continuous discovery as:

> "At a minimum, weekly touchpoints with customers / By the team building the product / Where they conduct small research activities / In pursuit of a desired outcome" (Ch. 1)

The loop has a recognizable weekly rhythm:

1. **Weekly customer interviews** (story-based, one-hour, one customer per week minimum). Each interview produces an "interview snapshot" — a brief synthesized artifact shared with stakeholders immediately, not in batch.
2. **Opportunity identification**: stories from interviews are filtered and mapped onto the Opportunity Solution Tree (OST).
3. **Target opportunity selection**: compare-and-contrast among leaf-node opportunities using four assessment criteria.
4. **Solution ideation**: individually generate 15–20 solutions; share in group; repeat; dot-vote down to 3 candidates.
5. **Assumption enumeration**: story-map each of the 3 solutions; generate 20–30 assumptions per idea across 5 assumption types; build an assumption map (2×2: importance × evidence); identify "leap of faith" assumptions (top-right quadrant).
6. **Assumption testing**: start with the smallest test that can give an early signal; iterate to bigger tests only if the assumption remains the riskiest after small tests pass; stop testing when enough risk has been removed to build.
7. **Delivery & impact measurement**: instrument the product to evaluate assumption tests in production; track product outcome (leading indicator) and business outcome; discovery continues through and after delivery.

The cycle is explicitly not a phase gate. Discovery and delivery run concurrently, feeding each other.

**OST structure** (four levels, from root to leaves):

```
Desired outcome (business/product metric)
└── Opportunity space (customer needs, pain points, desires)
    └── Sub-opportunities (child nodes; more specific moments)
        └── Assumption tests (leaves off solutions; the test artifacts themselves)
```

Solutions attach to opportunities, not to the outcome directly. Assumption tests attach to solutions.

---

## 2. The "opportunity" concept (maps to prodc's "need")

**Definition** (Ch. 2): "Opportunities represent our customers' needs, pain points, and desires. They represent opportunities to intervene in our customers' lives in a positive way."

Key properties:
- Must be framed from the **customer's perspective**, not the company's. "We want to expand internationally" is not an opportunity; "I struggle to collaborate with teammates in other time zones" is.
- Always grounded in **specific customer stories** heard in interviews. Opportunities surface from individual moments, not generalizations.
- They start as raw, unfiltered interview observations (potential opportunities) and become OST entries only after passing the **3-filter test**:
  1. Is it framed as a customer need, pain point, or desire (not a solution)?
  2. Was it heard in more than one interview, or is it uniquely interesting for this customer?
  3. If addressed, will it drive the desired outcome?
- They are **not validated in the scientific sense**. They are prioritized for exploration. An opportunity can be deprioritized and revisited later.
- Feelings (e.g., "I feel overwhelmed") are not opportunities by themselves. The underlying **cause** of the feeling is the opportunity (e.g., "I have to reconcile data from too many sources").

**Unvalidated vs. prioritized distinction**: Torres does not frame opportunities as "validated" or "invalidated" — that language applies only to assumption tests. An opportunity is either *in scope* (on the OST under a parent, assessed, targeted) or *out of scope* (not on the tree, deprioritized, or pending further interview evidence). Prioritization is a compare-and-contrast, not a validation.

---

## 3. States an opportunity moves through

The following represents the state machine Torres describes, reconstructed from Chapters 5–7 and 9–11:

### Opportunity states

| State | How entered | How exited |
|-------|-------------|------------|
| **heard** | Appears in a customer interview as a story about a specific moment | Passes or fails 3-filter test |
| **filtered-out** | Fails any leg of the 3-filter test | (terminal for now; may resurface in later interviews) |
| **on-tree** | Passes 3-filter test; placed on OST under appropriate parent, given sibling context | Assessed against 4 criteria |
| **reframed** | Placed as feeling/solution-framing; underlying cause identified and substituted | Now re-enters as on-tree with corrected framing |
| **assessed** | Team has evaluated it against the 4 criteria (sizing, market, company, customer factors) | Compare-and-contrast with siblings |
| **targeted** | Selected as the current leaf-node target opportunity (two-way door decision) | Solutions generated for it; or reversed back to assessed if early signals fail |
| **deprioritized** | Compare-and-contrast shows a sibling is more promising right now | Returns to on-tree for later rounds |
| **addressed** | A solution passed assumption testing and has been shipped | Outcome measured; if outcome not achieved, opportunity may be re-opened |

### Solution states (nested under a targeted opportunity)

| State | Description |
|-------|-------------|
| **brainstormed** | One of 15–20 individually generated solution ideas |
| **shortlisted** | Survived dot-vote; one of the 3 candidates being developed in parallel |
| **story-mapped** | Trio has walked through how end-users would use it; team agrees on what it means |
| **assumptions-enumerated** | 20–30 assumptions generated per the 5 types; assumption map completed |
| **under-test** | "Leap of faith" assumptions being tested (small simulation → evaluate behavior against pre-defined success criteria) |
| **surviving-tests** | Tests passing; assumption moving left on assumption map (more known); continuing to next riskiest assumption |
| **failed-test** | A key assumption refuted; solution revised or abandoned; team may redesign around the failed assumption |
| **clear-front-runner** | One of the 3 solutions has emerged as most promising based on comparative assumption testing |
| **shipped** | Built and deployed; impact measured in production |

### Assumption states (nested under a shortlisted solution)

| State | Description |
|-------|-------------|
| **implicit** | Assumption exists but has not been articulated |
| **articulated** | Named and phrased as a positive statement the team needs to be true |
| **mapped** | Placed on assumption map (2×2: importance × evidence) |
| **leap-of-faith** | In top-right quadrant (most important, weakest evidence); queued for testing |
| **being-tested** | Active experiment running; success criteria defined upfront |
| **evidence-gathered** | Test completed; evidence added to assumption map; assumption moved left (more known) |
| **refuted** | Test failed; evidence strongly disconfirms assumption; solution revised or discarded |
| **sufficiently-known** | Enough evidence accumulated that team is comfortable proceeding; not "proven true," just de-risked |

---

## 4. Assumption types and the confirm/refute decision

Torres identifies **5 assumption categories** (Ch. 9):

- **Desirability**: Does anyone want it? Will customers get value? Will they do what we need them to do and trust us to provide it?
- **Viability**: Should we build it? Will it create enough return for the business — more revenue than it costs, or contribution to another business goal?
- **Feasibility**: Can we build it? Includes technical feasibility and organizational feasibility (legal, security, compliance, culture).
- **Usability**: Is it usable? Can customers find what they need? Will they understand how to use it? Can they do what we need them to do?
- **Ethical**: Is there potential harm? Data collection, manipulation risk, inequity, addiction, privacy, harm to relationships?

### How to surface assumptions (the four methods)

1. **Story mapping**: Walk through end-user steps for each actor. Every step a user takes generates desirability, usability, and feasibility assumptions. Use this to surface assumptions you've baked into the design.
2. **Pre-mortem**: "Imagine it's six months in the future; the product launched and was a complete failure. What went wrong?" Every reason generates an assumption you depend on being false — restate it as a positive assumption.
3. **Walk the OST lines**: Work backwards from solution to target opportunity to desired outcome. "This solution will address the target opportunity because…" and "Addressing the target opportunity will drive the desired outcome because…" — each inference is an assumption.
4. **Explore potential harm**: "What is the potential harm in offering this solution?" Generates ethical assumptions.

### How to prioritize assumptions (assumption mapping)

Plot each assumption on a 2×2 grid:
- X-axis: evidence (strong evidence → left; weak evidence → right)
- Y-axis: importance to success (more important → top; less important → bottom)

**"Leap of faith" assumptions** = top-right quadrant (most important, weakest evidence). These are tested first. The team starts with the 2–3 in the very top-right corner, not the whole quadrant.

### How a team decides an assumption is confirmed or refuted

Torres is explicit that this is **not a scientific confirmation/invalidation**. The goal is risk mitigation, not truth-seeking (Ch. 10):

> "We are not validating or invalidating anything. It's important that we recognize that our research findings are not truths — they are merely confirming or disconfirming evidence that either supports or refutes our point of view. Our goal as a product team is not to seek truth but to mitigate risk."

**Structure of a good assumption test** (the simulate-evaluate framework):
1. **Define the assumption** as a positive statement.
2. **Identify the moment to simulate**: the specific behavioral context where the assumption would be confirmed or denied.
3. **Design the simulation**: small, fast — prototype, mockup, one-question survey, data query, or smoke-screen test. Simulate an experience; observe real behavior, not stated intent.
4. **Define success criteria upfront** (before seeing results), with specific numbers: "At least N out of M participants will exhibit behavior X." Vague criteria invite confirmation bias.
5. **Run the test** (target: completable in a day or two for the first iteration).
6. **Evaluate**: did the observed behavior meet the pre-defined criteria?
   - If **yes** → assumption is "more known" (moved left on map); if it is still the riskiest assumption, design a larger follow-on test; otherwise move to the next riskiest assumption.
   - If **no** → assumption is "refuted" (or more precisely: evidence against it); options are: redesign the solution to remove dependence on this assumption; abandon the solution if the assumption is foundational; or run a better-designed test if the team suspects a false negative.
7. **Iterate**: assumption tests grow in scale incrementally only as each prior test gives a positive early signal. Stop testing when remaining risk is low enough to build, or when the cost of the next test exceeds the cost of building.

Key principle: teams test **a set of 3 solutions in parallel**, not one idea at a time. This guards against confirmation bias and allows genuine compare-and-contrast.

---

## 5. Quotable passages (with PDF page numbers)

The following quotes are from the PDF; page numbers refer to the PDF file, which begins pagination at the book's first content page. Approximate locations given where exact page is uncertain.

**Q1 — What continuous discovery is** (PDF pp. 6–25, Ch. 1 definition):
> "At a minimum, weekly touchpoints with customers / By the team building the product / Where they conduct small research activities / In pursuit of a desired outcome."

**Q2 — Opportunities defined** (PDF pp. 26–45, Ch. 2):
> "Opportunities represent our customers' needs, pain points, and desires. They represent opportunities to intervene in our customers' lives in a positive way."

**Q3 — Opinion vs. evidence: behavior over stated intent** (PDF pp. 26–45, Ch. 2, on story-based interviewing):
> "We are going to ask our customers to share a specific story about their past behavior. We want to understand how they actually behaved in context, not what they think they would do in an ideal world."

**Q4 — Why batch synthesis fails** (PDF pp. 75–94, Ch. 5):
> "We need to synthesize as we go... [not in batch]. The more time that passes between conducting an interview and synthesizing it, the harder it becomes to recall the nuances of the conversation."

**Q5 — The 3-filter test for placing an opportunity on the OST** (PDF pp. 75–94, Ch. 6):
> "Before adding an opportunity to your opportunity solution tree, ask: Is this framed as a customer need, pain point, or desire — not as a solution? Have I heard about this in more than one interview, or is it unique to this customer? If we address this opportunity, will it help us drive our desired outcome?"

**Q6 — Why opportunities need a tree, not a backlog** (PDF pp. 75–94, Ch. 6):
> "An opportunity backlog asks us to make a prioritization decision before we have done the discovery work to know which opportunities are worth pursuing. An opportunity solution tree makes this discovery work visible."

**Q7 — Target opportunity selection is reversible** (PDF pp. 95–114, Ch. 7):
> "Choosing a target opportunity is a two-way door. You are not committing to solving this opportunity. You are simply committing to exploring it further. If you don't like what you find, you can always course-correct."

**Q8 — Why assumption testing beats idea testing** (PDF pp. 115–134, Ch. 9):
> "This pace is possible only when we step away from the concept of testing ideas and instead focus on testing the assumptions that need to be true in order for our ideas to succeed. By explicitly enumerating our assumptions, we can start to look for both confirming and disconfirming evidence to either support or refute each assumption."

**Q9 — What makes evidence real: behavior, not opinion** (PDF pp. 135–154, Ch. 10):
> "A strong assumption test simulates an experience, giving your participant the opportunity to behave either in accordance with your assumption or not. This behavior is what allows us to evaluate our assumption."

**Q10 — Pre-defining success criteria guards against confirmation bias** (PDF pp. 135–154, Ch. 10):
> "If we don't define our success criteria upfront, when we try to interpret the results, our brains will actively look for evidence that supports the assumption, and we'll likely miss the evidence that could refute it. To avoid this, we want to define what success looks like upfront (before we see the results)."

**Q11 — Goal is risk mitigation, not truth** (PDF pp. 135–154, Ch. 10):
> "We are not validating or invalidating anything. It's important that we recognize that our research findings are not truths — they are merely confirming or disconfirming evidence that either supports or refutes our point of view. Our goal as a product team is not to seek truth but to mitigate risk."

**Q12 — Discovery never ends** (PDF pp. 135–154, Ch. 11):
> "You are never done with discovery. Remember, this book is about *continuous* discovery. There is always more to learn and to discover."

---

## 6. What a simple "opinion → sourced → proven → done" model misses

Torres's workflow has several state transitions and loops that a linear model cannot represent:

### 6a. The reframe loop (within opportunities)
An opportunity captured as a feeling ("I feel overwhelmed") must be reframed to its root cause before it is valid for the OST. This is not just a data-entry step — it requires follow-up inquiry. The opportunity goes through a reframe before being placed on the tree. A simple model has no "reframe" state.

### 6b. The tree restructuring loop (within the OST)
As new interviews arrive (weekly), parent-child relationships between opportunities are revised. An opportunity may get a new parent, be split into two siblings, or be merged. The tree is a living structure. A linear model implies that once an insight is "sourced," it stays put. Torres's model requires the tree to be continuously reshaped.

### 6c. The two-way door reversal (target-opportunity to assessed)
Selecting a target opportunity is explicitly reversible ("two-way door"). If early solution testing reveals the opportunity was misframed or not worth addressing, the team returns to the assessment phase and selects a different sibling. This is a backwards state transition the simple model has no provision for.

### 6d. The solution-failure → opportunity-revision loop
When a solution fails in assumption testing, teams may discover their understanding of the opportunity was wrong — not just their solution. Torres writes (Ch. 2 and reinforced throughout) that the problem space and solution space co-evolve. A failed solution may trigger reframing of the parent opportunity. This is a jump backwards across the entire tree structure.

### 6e. The parallel-testing of three solutions
The simple model implies one thread of work. Torres's model explicitly requires keeping 3 solutions alive simultaneously during assumption testing, comparing their results against each other to find the "clear front runner." The state machine must branch (3 solution nodes in parallel under one targeted opportunity).

### 6f. The assumption-accumulation loop (not a single test)
An assumption is not tested once and then done. Evidence accumulates across multiple test iterations, each growing in scale. An assumption moves from right to left on the importance-evidence map incrementally. It is never "proven" — only "sufficiently known." A binary "sourced → proven" transition erases this gradient.

### 6g. The continuous interviewing flywheel
New opportunities enter the OST every week from new interviews, even while solutions are under active assumption testing. Discovery never pauses for delivery. This means the OST is always growing, and new opportunities may overtake the current target opportunity in priority, triggering a reset to the assessment phase.

---

## Summary for prodc modeling

The cleanest encoding maps to these principal entities and their states:

- **Opportunity**: `heard` → `filtered-out` | `on-tree` → `reframed`? → `assessed` → `targeted` | `deprioritized` → `addressed`
- **Solution** (child of Opportunity): `brainstormed` → `shortlisted` → `story-mapped` → `assumptions-enumerated` → `under-test` → `failed-test` | `clear-front-runner` → `shipped`
- **Assumption** (child of Solution): `implicit` → `articulated` → `mapped` → `leap-of-faith` → `being-tested` → `evidence-gathered` → `sufficiently-known` | `refuted`

Key loops to preserve in the model:
1. `refuted` assumption → solution redesigned (solution back to `story-mapped`) or abandoned (solution to `failed-test`)
2. `failed-test` solution + all 3 solutions failed → opportunity re-opened (back to `assessed`)
3. OST tree restructuring: any `on-tree` opportunity may change parent or be merged/split
4. Weekly interview → new `heard` opportunities enter at any time, including during active solution testing
