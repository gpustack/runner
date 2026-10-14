# Spec: Dependency Variant Patterns

Status: Proposed
Type: Feature

## Summary

`pack/dependencies.json` maps each catalog key to a closed enumeration of distribution aliases.
Variant families (`mooncake-transfer-engine-npu`, `-rocm`, `-cuda13`, and eventually `-cuda14`)
force one manual edit per family member. This spec lets an alias be a prefix pattern (a NAME_RE
stem plus one trailing `*`), so `mooncake-transfer-engine` folds with two aliases — the bare
literal and `mooncake-transfer-engine-*` — and any current or future variant records without
mapping edits.

The mapping stays a positive selector: it declares what to record, and records it when matched. It
does not police image contents. What changes is the *claimed meaning* of an unrecorded key. Today
the docs and AGENTS.md state that a missing map key means the package was absent; with alias
management that claim is false — the package may be installed under a name the mapping does not
cover. The semantics are corrected to "the mapping recorded nothing", which is what the data can
truthfully say.

## Motivation

### Goals

- An alias is a NAME_RE literal or a NAME_RE stem plus one trailing `*` (prefix pattern over
  PEP 503 normalized names). `mooncake-transfer-engine` becomes
  `["mooncake-transfer-engine", "mooncake-transfer-engine-*"]`; the bare literal stays because a
  pattern stem ends with `-` and never matches the bare name itself.
- Fold keeps order priority and stays truthful: a pattern with two installed family members is an
  ambiguity error, because the mutual-exclusion premise is broken and recording either would be
  arbitrary.
- Static validation rejects cross-key overlap a pattern introduces, so a pattern cannot steal a
  distribution another key records. The same check is what makes a stem wildcard safe per key:
  `mooncake-transfer-engine-*` passes because no other key owns a distribution under that prefix,
  while a hypothetical `vllm-*` is rejected by the `vllm-ascend` literals.
- Documentation and AGENTS.md stop claiming "missing key means absent"; they state "the mapping
  recorded nothing for that key" (absent, or installed under an unmapped name).
- Catalog keys, the folded output shape, receipt `distributions` (concrete installed names), the
  digest binding, the receipt schema, and the `list_runners(dependencies=...)` behavior are
  unchanged.

### Non-Goals

- No interception of unmapped variants: no probe-side near-miss reporting, no gate in
  `validate`/`publish`/`catalog`, no `ignored` list, no schema version bump. An installed
  distribution the mapping does not cover is simply not recorded; that is the selector's purpose,
  not a defect.
