# Declared-only warning ignores a path proof

scope: XS
verify: test
area: status

## Context

#103 warns when a `must` need is DELIVERED on declared proofs only. The check reads
`need.proofs`. The proof of `need.path.proof` (#99) is resolved apart, into `path_state`,
and does not count.

## Decision needed

A must need with `proofs: ["accept:..."]` and a results-backed `path.proof` still warns.
Decide whether a passing path proof counts as a results-backed proof.

- Yes: fold `ProofResult.declared` of the path proof into `declared_only` in
  `Resolver._resolve_leaf`.
- No: say so in docs/config.md, so the warning is not read as a bug.

## Test

A must leaf with one declared proof and one results-backed path proof: warns or not,
whichever is decided.
