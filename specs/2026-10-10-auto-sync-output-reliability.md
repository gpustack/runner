# Spec: Auto-Sync Output Reliability

Status: Built
Type: Feature

## Summary

Restructure how the auto-sync research workflow instructs its headless model, and give the model a way
to check its own output before replying. Stage prompts move from Python string concatenation into
version-controlled templates whose final block is the output contract. A repository checker command lets
the model validate a draft against the controller's own validator inside the session. Five consecutive
workflow runs (38021227566, 38022840112, 38025148564, 38027308465 and the earlier 379-series) failed or
burned repair rounds on output-contract problems that the model could have caught itself: undeclared
grammars, prose around the JSON object, and a reply truncated at the single-message output ceiling.

## Motivation

The research stage costs 2–5 million reported tokens and about 17–25 minutes per run. Each contract
failure discovered only by controller validation costs one bounded repair session (40–190k tokens) or the
whole run. Investigation of the failed runs showed three structural weaknesses:

- The output-format rules sit at the top of a 5.3 KB prose block (66 concatenated sentences), followed by
  a ~21 KB JSON payload. The model reads the format rules furthest from the generation point.
- Every contract rule is declared by hand in up to three surfaces (prompt, SKILL.md, release guide). Three
  of the five failures were rules the validator enforced but no surface declared.
- The model has no way to test its draft against the validator. It learns the contract only from a
  rejection after the reply is final.

### Goals

- The model reads the output contract as the terminal block of every stage prompt.
- Prompt text lives in reviewable template files with validated placeholders, not in Python literals.
- The model can run a repository checker that returns the controller validator's exact verdict on a draft.
- The controller's fail-closed validation stays the only acceptance gate; the checker is advisory.
- Contract wording stays synchronized across the prompt template, the skill, and the release guide,
  enforced by test.
- Success measure: the next scheduled auto-sync run completes the research stage with at most one repair
  round, and no repair round is spent on a failure class the checker reports.

### Non-Goals

- Rewriting the policy prose into a fully bulleted form. Policy sentences keep their rationale.
- Changing validator semantics, repair-round defaults, budgets, or the raw-JSON final-reply contract.
- An MCP server implementation. The checker ships as a shell command first (see Alternatives).
- Preserving conversation or thinking context across repair sessions.
- Slimming the analysis prompt. No analysis reply has truncated so far.

## Proposal

Make the stage prompts shorter at the point of generation and make validation reachable inside the
session. The work has two phases. Phase 1 restructures the prompts: templates under
`tools/auto_sync/prompts/`, payload before instructions, and a terminal keyword contract block. Phase 2
adds `tools.auto_sync.check_draft`, a shell command the model runs on its draft before its final reply;
the command assembles and validates the draft with the same code the controller uses and prints the first
error or an OK line. The parked branch `autosync/proposal-output-ceiling` (commit af276f6, suite-green)
folds into this work as the size-budget rule and the truncation-aware repair guidance.

### User Stories

#### Story 1

As the auto-sync maintainer, I want stage prompts kept in version-controlled template files with the
output contract as the final block, so that I can review contract changes in clean diffs and the model
reads format rules last.

#### Story 2

As the auto-sync maintainer, I want the model to check its draft with a repository command before
replying, so that contract violations surface inside the session instead of after a failed run.

#### Story 3

As the auto-sync maintainer, I want each contract keyword asserted to appear in the template, the skill,
and the release guide, so that no surface can drift from the validator again.

#### Story 4

As the auto-sync maintainer, I want truncation-shaped failures to carry size-budget guidance in the stage
prompt and the repair prompt, so that output-ceiling failures stop consuming repair rounds.

### Core Features & Acceptance Criteria

#### F1 · Prompt templates

- Analysis, proposal, and repair prompts live in `tools/auto_sync/prompts/*.md`, rendered with
  `string.Template` `$placeholder` substitution for computed values (budgets, turns, payload JSON).
  Contract sentences contain literal braces, so `str.format` cannot be used.
- The loader fails when the template's placeholder set differs from the supplied value set, whether a
  placeholder is missing from the template or a supplied value is unused.
