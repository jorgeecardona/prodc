---
title: issue update --field needs= writes a list with one empty string instead of clearing it
status: done
area: cli
owner: null
filed: 2026-11-12
fixed_in: 81048b3
scope: XS
verify: test
---

## Context

`prodc issue update <name> --field needs=` (empty value, meant to clear the list) wrote:

```yaml
needs:
  - ""
```

Seen on 12-11-2026 while unlinking three issues from dropped drafts (PD-13, PD-14, PD-18). The lines were removed by hand.

## Done when

`--field KEY=` with an empty value removes the key (or clears the list), and a test covers it. Also consider a clear flag for needs, like `--clear-blocked-by`.