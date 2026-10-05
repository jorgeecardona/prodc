# Quickstart

Three files, one command.

## 1. `prodc.toml`

```toml
[prodc]
needs = ["needs/*.yaml"]

[proofs.web]
kind = "gherkin"
paths = ["features/*.feature"]
delivered = ["@implemented"]
pending = ["@pending"]
```

## 2. `needs/jordan.yaml`

```yaml
who: jordan
label: "design partner"
needs:
  - id: N-1
    text: "When an order is past due, jordan can see it highlighted"
    must: true
    sources:
      - kind: interview
        who: Jordan
        date: 2026-09-20
        quote: "I lose the past-due ones in the list"
    proofs:
      - "web:orders.feature#Past due orders are highlighted"

  - id: N-2
    text: "jordan can export the day's delivery run sheet"
    sources:
      - kind: artifact
        locator: issues.md#N-2
        date: 2026-09-21
    # no proofs → HOLE (evidenced, not yet proven)

  - id: N-3
    text: "implement a settings page"   # no sources → opinion
```

## 3. `features/orders.feature`

```gherkin
Feature: Orders board

  @implemented
  Scenario: Past due orders are highlighted
    Given an order whose due date has passed
    When I open the orders board
    Then the order is highlighted as past due
```

## 4. Run

```bash
prodc status
```

N-1 is DELIVERED (tagged scenario), N-2 is a HOLE, N-3 is an opinion. Exit 0; a BROKEN proof would exit 1.

The same project is checked in at `examples/quickstart/`.

Other proof kinds (`pytest`, `files`, `accept`, …) and every `prodc.toml` section: [Config](config.md).