- No regex or multi-glob syntax; a pattern is exactly one NAME_RE stem plus a trailing `*`.
- No version-aware or context-aware matching (the probe does not learn the image's CUDA version).
- No change to `pack/shared/probe_dependencies.sh`; it serves historical post-operations only.
- No retroactive re-collection of already-published entries; new receipts use the new matching.
- No library code change; query behavior is untouched — only its documented interpretation.

## Proposal

### User Stories

#### Story 1

As a maintainer adding a recipe for a new accelerator or toolkit major (CUDA 14, a TPU backend),
I want the existing `mooncake-transfer-engine-*` pattern to cover the new variant distribution,
so that the catalog records the package without a mapping PR.

#### Story 2

As a reviewer of mapping PRs, I want patterns statically validated, so that a pattern cannot steal
distributions from another key or fold two co-installed family members into an arbitrary winner.

#### Story 3

As a consumer of the catalog, I want the docs to say exactly what a missing key means, so that I
never read "not installed" from what is only "not recorded".

### Core Features & Acceptance Criteria

1. **Pattern aliases in the v1 shape.** The file stays a flat `{key: [aliases]}` object. An alias
   is a NAME_RE literal or a NAME_RE stem plus one trailing `*`. `validate_mapping` accepts the
   extended syntax and rejects malformed patterns (`*` mid-name, double `*`, empty stem) and any
   cross-key overlap: a literal under one key may not start with another key's pattern stem, and
   two keys' pattern stems may not be prefix-related. Same-key overlaps are allowed and resolved
   by alias order. Acceptance: validation tests cover valid patterns, each malformed form,
   literal-vs-pattern and pattern-vs-pattern cross-key overlap, and same-key shadowing.
2. **Probe matching.** `probe_dependencies.py` treats an installed normalized name as wanted when
   it equals a literal or starts with a pattern stem. The conflicting-versions rule is unchanged,
   with "mapped" now meaning literal-or-pattern. Receipt `distributions` keep concrete installed
   names; the receipt schema gains no fields. Acceptance: probe tests cover a pattern hit, a
   literal hit, a non-matching lookalike (`torchvision` vs stem `torch`) excluded, and a
   conflicting pattern-matched duplicate failing.
3. **Fold semantics.** Alias order decides. A literal matches its exact name. A pattern matches
   when exactly one installed distribution starts with its stem; zero matches passes to the next
   candidate; two or more raise an ambiguity error. `validate_distributions` accepts a collected
   name when it equals a literal or starts with a pattern stem. Acceptance: fold tests cover
   unique pattern match, literal-before-pattern priority, zero-match fall-through, and the
   ambiguity error for two installed family members.
4. **Migration.** `mooncake-transfer-engine` becomes
   `["mooncake-transfer-engine", "mooncake-transfer-engine-*"]`, replacing the `-npu`, `-rocm`
   and `-cuda13` literals. Acceptance: `tests/pack/test_dependencies.py` self-consistency tests
   pass on the migrated file, and fixture receipts carrying `mooncake-transfer-engine-npu`,
   `-rocm` or `-cuda13` fold to the same catalog entries as before.
5. **Semantic correction.** `docs/dependency-metadata.md` rewrites the unknown-versus-empty table
   row and the querying notes that say "not installed": a map without the queried key means the
   mapping recorded nothing — the package is absent or installed under an unmapped name. The
   "One name, several distributions" section documents pattern syntax, the stem-wildcard form and
   its per-key premise (every distribution under the prefix is a build variant of one package),
   the ambiguity error, and keeps the mutual-exclusion and comparable-version grouping conditions
   as the bar for adding any pattern. The AGENTS.md line "A missing map key means that package was
   absent" is corrected to the same semantics. `docs/packaging.md` step 4 mentions patterns.
   Acceptance: `uv run mkdocs build --strict` green; the three-statement block in AGENTS.md stays
   internally consistent.

### Notes / Constraints / Caveats

- The grouping conditions stay authoritative: a pattern may fold only distributions that are
  mutually exclusive and share a versioning scheme. A stem wildcard additionally asserts that
  *everything under the prefix* is a build variant of one package — true for
  `mooncake-transfer-engine`, false for the `vllm`, `sglang` or `lmcache` prefixes, which mix in
  distinct packages. Patterns change syntax, not policy; the wildcard is a per-key judgment, never
  a default.
- The ambiguity error protects data that *is* recorded; it is not a check on unrecorded packages.
  Nothing in this design inspects, enumerates, or fails on distributions the mapping does not
  cover.
- Residual risk of a stem wildcard: an upstream could one day publish a different-purpose
  distribution under the prefix. The images are curated by our own recipes, so such a package
  would only appear by deliberate installation; if it ever co-installs with the real variant, the
  ambiguity error fires. Version-scheme comparability cannot be checked mechanically under any
  alias form and remains a review-time concern.
- Rejected alternatives: interception of unmapped variants with an `ignored` escape list (turns
  the whitelist into image-content policy and forces enumeration of exceptions — the failure mode
  this spec exists to avoid); per-family patterns only (`-cuda*`, `-npu`, …) as the sole form
  (keeps a human checkpoint per family, but for a prefix that contains only build variants the
  checkpoint buys nothing the ambiguity error does not); implicit key-prefix matching with no
  syntax (the file stops being self-describing); full regex aliases (no static overlap checking);
  PyPI-based family discovery (non-hermetic).

### Boundaries

- **Always:** keep catalog keys literal; keep receipt `distributions` concrete; validate pattern
  overlap statically; fail the fold on ambiguity; adopt a stem wildcard only where the prefix
  holds build variants of one package.
- **Ask first:** extending pattern syntax beyond one trailing `*`; a stem wildcard for another
  key; per-backend conditional mappings; any change to folded-output keys, receipt schema, or
  query behavior.
- **Never:** match versions or image build args in the probe; report, flag, or fail on
  distributions the mapping does not cover; ship the mapping file with the library.

### Risks and Mitigations

- Prefix over-match captures an unintended distribution → static cross-key overlap rejection plus
  the fold-time ambiguity error; images are curated by our own recipes.
- A key adopts a wildcard its prefix does not deserve → the boundary above plus static overlap
  rejection (the `vllm-*` case fails validation outright); doc states the per-key premise.
- A reader of old docs keeps the "missing means absent" mental model → docs, AGENTS.md, and the
  querying notes are corrected in the same change.

## Design Details

### Commands

```sh
uv run pytest tests/pack -q
uv run pre-commit run --files <changed-files> --show-diff-on-failure
uv run mkdocs build --strict
```

### Project Structure

- `pack/dependencies.json` — `mooncake-transfer-engine` aliases become
  `["mooncake-transfer-engine", "mooncake-transfer-engine-*"]`.
- `pack/collect_dependencies.py` — `validate_mapping` (pattern syntax, overlap checks),
  `validate_distributions` (literal-or-pattern membership), `fold_dependencies` (pattern
  semantics, ambiguity error).
- `pack/probe_dependencies.py` — literal-or-pattern matching.
- `tests/pack/test_dependencies.py` — self-consistency extended to pattern stems (normalization,
  cross-key overlap).
- `tests/pack/test_collect_dependencies.py`, `tests/pack/test_probe_dependencies.py` — behavior
  tests above; `tests/pack/test_merge_runner.py` fixtures unchanged in shape (v1 file kept).
- `docs/dependency-metadata.md`, `docs/packaging.md`, `AGENTS.md` — semantic correction.

### Code Style

```python
def fold_dependencies(distributions: dict, mapping: dict) -> dict[str, str]:
    """First matching alias wins; a pattern requires exactly one installed match."""
```

Match the existing idiom: validation raises `ValueError` with stable message text, the probe keeps
raw versions verbatim, and JSON stays sorted on write.

### Implementation Plan

- [ ] **T1 · Pattern aliases: validation, probe matching, fold semantics**
      Blocked by: None
      Owns: `pack/dependencies.json`, `pack/collect_dependencies.py`,
      `pack/probe_dependencies.py`, `tests/pack/test_dependencies.py`,
      `tests/pack/test_collect_dependencies.py`, `tests/pack/test_probe_dependencies.py`
      Acceptance: criteria 1–4.
      Verify: `uv run pytest tests/pack -q`
- [ ] **T2 · Semantic correction in docs and AGENTS.md**
      Blocked by: None
      Owns: `docs/dependency-metadata.md`, `docs/packaging.md`, `AGENTS.md`
      Acceptance: criterion 5.
      Verify: `uv run mkdocs build --strict`

Checkpoint after both: full `tests/pack` + pre-commit on changed files + `mkdocs --strict`.

### Test Plan

[x] I/we understand the owners of the involved components may require updates to existing tests
to make this code solid enough prior to committing the changes necessary to implement this
enhancement.

#### Prerequisite testing updates

None. The v1 file shape is kept; existing fixtures load unchanged.

#### Unit tests

As enumerated per criterion above: mapping validation matrix, probe matching, fold matrix, and
the pattern-extended self-consistency tests.

#### Integration tests

The existing `tests/pack/test_collect_dependencies.py` real-metadata harness (venv fixtures,
container execution mocked) exercises the probe end to end; pattern cases ride it.

#### e2e tests

No new automated e2e. The next Pack invocation publishing a new `mooncake-transfer-engine-*`
variant is the real check: it must fold without a mapping edit.
