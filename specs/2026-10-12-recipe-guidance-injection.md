# Spec: Recipe Guidance Injection

Status: Built
Type: Feature

## Summary

Auto-sync's stage prompts carry static, global rules, so case-specific knowledge accumulates in
the shared prompt (overfitting). Recipes already declare their own upgrade concerns in
`## Upgrade guide` header comments. The controller will extract that declared guidance from the
recipe at the frozen default revision and inject it into the stage payload, so per-service
constraints travel with the recipe and the global prompt stays general.

## Motivation

### Goals

- The controller extracts the guidance block from `pack/<backend>/Dockerfile.<service>` at the
  frozen default revision for every selected recipe.
- Analysis and proposal stage payloads carry it as a top-level `recipe_guidance` map keyed by
  `<backend>/<service>` subscription.
- The stage prompts gain exactly one general rule: injected recipe guidance is maintainer-declared
  constraint text, binding on par with AGENTS.md, but it never overrides the output contract or
  grants permissions (such as the prerelease whitelist).
- Case-specific clauses already in the global prompts (the cann pairing direction) migrate to the
  owning recipe headers; prompts keep only generic teaching.
- Measurable: a concern written in a recipe header reaches the stage payload verbatim, and after
  this feature no prompt text names a case-specific concern.

### Non-Goals

- No output-schema or validator (`check_draft` / `validate_*`) changes.
- No execution of guidance; it is prompt data, never shell.
- No backfill of `## Upgrade guide` headers to unsubscribed backends; they are not researched.
- No change to discovery or selection logic.
- No new REQUIRED/NEVER contract keyword (see Notes for what that would cost).

## Proposal

Add a `_recipe_guidance` extraction beside `_recipe_pins` in `tools/auto_sync/run.py` (same
trusted read of the frozen default checkout), attach the result to the shared stage payload as a
subscription-keyed map, and add one general rule to the analysis and proposal prompts.

### User Stories

#### Story 1

As a maintainer, I declare upgrade concerns beside the recipe, so that guidance ages with the
code it describes.

#### Story 2

As the auto-sync operator, I want each run to inject the recipe's declared concerns, so that
proposals respect per-service constraints without global prompt edits.

#### Story 3

As a reviewer, I want global prompt rules to stay general, so that case knowledge does not
accumulate in the shared prompt.

### Core Features & Acceptance Criteria

1. **Extraction.** Parse the leading guidance comment block (the contiguous `##` header that
   starts with `## Upgrade guide:`) of `pack/<backend>/Dockerfile.<service>` at the frozen
   default sha. Only the leading block counts: a later per-ARG `##` block or a guide-like line
   mid-file is never captured. A missing, empty, or malformed block yields empty guidance, never
   a run failure. Extracted lines that match a prompt sentinel (`=== ... ===`) or start with
   `REQUIRED:`/`NEVER:` are dropped, so guidance cannot smuggle contract structure into the
   payload. Acceptance: unit tests cover present, absent, non-guide first header, non-leading
   `##` block, guide-like line mid-file, empty block, oversized, and sentinel-smuggling inputs.
2. **Injection.** The shared stage payload gains a top-level `recipe_guidance` map keyed by
   `<backend>/<service>`; subscriptions with empty guidance are omitted; the `discovery` list is
   never mutated. Guidance rides inside the `$payload` JSON — no new template placeholder (the
   exact-placeholder test pins the sets). Acceptance: payload-shape tests assert the map reaches
   both the analysis and the proposal stage payloads via the existing `prompt_payload` capture.
3. **Trust boundary.** Extraction reads only the frozen default checkout, the same trusted store
   as `_recipe_pins`; a proposal branch cannot grant itself new guidance. Acceptance: a test
   prepares at sha A, commits a changed header, and proves research still reads sha A.