- Acceptance: `uv run pytest tests/auto_sync` passes; a template audit test proves the assembled prompt
  carries no unsubstituted placeholder and the loader rejects placeholder-set drift.

#### F2 · Contract-last structure

- The assembled stage prompt orders: role and scope prose, policy prose, payload JSON, then a terminal
  `OUTPUT CONTRACT` block of `REQUIRED:` / `NEVER:` keyword lines.
- Acceptance: a test asserts the contract block starts after the payload and ends the prompt; the
  existing policy-sentences test asserts against the templates.

#### F3 · Draft checker command

- `python -m tools.auto_sync.check_draft --stage analysis|proposal` reads a draft JSON object on stdin
  inside the stage workspace (`< file` or heredoc; the harness shell's stdin is EOF).
- For the proposal stage it inlines `patch_file` references with `tools.auto_sync.assemble` before
  validating, exactly as the controller does.
- Every completed check exits 0 and prints `VALID` or `INVALID` as the first line, with the validator's
  first error after `INVALID`. An invalid draft is data, not a tool failure: three identical failing
  tool calls let the session's tool guard kill the process (`agent.py:339-361`), which no repair round
  can recover. Environment failure (for example ImportError) exits 3 with a distinct line, and the
  templates tell the model to reply normally when the checker is unavailable.
- The controller writes the seed data the checker needs (identity, discovery, the full evidence map
  with paths and revisions, prerelease permissions, packages) as read-only files in a single dot-dir at
  the workspace root, once per stage: analysis seed at research start, proposal seed when the proposal
  workspace is created (`run.py:1499-1504`). The controller lists the dot-dir in the workspace's
  `.git/info/exclude`, so `git add -A` never sweeps seed files into a group patch, which the
  controller rejects as a forbidden patch path (`proposal.py:257-294`).
  The checker fails closed on missing or unreadable seed data.
- Stage prompts instruct the model to run the checker on its draft and fix every reported error before
  the final reply. All three templates (analysis, proposal, repair) carry the instruction and carve out
  a checker-scratch exception to the "do not edit files" rule.
- Acceptance: for every fixture draft, the checker's verdict matches the controller validator's verdict
  at the `validate_*` layer. Parity stops there: `_bind_discovery` (silent degradation, `run.py:531-533`)
  and `_check_group_patches` (apply failures, `run.py:1050-1054`) stay controller-only, and the
  checker's OK line says so. An e2e test proves a reply rejected by the controller still fails even when
  the checker passed it (advisory, never a gate); the checker performs no network, registry, or GitHub
  access. The model can modify the checker or its seed inside the workspace; this is accepted and
  documented, because controller validation remains the only gate.

#### F4 · Size budget and truncation guidance (folds the parked branch)

- The proposal prompt, the skill, and the release guide state that the final reply is one model message
  with a hard output ceiling and that reason and report text stay concise.
- `_repair_prompt` re-parses the failed reply with `json.loads`. A `JSONDecodeError` at end of text
  (`pos == len(reply)`) or an unterminated string takes the truncation branch: return the complete
  object with concise reason and report text. Every other parse failure (prose prefix at char 0,
  trailing prose, duplicate keys, non-finite numbers, non-object JSON) takes the existing prose branch.
- Acceptance: the parked branch's tests (`test_repair_prompt_guides_*`, policy-sentence assertions) pass
  after the fold, adjusted to pin all four reply shapes above; no other behavior from af276f6 is lost.

#### F5 · Three-surface sync test

- Each contract keyword (raw-JSON reply, package version grammar, patch version grammar, settled-candidate
  rule, candidate-group status rule, output ceiling rule) is parsed from the prompt template's
  `OUTPUT CONTRACT` block — no fourth hardcoded list — and asserted verbatim in the template,
  `SKILL.md`, and `docs/release-automation.md` (surrounding prose may paraphrase). The
  `#proposal-output` anchor in the release guide stays; the proposal prompt has the model read it
  in-session (`run.py:1443`). The schema stub in the guide is a field-shape example, not a keyword.
- Acceptance: removing any keyword from any one surface fails the test.

### Notes / Constraints / Caveats

- Python 3.10+, typed data, small functions; the checker reuses `proposal.py` and `assemble.py` verbatim.
- No new third-party dependency. The checker is a module entry point, not a server.
- The model already runs shell checks (`git apply --check`); the checker follows that pattern.
- Templates render with `string.Template`; `$placeholder` never collides with the JSON payload or the
  brace-bearing contract sentences. Conditional repair guidance arrives through named slots
  (`$correction`, `$guidance`) whose values may be empty strings, so the templates stay static.
- `MAX_SESSION_TURNS // 4` and similar budget values are computed at the call site and passed in; the
  templates carry no arithmetic.
- Templates keep the existing sentence wording wherever possible to limit test churn and review size.
- The parked branch `autosync/proposal-output-ceiling` (af276f6) holds the F4 work; cherry-pick or
  re-apply it during implementation, then delete the branch.
- Operator-side mitigation stays outside the repo: `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_EXTRA_BODY`
  `{"max_tokens": ...}` raises the provider output ceiling without code changes.

### Boundaries

- **Always:** keep the controller's fail-closed validation as the only acceptance gate; run the full
  `tests/auto_sync` suite and pre-commit hooks before every PR; write prompts, docs, commits, and PR text
  in English; Conventional Commits with DCO sign-off.
- **Ask first:** adding a third-party dependency; changing validator semantics, repair-round defaults, or
  token budgets; weakening or removing any existing prompt rule not named in this spec.
- **Never:** let a checker pass substitute for controller validation; execute model-supplied code in the
  checker; give the checker network, registry, or GitHub access; put credentials in checker seed data;
  relax the raw-JSON final-reply contract.

### Risks and Mitigations

- Risk: the model skips the checker and fails as today. → The stage prompt mandates the check and the
  controller still gates, so behavior cannot regress below the current failure rate.
- Risk: placeholder drift between templates and the loader. → The loader fails on missing or unused
  placeholders; the template audit test asserts it.
- Risk: stale or forged checker seed data. → The controller writes seed files per stage; the checker
  fails closed on unreadable or mismatched seed data.
- Risk: repeated checker calls burn the bounded turn and tool-call budgets. → Budgets already bound the
  session; the checker guidance asks for one check on the final draft.
- Risk: an invalid draft checked with a nonzero exit trips the tool guard after three identical failing
  calls and kills the session beyond repair. → The checker exits 0 for every completed check and reports
  `VALID`/`INVALID` as data; only environment failure exits distinctly (3).
- Risk: the model edits the checker or its seed inside the workspace to force a pass. → Accepted by
  design: the checker is advisory, controller validation is the only gate, and F3 documents this.
- Risk: the prose/payload sentinel line is forged by model text, breaking prompt-parsing tests. → Model
  text occurs only inside the payload and controller prose never contains the sentinel, so the first
  occurrence is authoritative.
- Risk: prompt reordering changes model behavior in unmeasured ways. → The next scheduled run is the
  acceptance signal (Goals); reordering keeps wording identical.

## Design Details

### Commands

```sh
make prepare
uv sync --locked --all-packages
export AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin
uv run pytest tests/auto_sync -q
uv run pre-commit run --files <changed-files> --show-diff-on-failure
uv run mkdocs build --strict
uv run python tools/auto_sync/lint_workflows.py .github/workflows/auto-sync.yml  # workflow changes only
```

Run everything from the repository root on this machine; no remote environment is involved.

### Project Structure

```text
tools/auto_sync/
  prompts/            # NEW: analysis.md, proposal.md, repair.md templates (F1)
  run.py              # stage orchestration; assembles prompts from templates; writes checker seeds
  proposal.py         # validators the checker reuses (F3)
  assemble.py         # patch_file inlining the checker reuses (F3)
  check_draft.py      # NEW: checker module entry point (F3)
  agent.py            # MCP and process plumbing (unchanged)
tests/auto_sync/
  test_e2e.py         # policy-sentence, repair-prompt, and e2e coverage
  fixtures/           # draft fixtures for checker verdict parity
docs/release-automation.md           # contract surface (F5)
.agents/skills/runner-release-sync/SKILL.md  # contract surface (F5)
```

### Code Style

Small typed functions; `ProposalError` for every rejection with a stable message; JSON and YAML
serialized as data; no comments unless they state a rule and its reason.

```python
def require(predicate, message):
    if not predicate:
        raise ProposalError(message)
```

### Implementation Plan

Three serial tasks, one PR each. The DAG is linear: T2 reorders the templates T1 creates, and T3
writes checker instructions into the reordered templates.

- [x] **T1 · Prompt templating + size-budget fold (F1, F4)**
      Blocked by: None
      Owns: `tools/auto_sync/prompts/**`, `tools/auto_sync/run.py`, `tests/auto_sync/**`,
            `docs/release-automation.md`, `.agents/skills/runner-release-sync/SKILL.md`
      Acceptance:
      - Analysis, proposal, and repair prompts render from `tools/auto_sync/prompts/*.md` via
        `string.Template`; the loader fails when the template placeholder set differs from the
        supplied value set.
      - A sentinel line constant separates controller prose from payload; the 19 test sites that
        parse prompts with `split("\n", 1)[1]` migrate to it.
      - The parked branch `autosync/proposal-output-ceiling` (af276f6) is cherry-picked in and
        adjusted: `_repair_prompt` re-parses the failed reply and branches per F4; tests pin the
        truncated-mid-string, truncated-at-end, prose-prefix, and prose-suffix shapes.
      - Size-budget wording lands in the proposal template, SKILL.md, and the release guide.
      Verify: `export AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin && uv run pytest tests/auto_sync -q`,
              `uv run pre-commit run --files <changed> --show-diff-on-failure`,
              `uv run mkdocs build --strict`

- [x] **T2 · Contract-last ordering + three-surface sync test (F2, F5)**
      Blocked by: T1
      Owns: `tools/auto_sync/prompts/**`, `tools/auto_sync/run.py`, `tests/auto_sync/**`,
            `docs/release-automation.md`, `.agents/skills/runner-release-sync/SKILL.md`
      Acceptance:
      - The assembled stage prompt orders prose, payload JSON, then the terminal `OUTPUT CONTRACT`
        block of `REQUIRED:` / `NEVER:` lines; a test asserts the block starts after the payload and
        ends the prompt.
      - The keyword matrix test parses contract keywords from the template's `OUTPUT CONTRACT` block
        and asserts each verbatim in the template, SKILL.md, and `docs/release-automation.md`;
        removing a keyword from any one surface fails the test.
      - `test_policy_sentences_reach_stage_prompts` asserts against the templates.
      Verify: same as T1

- [x] **T3 · Draft checker command (F3)**
      Blocked by: T2
      Gate: review
      Owns: `tools/auto_sync/check_draft.py`, `tools/auto_sync/run.py` (seed writing),
            `tools/auto_sync/prompts/**`, `tests/auto_sync/**`
      Acceptance: every F3 bullet — the stdin checker with `VALID`/`INVALID` first line and exit 0
      on completed checks, exit 3 on environment failure, proposal-stage `patch_file` inlining,
      verdict parity at the `validate_*` layer, per-stage seed writing into the workspace dot-dir,
      fail-closed seed handling, checker instructions in all three templates with the scratch
      exception, and the advisory, fail-closed-seed, tool-guard-survival, and no-network proofs.
      Verify: same as T1

### Test Plan

[ ] I/we understand the owners of the involved components may require updates to existing tests to make
this code solid enough prior to committing the changes necessary to implement this enhancement.

#### Prerequisite testing updates

None. The suite is green on main (748 passed, 17 skipped) and on the parked branch (751 passed).

#### Unit tests

- Prompt loader: placeholder-set equality (missing and unused both fail); `$placeholder` substitution
  with brace-containing values; call-site budget values render.
- `_repair_prompt`: four reply shapes pin their branches — truncated mid-string ("Unterminated string
  starting at"), truncated at end (`pos == len(reply)`), prose prefix (`pos == 0`), prose suffix
  ("Extra data"); duplicate-key, non-finite-number, and non-object drafts take the prose branch.
- `check_draft`: `VALID`/`INVALID` first line with exit 0 on completed checks; exit 3 on environment
  failure; fail-closed on missing or unreadable seed; verdict parity with `validate_analysis` and
  `validate_proposal` over every fixture draft; no network, registry, or GitHub access (socket-blocked
  run).
- Template audit: no unsubstituted `$placeholder` in assembled prompts; the keyword matrix parses the
  template `OUTPUT CONTRACT` block and asserts each keyword verbatim in the template, SKILL.md, and the
  release guide; removing a keyword from any surface fails the test.
- Per-package target: `tools/auto_sync` — 2026-10-10 — no coverage-percentage gate exists; the suite
  must stay green with these cases added.

#### Integration tests

- E2E with a mocked model: the assembled prompt ends with the `OUTPUT CONTRACT` block after the
  payload; sentinel-line prompt parsing across the 19 migrated sites;
  `test_policy_sentences_reach_stage_prompts` re-asserted against the templates; seed files are written
  per stage into the workspace dot-dir and `git add -A` never sweeps them into a group patch; a
  checker-passed invalid reply still fails controller validation; three identical checker calls do not
  trip the tool guard (the session survives).
- Full suite: `export AUTO_SYNC_TOOL_BIN=/tmp/runner-pr-284-r3-tools/bin && uv run pytest tests/auto_sync -q`.

#### e2e tests

The acceptance signal is operational: the next scheduled auto-sync run completes the research stage
with at most one repair round and no repair round spent on a failure class the checker reports. No GPU
or live-provider e2e runs in CI, per repository policy; the offline suite above is the automated bar.

## Alternatives

- **MCP stdio server for the checker.** The model calls tools through MCP today (GitHub, DeepWiki), and a
  native server matches the user's framing. Rejected for the first iteration: no MCP SDK is in the
  dependency tree, so the server would hand-roll JSON-RPC over stdio plus lifecycle management for the
  same advisory effect a shell command delivers. Revisit if the model proves unreliable at invoking the
  shell checker.
- **Tolerant final-reply parsing in the controller** (strip prose around the JSON). Rejected: prose
  replies going to repair is tested, deliberate design; tolerance would weaken the contract signal.
- **Preserving thinking context across repair sessions.** Rejected: replays the full untrusted transcript
  at roughly 100x the repair token cost, lets untrusted content steer later sessions, and cannot fix
  truncation, which is a per-message ceiling.
- **Full bullet-ization of all policy sentences.** Rejected: rationale-bearing sentences lose information
  at 10–15 words, and the churn rewrites every policy-sentence assertion. The keyword block covers the
  output contract only.
- **Off-the-shelf JSON Schema validation MCP** (for example vinkius-labs/json-schema-validator-mcp,
  EienWolf/jsonshema_mcp). Rejected: JSON Schema can express the shape layer (field sets, enums,
  patterns) and static conditionals, but not the rules our failures came from — real PEP 440 parsing,
  cross-entity aggregation (candidate status versus group statuses), reference closure between groups and
  candidates, DAG acyclicity, and git-diff structure. Encoding the expressible subset would duplicate
  `proposal.py` in a second validator that drifts, and its generic error messages weaken the repair loop,
  which depends on the exact rejection text. It also adds a community server to a pinned, offline-tested
  toolchain for a saving of about a hundred lines of plumbing around the already-tested validator.
- **Shared OUTPUT_CONTRACT constant instead of full templates.** Rejected: the maintainer reviews prompt
  wording in complete template files (Story 1); a Python constant assembled behind the payload hides the
  contract from reviewable diffs and reintroduces the drift the templates remove.
- **Do nothing beyond the parked fix.** Rejected: it leaves the contract at the top of a 26 KB prompt and
  keeps validation unreachable inside the session, so the same failure classes recur.

## Open Questions

- ~~Should the analysis stage also run the checker, or only the proposal stage?~~ Resolved: both. The
  checker takes `--stage analysis`, and all three templates carry the checker instruction.
- Does the scheduled workflow's configured provider honor a raised `max_tokens`? That is operator
  configuration outside this spec; the run after this ships will show whether the ceiling still binds.
