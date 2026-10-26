# Spec: Auto-Sync Variant Retirement

Status: Shipped
Type: Feature

## Summary

Upstream drops accelerator variants over time: SGLang publishes no 910b image at 0.5.22, while
the A3 image advances. Auto-sync must be able to retire such a variant itself: remove its matrix
rules, keep its published support records and catalog entries, and stop chasing it in discovery.
Today each layer contradicts that move, so the pipeline dead-ends and burns a research run every
cycle (observed in run 40196991015).

## Motivation

Run 40196991015 proposed moving cann/sglang A3 to 0.5.22 (CANN 9.1.0 base) while holding 910b at
0.5.20. Trusted validation rejected the only group: `changed matrix combination lacks
compatibility evidence`. Three layer mismatches produced the dead-end:

1. **Hold is unvalidatable on a shared recipe.** The proposal had to edit
   `pack/cann/Dockerfile.sglang` (a hardcoded `cann-9.0.0` path) for the A3 bump.
   `_changed_configurations` in `tools/auto_sync/checks.py` then marks every surviving
   cann/sglang combination as changed, including the held 910b one, and requires compatibility
   rows for each. A held variant has nothing new to evidence, so no valid row set exists.
2. **The instructed move is forbidden.** The rotation rule in `proposal.md`, the
   runner-release-sync skill, and `docs/release-automation.md` says to "remove the matrix rules
   and support rows" for a dropped variant. But `_check_support` makes published support rows
   immutable, and the 910b record is published. Following the instruction guarantees rejection.
3. **Discovery chases retired variants forever.** `discover()` derives the variant universe from
   pooled catalog and support records. A retired variant keeps its published records (the images
   remain usable), so it stays in the universe with a permanent `needs_update` it can never
   satisfy. The existing "dropped variant is not chased" behavior only covers variants whose
   records are gone entirely (the cu129 case, where the record was still `prepared`).

### Goals

- A proposal can retire a variant inside the advancing group: remove its matrix rules with a
  comment citing the upstream scoping and the re-add condition, keep published support rows and
  catalog entries, drop only its `prepared` support rows.
- Validation accepts exactly that shape and keeps rejecting everything it rejects today;
  the changed-combination gate names the offending combinations and points at retirement.
- Discovery stops chasing a variant that has records but no matrix rule; a ready group may still
  add such a variant back when upstream support returns (`_bind_discovery` already permits this).
- The rotation rule text is identical in meaning across `proposal.md`, the skill, and the release
  guide, and matches what validation enforces.

### Non-Goals

- No catalog deprecation (`deprecated: true`) of retired variants' entries. Published images
  remain selectable; deprecation is a separate Pack-side decision (`pack/discard_runner.sh`).
- No new support-record status. A published row stays published after its variant retires.
- No pure-retirement proposal shape (a group without advancing rows). Nothing breaks while a
  retired variant's last base image still builds; retirement rides the next advance.
- No workflow YAML changes: the gates and prompts are the mechanism.
- The cann/vllm `blocked` outcome in run 40196991015 (no sourced Ascend plugin pair) is
  unrelated and unchanged.

## Proposal

### Discovery (`tools/auto_sync/discovery.py`)

Add a `_matrix_variants(repo)` reader: parse `pack/matrix.yaml` from the frozen default checkout
with a lazy `yaml` import (same pattern as `prerelease_packages`; Pack's `--no-dev` promote path
never calls `discover`). Return a map of `(backend, service)` to the set of declared variants
(`CANN_ARCHS` for cann, canonicalized; `""` otherwise). A missing, malformed, or escaping matrix
raises `DiscoveryError`, so detection fails visibly exactly like the catalog and support sources.

In `discover()`, filter the per-subscription variant universe:

```python
current = sorted({record["variant"] for record in represented})
result["variants"] = [
    _match(result, variant, sources)
    for variant in (current or list(variants))
    if variant in declared.get((backend, service), set())
]
```

A subscription with no matrix rules gets an empty universe and reports `unchanged`, which is the
quiet state for a fully retired subscription. The add-back path needs no change: `_bind_discovery`
in `run.py` already lets a ready group introduce a variant outside the universe, and the
retirement comment in the matrix carries the re-add condition for future evaluation.

### Validation (`tools/auto_sync/checks.py`)

No gate semantics change. `_changed_configurations` gains a precise error: name the offending
combinations and state that a variant which cannot follow a touched shared recipe must be retired
(matrix rule removal) rather than held without evidence. The retirement shape already passes every
gate today; the tests below pin that.