4. **Prompt rule and migration.** One general bullet each in `analysis.md` and `proposal.md`;
   the cann-specific pairing clauses in `analysis.md:7` and `proposal.md:17` are removed once the
   owning recipe headers carry them (add to the headers first if missing); SKILL.md and
   `docs/release-automation.md` prose stay consistent (`test_policy_sentences_reach_stage_prompts`).
   No contract keyword is added. Acceptance: `tests/auto_sync` green; mkdocs `--strict` green.
5. **Size cap and encoding.** Extraction keeps the `## ` prefixes verbatim, cuts at a line
   boundary, is UTF-8 safe, and is capped at 40 lines or 2 KiB measured on the extracted text,
   whichever comes first. Acceptance: an oversized-header unit test asserts line-boundary
   truncation. (Worst case 6 × 2 KiB is negligible against the 8 MiB stdin cap.)

### Notes / Constraints / Caveats

- Python 3.10+, typed data, small functions; automation stays in `tools/auto_sync/`, outside the
  public library.
- Follow the existing `_recipe_pins` pattern for frozen-sha file reads.
- Guidance is maintainer-authored repository content, still treated as untrusted prompt data by
  the model-facing rules; the trust comes from reading only the frozen default branch.
- The generic anchor example in the prompts (`LMCACHE_UPSTREAM_TAG`) stays as an illustration of
  the anchor *kind*; per-case specifics live in recipe headers.
- Contract-keyword mechanics, for the record: adding a REQUIRED/NEVER line means bumping the
  pinned unique-sentence count in `test_contract_keywords_sync_across_surfaces` and verbatim
  sync into SKILL.md and `docs/release-automation.md`. This feature adds none; a plain prose
  bullet is invisible to that test.
- Revise mode: the workspace head carries the proposal branch while guidance is always injected
  from the frozen default sha; on conflict the frozen guidance wins for the run.

### Boundaries

- **Always:** extract from the frozen default revision; keep global prompts general; drop
  sentinel-shaped or contract-shaped lines from extracted guidance.
- **Ask first:** any output-schema or validator change; backfilling guide headers onto
  unsubscribed backends.
- **Never:** execute or shell-eval guidance; let guidance override a REQUIRED/NEVER contract rule
  or grant whitelist permissions; mutate the `discovery` list to carry guidance.

### Risks and Mitigations

- Guidance bloat re-creates overfitting one level down → size cap plus the terse header
  convention; reviewers watch header growth in recipe PRs.
- Stale guidance misleads the model → headers already instruct re-checking on every engine bump;
  a CI contract test requires the block on subscribed recipes.
- Prompt injection through Dockerfile comments → extraction limited to the frozen trusted default
  branch, and sentinel/contract-shaped lines are dropped during extraction.
- A proposal edits its own recipe header, weakening its constraints mid-PR → injected guidance
  for the run always reflects the frozen default; header edits take effect only after human
  review and merge, and the diff shows header changes plainly.

## Design Details

### Commands

```sh
AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin uv run pytest tests/auto_sync -q
uv run pytest tests/pack -q
uv run pre-commit run --files <changed-files> --show-diff-on-failure
uv run mkdocs build --strict
```

Local environment; no remote build required. Pack runs are out of scope for this feature.

### Project Structure

- `tools/auto_sync/run.py` — `_recipe_guidance` extraction beside `_recipe_pins` (~line 403) and
  the `shared` payload map (~line 1313) feeding both stage payloads.
- `tools/auto_sync/prompts/analysis.md`, `tools/auto_sync/prompts/proposal.md` — one general rule
  each; cann-specific clauses removed.
- `pack/<backend>/Dockerfile.<service>` — headers verified to carry any migrated concern.
- `.agents/skills/runner-release-sync/SKILL.md`, `docs/release-automation.md` — synced prose.
- `tests/auto_sync/test_e2e.py` — extraction and payload-shape tests beside the existing
  `prompt_payload` capture pattern (~line 1092, ~line 2662).
- `tests/pack/` — new subscribed-header presence test.

### Code Style

