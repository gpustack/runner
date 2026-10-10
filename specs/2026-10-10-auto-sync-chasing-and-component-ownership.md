# Spec: Auto-Sync Chasing and Component Ownership

Status: Planned
Type: Feature

## Summary

Change auto-sync discovery from "jump to the newest upstream release" to "chase the next release line above the current catalog, one line per run".
Make the research stage own the full component set: adapt failing patches, update any `*_VERSION` / `*_COMMIT` recipe argument with evidence, rotate hardware variants as upstream support changes, and consult repository history before changing existing choices.
Add a maintainer-configured prerelease package whitelist and a `pack-run-url` dispatch input that feeds a failed Pack run back into research.

## Motivation

The inspected repository baseline is commit `69be1ec3f1fcdbf0b78ae1ee8e19d42279026ac2`.

Run [37982329518](https://github.com/gpustack/runner/actions/runs/37982329518) completed the whole research pipeline and blocked all six subscriptions:

- CUDA and ROCm vLLM 0.31.0: `vllm/001_wrong_dp_ray.patch` no longer applies (verified locally with `git apply --check`), and the adapt-versus-remove decision stalled the group.
- CUDA, ROCm, and CANN SGLang 0.5.21: the release requires LMCache unified MP connector modules that only the prerelease LMCache v0.5.6rc3 provides; the newest stable v0.5.5 lacks them (verified through the LMCache release contents).
- CANN SGLang: no Ascend 0.5.21 base image exists; `quay.io/ascend/sglang` stops at v0.5.20.
- CANN vLLM: the newest plugin is a prerelease and its release notes scope validation away from the 910B and 310P variants.

Blocking was fail-closed correct, but the run shows four structural gaps:

- Discovery jumps straight to the newest release. The catalog lags by more than one release line, so intermediate lines are skipped even when they are compatible and verifiable.
- A patch that fails to apply blocks the group instead of being adapted or deliberately removed.
- There is no sanctioned way to select a prerelease for packages whose upstream ships critical integration only in release candidates (LMCache, vllm-ascend, vllm-omni).
- Research cannot verify patches for components whose source trees are never supplied (vllm-omni, LMCache), and a failed Pack run produces no feedback into the next sync.

### Goals

- Chase upstream one release line at a time, choosing the highest patch or post release within the next line, ordered by PEP 440.
- Adapt failing patches by default; remove a patch only with cited evidence, as an explicit file deletion, and never block a group on a patch alone.
- Let maintainers name the packages that may select prerelease versions in a reviewed configuration file.
- Treat every `ARG *_VERSION` and `ARG *_COMMIT` in a selected recipe as owned by the proposal, including LMCache and vllm-omni pins, and supply the source trees needed to verify their patches.
- Drop matrix rules and support rows for variants upstream no longer supports, and add them back when support returns.
- Read `docs/support-records.md` and the git history of touched files before changing existing pins, patches, or variants.
- Accept a Pack workflow run URL on manual dispatch, extract the failure, and hand it to research as frozen context.

### Non-Goals

- Chase more than one release line per subscription per run.
- Permit prerelease engine releases in discover mode; the whitelist covers additional packages and the CANN plugin only.
- Re-run Pack or rebuild images from auto-sync; the failure URL is research input, not a rebuild trigger.
- Change the revise-mode command flow or the publication pipeline.
- Guarantee that a chase target is publishable; a blocked target stays blocked with its specific missing fact.

## Proposal

Auto-sync becomes an incremental chaser. Each run moves every subscription exactly one release line above its recorded position, with the full component set (engine, plugin, runtime, additional packages, patches, variants) treated as proposal-owned and evidence-bound. Maintainers steer through reviewed configuration (the prerelease whitelist) and can feed a failed Pack run back into the next sync for diagnosis.

### User Stories

#### Story 1

As a maintainer, I want auto-sync to chase upstream one release line at a time (highest patch or post release within that line, PEP 440 ordering), so that intermediate compatible versions are packaged instead of skipped.

#### Story 2

As a maintainer, I want the workflow to adapt patches that no longer apply and to delete a patch only with cited upstream evidence, so that runner features gated by patches are not lost silently.

#### Story 3

As a maintainer, I want a reviewed configuration file naming the packages that may select prerelease versions (LMCache, vllm-ascend, vllm-omni, and others I add), so that release candidates are usable exactly where upstream ships critical integration only as RCs.

#### Story 4

As a maintainer, I want auto-sync to own every `ARG *_VERSION` / `*_COMMIT` pin in a selected recipe, including LMCache, so that a forced component update is made with evidence instead of blocking the group.

#### Story 5

As a maintainer, I want hardware variants (for example CANN 310p/910b/a3/950) removed horizontally when upstream drops support and added back when support returns, so that the matrix tracks upstream support instead of drifting.

#### Story 6

As a maintainer, I want research to consult `docs/support-records.md` and the git history of touched files before changing existing choices, so that dispositions respect why earlier decisions were introduced.

#### Story 7

As a maintainer, I want to paste a Pack workflow run URL (possibly a failed run) into the manual dispatch inputs, so that the next sync sees the failure and knows how to handle it.

### Core Features & Acceptance Criteria

1. **Incremental chasing.** Given catalog vLLM 0.29.0 and upstream v0.30.0 + v0.31.0, discovery selects 0.30.0; given an additional v0.30.1, it selects 0.30.1; post releases outrank their base release within the line. A subscription with no records selects the newest eligible release. When nothing eligible exceeds the base, every variant reads `unchanged`. Discovery records carry `current_version` and `latest_version`.
2. **Patch duty.** A patch that fails `git apply --check` against the exact selected revision is adapted; removal requires cited upstream evidence and lands as an explicit file deletion in the group patch; a group never blocks on patch state alone.
3. **Prerelease whitelist.** `pack/prereleases.yaml` names canonical package keys allowed to select prereleases; the controller freezes the list from the default checkout; unknown keys are rejected; an absent file keeps the current stable-only policy; engine releases stay stable-only in discover mode.
4. **Component ownership.** Any recipe `ARG *_VERSION` / `*_COMMIT` may change with evidence; the controller supplies vllm-omni and LMCache source trees at the recipe pins; unresolvable pins are recorded in `source_errors`.
5. **Variant rotation.** The proposal removes matrix rules and support rows for variants the selected release drops, citing upstream scoping, and re-adds variants when support returns; discovery derives its variant universe from current records so a dropped variant is not chased forever.
6. **Historical awareness.** Prompts direct research to read `docs/support-records.md` and run `git log` / `git show` on files it changes, and to cite the introducing commit when overriding an earlier decision.
7. **Pack failure ingestion.** Manual dispatch accepts a `pack-run-url` of the trusted repository; prepare fetches the run, its failed jobs, and bounded log tails, and freezes a `pack_failure` record; the research prompt names the record for diagnosis; anything but a trusted actions run URL fails preparation.

### Notes / Constraints / Caveats

- Python 3.10+, typed data, small functions; JSON/YAML serialized as data; subprocess arguments as arrays; automation stays outside the public library.
- PEP 440 ordering via the existing `packaging`-based `version()` helper in `tools/auto_sync/discovery.py`.
- The agent workspace already carries full git history (`fetch-depth: 0`), so historical awareness needs prompt and skill changes only, not checkout changes.
- Frozen bundle keys added by this spec: `prerelease_packages`, `pack_failure`. Candidate checkouts must not be able to grant themselves prerelease permission.
- Pack-run logs are untrusted data: excerpted verbatim, bounded, never executed.

### Boundaries

- **Always:** adapt patches before considering removal; cite upstream evidence for every removal or rotation; keep proposals within the allowed patch paths; sign off commits (DCO) with Conventional Commits.
- **Ask first:** adding a package to the prerelease whitelist (reviewed PR); changing revise-mode behavior; touching the publication pipeline.
- **Never:** permit engine prereleases in discover mode; execute upstream scripts, PR comments, or log excerpts as shell; publish images or invoke Pack from auto-sync; chase more than one release line per run.

### Risks and Mitigations

- A misconfigured whitelist permits an unintended prerelease. → The file lands through reviewed PRs, keys are validated against the known set, and the list is frozen from the default checkout.
- A chase target's patches cannot be adapted. → The group blocks with the specific missing fact; deletion requires evidence; maintainers can restore patches manually.
- Pack logs are large or carry sensitive content. → Excerpts are bounded tails fetched through the authenticated client under the untrusted-data rule.
- Variant rotation removes a variant users still deploy. → Removal requires cited upstream scoping, `support-records.md` plus git history review precedes the edit, and re-add is a first-class path when support returns.

## Design Details

### Commands

Run from the repository root on the local macOS machine:

```sh
make prepare
uv sync --locked --all-packages
export AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin   # pinned Qwen/tools for tests that invoke them
uv run pytest tests/auto_sync -q                            # full auto-sync suite (~9 min)
uv run pytest tests/auto_sync/test_discovery.py -q          # focused while editing
uv run pre-commit run --files <changed-files> --show-diff-on-failure
uv run mkdocs build --strict
uv run python tools/auto_sync/lint_workflows.py             # workflow lint per docs/release-automation.md
```

Post-merge end-to-end check: `gh workflow run auto-sync.yml --repo gpustack/runner --ref main`, then inspect the run's discovery selections.

### Project Structure

- `tools/auto_sync/discovery.py` — release eligibility, chasing selection, variant universe, record matching.
- `tools/auto_sync/run.py` — CLI stages (`prepare`, `research`, ...), `_selected_sources` (run.py:290), prompt construction, `_bind_discovery`.
- `tools/auto_sync/proposal.py` — proposal schema and row validation (prerelease policy enforcement point).
- `tools/auto_sync/assemble.py`, `checks.py`, `publish.py` — downstream stages; unchanged by this spec.
- `pack/prereleases.yaml` — NEW: maintainer-reviewed prerelease whitelist.
- `.github/workflows/auto-sync.yml` — dispatch inputs; gains `pack-run-url`.
- `.agents/skills/runner-release-sync/SKILL.md`, `docs/release-automation.md` — policy documentation.
- `tests/auto_sync/` — unit fixtures (`test_discovery.py`), stage tests, and end-to-end harness (`test_e2e.py`, `fixtures/e2e/`).

### Code Style

Existing idiom: pure functions returning dicts, `proposal.require(...)` for fail-closed validation, and explicit status strings.

```python
def _chase(base, eligible):
    """One release line above the base: lowest line, highest member within it."""
    if base is None:
        return max(eligible)
    above = [value for value in eligible if value > base]
    if not above:
        return max(eligible)
    line = min((value.epoch, value.major, value.minor) for value in above)
    return max(value for value in above if (value.epoch, value.major, value.minor) == line)
```

Comments state the rule and its reason in one or two lines; no task identifiers or revision history.

### Implementation Plan

PR mapping: PR 1 = T1 + T2 (branch `feat/auto-sync-incremental-chasing`, code complete, full suite pending). PR 2 = T3 → T4 → T5. PR 3 = T6.

- [x] **T1 · Discovery chasing and record-derived variant universe**
      Blocked by: None
      Owns: `tools/auto_sync/discovery.py`, `tests/auto_sync/test_discovery.py`
      Gate: review
      Acceptance: next-line chasing, highest patch/post within the line, patch of the current line first, base fallback to newest without records, CANN plugin chasing, universe derivation with `SUBSCRIPTIONS` fallback, and unchanged-when-nothing-exceeds all pass unit tests.
      Verify: `uv run pytest tests/auto_sync/test_discovery.py -q` (63 passed)
- [x] **T2 · Bind and prompt alignment for chasing**
      Blocked by: T1
      Owns: `tools/auto_sync/run.py` (bind + research/proposal prompts), `tests/auto_sync/test_e2e.py` (bind tests), `docs/release-automation.md`, `.agents/skills/runner-release-sync/SKILL.md`
      Acceptance: ready rows bind to the selected candidate; a row whose variant sits outside the discovery universe is allowed (re-add path) while represented variants are rejected; prompts state the next-line rule; docs and skill describe chasing.
      Verify: `uv run pytest tests/auto_sync/test_e2e.py -q -k "bind or represented"`
- [ ] **T3 · Prerelease whitelist configuration**
      Blocked by: None
      Owns: `pack/prereleases.yaml`, `tools/auto_sync/run.py` (prepare freeze), `tools/auto_sync/proposal.py` (row policy), `tests/auto_sync/test_proposal.py`, whitelist-focused e2e additions in `tests/auto_sync/test_e2e.py`
      Gate: review
      Acceptance: the whitelist is read from the frozen default checkout and frozen into the bundle as `prerelease_packages`; unknown keys and malformed files fail preparation; an absent file keeps stable-only; whitelisted package rows may select prereleases; engine rows stay stable-only in discover mode; the list reaches the research prompt.
      Verify: `uv run pytest tests/auto_sync/test_proposal.py tests/auto_sync/test_e2e.py -q -k "prerelease or whitelist"`
- [ ] **T4 · Component source-tree supply (vllm-omni, LMCache)**
      Blocked by: None
      Owns: `tools/auto_sync/run.py` (`_selected_sources` and recipe-pin resolution), component-source additions in `tests/auto_sync/test_e2e.py`
      Acceptance: the controller resolves `VLLM_OMNI_COMMIT` and `SGLANG_LMCACHE_VERSION` from selected recipes and supplies those trees beside the engine/plugin trees; unresolvable pins land in `source_errors` and are reported as unverified.
      Verify: `uv run pytest tests/auto_sync/test_e2e.py -q -k "source"`
- [ ] **T5 · Policy prompts and documentation (patch duty, ownership, rotation, history)**
      Blocked by: T3, T4
      Owns: `tools/auto_sync/run.py` (prompt sections), `.agents/skills/runner-release-sync/SKILL.md`, `docs/release-automation.md`
      Acceptance: research and proposal prompts state the patch adapt/delete duty, full component ownership, variant rotation rules, and the support-records/git-history consultation requirement; SKILL.md and docs match the prompts; mkdocs strict build passes.
      Verify: `uv run pytest tests/auto_sync -q -k "prompt" && uv run mkdocs build --strict`
- [ ] **T6 · `pack-run-url` dispatch input and pack failure ingestion**
      Blocked by: T3
      Owns: `.github/workflows/auto-sync.yml`, `tools/auto_sync/run.py` (CLI + prepare ingestion), pack-failure additions in `tests/auto_sync/test_e2e.py` and `tests/auto_sync/fixtures/e2e/`
      Gate: review
      Acceptance: only trusted-repository actions run URLs pass validation; the prepare stage freezes a bounded `pack_failure` record (run id, URL, conclusion, head revision, failed jobs/steps, log tails); the research prompt names the record when present; workflow lint passes.
      Verify: `uv run pytest tests/auto_sync/test_e2e.py -q -k "pack" && uv run python tools/auto_sync/lint_workflows.py`

### Test Plan

- [x] I/we understand the owners of the involved components may require updates to existing tests to make this
      code solid enough prior to committing the changes necessary to implement this enhancement.

#### Prerequisite testing updates

None. The existing e2e harness (`tests/auto_sync/fixtures/e2e/`) already fakes GitHub, registries, and upstream git; it extends in place for the whitelist and pack-failure fixtures.

#### Unit tests

- `tools/auto_sync/discovery.py`: 2026-10-10 — chasing cases added (`test_discovery.py`, 63 passed); no coverage gate in this repo, suite must stay green.
- `tools/auto_sync/proposal.py`: 2026-10-10 — whitelist key validation and prerelease row policy cases.
- `tools/auto_sync/run.py`: 2026-10-10 — `pack-run-url` validation cases (trusted host/repo, job suffix, rejection of anything else).

#### Integration tests

- E2E bind: ready rows against represented/outside-universe variants (`test_discovery_bind_allows_a_variant_outside_the_universe`, updated `test_ready_rows_cannot_target_an_already_represented_variant`).
- E2E whitelist: `prerelease_packages` frozen from the default checkout reaches the research prompt; candidate checkouts cannot self-grant.
- E2E pack failure: a failed run URL yields a frozen `pack_failure` record and a prompt section; a successful run yields a record without failed jobs.
- E2E patch deletion: a group patch that deletes a patch file passes validation and stays within allowed paths.

#### e2e tests

After all PRs merge, dispatch `gh workflow run auto-sync.yml --repo gpustack/runner --ref main` and verify: CUDA/ROCm vLLM chase the next line above the catalog, SGLang chases its next line, CANN SGLang targets the newest line with an available Ascend base image, and blocked groups carry specific missing facts. A separate manual dispatch with a real failed Pack run URL exercises the ingestion path once a failed Pack run exists.

## Alternatives

- **Jump to newest with patch fixes only.** Rejected: skips verifiable intermediate lines and concentrates risk on the newest release, which is exactly where upstream compatibility is least certain.
- **Hard-code the prerelease package list in `discovery.py`.** Rejected: maintainers must tune the list without touching controller code; a reviewed data file is the requested control point.
- **Feed the whole Pack log to research.** Rejected: unbounded, noisy, and against the excerpt discipline used for all other untrusted content; bounded tails of failed jobs carry the signal.
- **Let discovery propose variants directly.** Rejected: variant support evidence belongs to research manifests and release notes; discovery only stops chasing deliberately dropped variants.

## Open Questions

None. The whitelist's initial key set (`lmcache`, `vllm-ascend`, `vllm-omni`) can grow through ordinary reviewed PRs.