### Contract surfaces (prompts, skill, guide)

Rewrite the rotation rule once and keep it consistent across
`tools/auto_sync/prompts/proposal.md`, `.agents/skills/runner-release-sync/SKILL.md`, and
`docs/release-automation.md`:

- Retire inside the advancing group: remove the variant's matrix rules, leaving a comment with
  the upstream scoping and the re-add condition.
- Keep published support rows and catalog entries; published images remain usable. Drop only the
  variant's `prepared` support rows.
- Never hold a trailing variant on a recipe the group changes; a touched shared recipe requires
  evidence for every surviving combination, so a variant that cannot follow must retire.
- Add a retired variant back when support returns.

`analysis.md` gains one bullet: record the selected line's per-variant artifact availability
(registry listings) in findings, naming any universe variant with no artifact for the selected
line, so the proposal stage has the scoping evidence retirement cites.

`docs/support-records.md` header gains one line: retiring a matrix variant does not change or
remove its published rows.

`docs/release-automation.md` updates the discovery variant-universe line in
`Discovery and release policy`, updates the rotation rule in `Compatibility research`, and notes in
`Proposal output` that retiring a variant removes its matrix rules and drops only its `prepared`
support rows while keeping `published` support rows and catalog entries untouched.

The rule stays plain prose: no REQUIRED/NEVER contract keyword, so
`test_contract_keywords_sync_across_surfaces` keeps its count of 13. The phrase
"Rotate variants with evidence" stays in `proposal.md` for `test_policy_sentences_reach_stage_prompts`.

### User Stories

#### Story 1

As the auto-sync operator, I want a run to retire an upstream-dropped variant in the same PR that
advances the survivors, so that one cycle finishes instead of dead-ending on validation.

#### Story 2

As a maintainer, I want published 910b images to stay selectable after the variant retires, so
that existing 910b deployments keep working at their last supported version.

#### Story 3

As a reviewer, I want the rotation rule to read the same in the prompt, the skill, and the guide,
and to match what validation enforces, so that no surface instructs an impossible move.

### Core Features & Acceptance Criteria

1. **Matrix-aware universe.** Discovery reads `pack/matrix.yaml` from the frozen default checkout
   and intersects the records-derived variant universe with the declared variants. Acceptance:
   a unit test with published a3+910b records and an a3-only matrix chases only a3; the existing
   `test_dropped_variant_is_not_chased` and the real-repo `test_current_catalog_and_support_are_valid`
   stay green; a malformed matrix fails every subscription visibly.
2. **Retirement validates.** A group that removes the 910b matrix rule, keeps both published
   support rows, adds the A3 prepared row, and edits the shared recipe passes
   `validate_candidate` as `ready`. Acceptance: new positive test in `test_checks.py`.
3. **Rejection shape kept.** The same proposal holding 910b (rule kept) still fails, now with an
   error naming the rowless changed combinations; removing the published 910b support row still
   fails as removed accepted metadata. Acceptance: two negative tests in `test_checks.py`.
4. **Contract surfaces consistent.** The rotation rule reads identically in meaning across the
   three surfaces; `test_policy_sentences_reach_stage_prompts` and
   `test_contract_keywords_sync_across_surfaces` stay green without keyword-count changes.
5. **Suite green.** `uv run pytest tests/auto_sync` passes with the pinned tools, and
   `uv run mkdocs build --strict` passes for the docs edits.

### Notes / Constraints / Caveats

- Python 3.10+, typed data, small functions; automation stays in `tools/auto_sync/`.
- The lazy `yaml` import pattern from `prerelease_packages` keeps Pack's `promote` path free of
  the PyYAML dependency.
- Discovery's matrix read is advisory: it only shapes the chasing universe. Validation re-parses
  the matrix exactly (`yq`) and remains the only gate.