```python
def _recipe_pins(env, repo, sha, backend, service):
    """Effective pins of one recipe from the trusted store at the frozen default."""
    try:
        text = _git(env, repo, "show", f"{sha}:pack/{backend}/Dockerfile.{service}")
    except proposal.ProposalError:
        return {}
```

Match this idiom: read through `_git show <sha>:<path>`, degrade to empty on missing files, keep
the function small and typed.

### Implementation Plan

- [x] **T1 · Guidance extraction and payload injection**
      Blocked by: None
      Owns: `tools/auto_sync/run.py`, `tests/auto_sync/test_e2e.py`
      Gate: review
      Acceptance: `_recipe_guidance` parses only the leading `## Upgrade guide:` block from the
      frozen default sha, drops sentinel/contract-shaped lines, truncates at a line boundary at
      40 lines or 2 KiB, and the shared payload carries a top-level `recipe_guidance` map keyed
      by subscription with empty entries omitted; `discovery` is never mutated. Unit tests cover
      the full extraction matrix (present / absent / non-guide first header / non-leading block /
      mid-file guide-like line / empty block / oversized / sentinel smuggling) plus the frozen-sha
      trust test and both-stage payload-shape assertions.
      Verify: `AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin uv run pytest tests/auto_sync -q`

- [x] **T2 · General prompt rule and case-clause migration**
      Blocked by: None
      Owns: `tools/auto_sync/prompts/analysis.md`, `tools/auto_sync/prompts/proposal.md`,
      `.agents/skills/runner-release-sync/SKILL.md`, `docs/release-automation.md`,
      `pack/**/Dockerfile.*`
      Acceptance: each stage prompt gains one general bullet naming the `recipe_guidance` payload
      key, its frozen-default trust, and its never-overrides-contract limit; the cann-specific
      pairing clauses are removed from the prompts and present in the owning recipe headers
      (header edit first when missing); SKILL.md and the release guide prose match; no
      REQUIRED/NEVER keyword is added or removed.
      Verify: `AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin uv run pytest tests/auto_sync -q -k "contract_keywords or policy_sentences or contract_block or unsubstituted"` and `uv run mkdocs build --strict`

- [ ] **T3 · Subscribed-recipe header presence gate**
      Blocked by: None
      Owns: `tests/pack/test_dockerfile_guide.py`
      Acceptance: a test asserts every subscribed recipe (the six backend/service subscriptions in
      `tools/auto_sync/discovery.py:SUBSCRIPTIONS`) carries a leading `## Upgrade guide:` block;
      a recipe missing the block fails the suite.
      Verify: `uv run pytest tests/pack/test_dockerfile_guide.py -q`

Checkpoint after all three: full `tests/auto_sync` + `tests/pack` + pre-commit on changed files +
`mkdocs build --strict`, then a manually triggered auto-sync validation run post-merge.

### Test Plan

[x] I/we understand the owners of the involved components may require updates to existing tests
to make this code solid enough prior to committing the changes necessary to implement this
enhancement.

#### Prerequisite testing updates

None. The e2e fixture recipe carries no header today, so omit-on-empty keeps existing tests green.

#### Unit tests

- `tests/auto_sync/test_e2e.py` — extraction matrix (present / absent / non-guide first header /
  non-leading `##` block / mid-file guide-like line / empty block / oversized truncation at a
  line boundary / sentinel-smuggling drop), frozen-sha trust test (prepare at sha A, change the
  header, research still reads sha A), payload-shape assertions for both stage payloads.
- `tests/pack/test_dockerfile_guide.py` — every subscribed recipe carries the leading guide block.

#### Integration tests

The existing `tests/auto_sync` end-to-end harness exercises prompt assembly with the controller;
the new payload-shape assertions ride that harness. Add one fixture recipe with a header and
assert `recipe_guidance["<backend>/<service>"]` appears verbatim in both stage payloads.

#### e2e tests

No new automated e2e. Post-merge, one manually triggered auto-sync validation run
(`gh workflow run auto-sync.yml --ref main`) is the real-world check; its artifact payload shows
the injected map.