- Test fixtures build the matrix as emitted JSON (valid YAML), so no new test-time dependency.
- The retirement comment convention follows the cu129 precedent (#338/#339): state the upstream
  scoping, the re-add condition, and the verification command when one exists.
- Research prompts never mention a specific variant retirement; the rule text stays general.

### Boundaries

- **Always:** read the matrix from the frozen default checkout; keep published support rows
  immutable; keep the rotation rule consistent across the three surfaces.
- **Ask first:** catalog deprecation of retired variants; a new support-record status;
  workflow YAML changes.
- **Never:** let discovery's matrix read change validation semantics; mark a published row
  removed or unpublished from the proposal path; add a contract keyword for this feature.

### Risks and Mitigations

- A matrix rule removed by mistake silently de-chases the variant → matrix changes are
  human-reviewed, and the retirement comment makes intent explicit.
- The model still chooses to hold a variant → the rewritten rule forbids it, the validation error
  names the exact blocking combinations, and the repair loop gets a concrete pointer.
- Universe filtering hides a variant whose support returns → add-back stays possible through
  `_bind_discovery`, and the matrix comment carries the re-add condition.
- Fixture repositories with incomplete `pack/matrix.yaml` stop chasing omitted subscriptions →
  `test_discovery.py`'s `repository()` helper and `test_e2e.py`'s `scenario` fixture declare the
  subscribed combinations in `pack/matrix.yaml`.

## Design Details

### Commands

```sh
uv run pytest tests/auto_sync/test_discovery.py tests/auto_sync/test_checks.py -q
AUTO_SYNC_TOOL_BIN=/tmp/auto-sync-tools/bin uv run pytest tests/auto_sync -q
uv run pre-commit run --files <changed-files> --show-diff-on-failure
uv run mkdocs build --strict
```

Local environment; no remote build or GPU required. If `/tmp/auto-sync-tools/bin` is absent, run
`bash tools/auto_sync/bootstrap.sh --prefix /tmp/auto-sync-tools` first. Pack runs are out of scope.

### Project Structure

- `tools/auto_sync/discovery.py` — `_matrix_variants(repo)` parses `pack/matrix.yaml` from the
  frozen default checkout with a lazy `yaml` import and returns a `(backend, service) -> set[str]`
  map of canonicalized variants; `discover()` intersects `(current or list(variants))` with the
  declared set for `(backend, service)`.
- `tools/auto_sync/checks.py` — `_changed_configurations` names every changed matrix combination
  that lacks a compatibility row and instructs retiring a variant that cannot follow a touched
  shared recipe by removing its matrix rules.
- `tools/auto_sync/prompts/proposal.md`, `.agents/skills/runner-release-sync/SKILL.md`,
  `docs/release-automation.md` — unified rotation rule text; `proposal.md` keeps the phrase
  `Rotate variants with evidence` and adds no `REQUIRED:`/`NEVER:` keyword.
- `tools/auto_sync/prompts/analysis.md` — one bullet instructing the analysis stage to record
  per-variant registry artifact availability for the selected line in `findings`.
- `docs/support-records.md` — one header line stating that retiring a matrix variant does not
  change or remove its published rows.
- `tests/auto_sync/test_discovery.py` — `repository()` helper writes a default `pack/matrix.yaml`
  covering `SUBSCRIPTIONS` (overridable via `matrix=`); new tests cover retired-variant exclusion,
  empty-matrix `unchanged` status, and missing/malformed/escaping `pack/matrix.yaml` failures.
- `tests/auto_sync/test_checks.py` — positive test for retiring `910b` while advancing `a3` on a
  shared `cann/sglang` recipe; two negative tests for holding `910b` on the touched shared recipe
  (asserting the error names the `910b` combination and mentions retirement) and for removing the
  published `910b` support row.
- `tests/auto_sync/test_e2e.py` — `scenario` fixture declares all six subscribed combinations in
  `pack/matrix.yaml` (keeping the `cuda/vllm` rule at the end so `ready.json`'s diff applies) with
  minimal stub recipes for the five non-`cuda/vllm` subscriptions.

### Code Style

```python
def _matrix_variants(repo: Path) -> dict[tuple[str, str], set[str]]:
    """Declared canonical variants per (backend, service) in pack/matrix.yaml."""
    path = Path(repo) / "pack" / "matrix.yaml"
    if not path.resolve().is_relative_to(Path(repo).resolve()):
        msg = "matrix escapes the frozen checkout"
        raise DiscoveryError(msg)
```

Follow `prerelease_packages`: check path containment, raise `DiscoveryError` on missing or malformed
YAML, import `yaml` lazily inside the function, and canonicalize variants with `canonical_variant`.

### Implementation Plan

- [x] **T1 · Matrix-aware discovery universe and unit tests**
      Blocked by: None
      Owns: `tools/auto_sync/discovery.py`, `tests/auto_sync/test_discovery.py`,
      `tests/auto_sync/test_e2e.py`
      Gate: review
      Acceptance: `_matrix_variants(repo)` reads `pack/matrix.yaml` from the frozen checkout using
      lazy `yaml.safe_load`, validates the `rules` structure and arguments, canonicalizes variants
      (`CANN_ARCHS` for `cann`, `""` otherwise), and raises `DiscoveryError` on missing, escaping,
      or malformed files. `discover()` filters `(current or list(variants))` by the declared set for
      `(backend, service)`. `test_discovery.py` covers retired-variant exclusion (`a3` + `910b`
      published records with an `a3`-only matrix chases only `a3`), empty-matrix `unchanged` status,
      and missing/malformed/escaping matrix failure cases while keeping all existing discovery and
      e2e tests green.
      Verify: `uv run pytest tests/auto_sync/test_discovery.py -q`

- [x] **T2 · Changed-configuration error message and retirement validation tests**
      Blocked by: None
      Owns: `tools/auto_sync/checks.py`, `tests/auto_sync/test_checks.py`
      Gate: review
      Acceptance: `_changed_configurations` keeps its exact gate condition (`changed <= {_row_key(row) for row in rows}`)
      and includes the offending `(backend, service, variant, runtime, platform)` combinations and
      retirement guidance in the `ProposalError` message while retaining the
      `changed matrix combination lacks compatibility evidence` prefix. `test_checks.py` adds a
      positive test where retiring `910b` from `pack/matrix.yaml`, keeping published `a3` and `910b`
      support rows, adding the `prepared` `a3` row, and editing `pack/cann/Dockerfile.sglang`
      validates as `ready`, plus two negative tests (holding `910b` fails naming `910b` and
      retirement; deleting the published `910b` support row fails as removed accepted metadata).
      Verify: `uv run pytest tests/auto_sync/test_checks.py -q`

- [x] **T3 · Prompt, skill, and documentation alignment**
      Blocked by: T1, T2
      Owns: `tools/auto_sync/prompts/proposal.md`, `tools/auto_sync/prompts/analysis.md`,
      `.agents/skills/runner-release-sync/SKILL.md`, `docs/release-automation.md`,
      `docs/support-records.md`
      Gate: review
      Acceptance: `proposal.md`, `SKILL.md`, and `docs/release-automation.md` carry the unified
      variant-retirement rule; `proposal.md` preserves `Rotate variants with evidence`; `analysis.md`
      gains the per-variant registry artifact availability bullet; `docs/support-records.md` gains
      the header line on published rows surviving variant retirement; no `REQUIRED:`/`NEVER:`
      contract keyword or `$` template identifier is added; `mkdocs build --strict` and the prompt
      contract tests pass.
      Verify: `AUTO_SYNC_TOOL_BIN=/tmp/auto-sync-tools/bin uv run pytest tests/auto_sync -q` and `uv run mkdocs build --strict`

### Test Plan

[x] I/we understand the owners of the involved components may require updates to existing tests to make this
code solid enough prior to committing the changes necessary to implement this enhancement.

#### Prerequisite testing updates

Update `tests/auto_sync/test_discovery.py`'s `repository()` helper and
`tests/auto_sync/test_e2e.py`'s `scenario` fixture to write `pack/matrix.yaml` rules for the
subscribed combinations so existing discovery and e2e tests run against a complete matrix.

#### Unit tests

- `tools/auto_sync/discovery.py`: `2026-10-26` - `100%` of `_matrix_variants` and universe-filtering
  branches (`tests/auto_sync/test_discovery.py`: retired variant excluded from universe, fully
  retired subscription reports `unchanged`, missing/malformed/symlink-escaping `pack/matrix.yaml`
  returns `failed` for all subscriptions).
- `tools/auto_sync/checks.py`: `2026-10-26` - `100%` of `_changed_configurations` error reporting
  and retirement validation (`tests/auto_sync/test_checks.py`: positive retirement group passes as
  `ready`; held variant on touched shared recipe fails naming the held combination; removed
  published support row fails).

#### Integration tests

- `tests/auto_sync/test_e2e.py::test_policy_sentences_reach_stage_prompts` and
  `tests/auto_sync/test_e2e.py::test_contract_keywords_sync_across_surfaces` verify prompt, skill,
  and guide synchronization.
- Full `tests/auto_sync` suite exercises `prepare`, `research`, `validate`, and `publish` against
  the matrix-aware discovery universe.

#### e2e tests

No live model or GitHub workflow e2e in CI; offline `tests/auto_sync/test_e2e.py` covers the
end-to-end controller pipeline with local Git, HTTP, registry, and pinned Qwen CLI fixtures, and
`uv run mkdocs build --strict` verifies documentation rendering.
