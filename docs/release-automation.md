# Release automation

Auto-sync researches upstream releases and prepares one formal pull request for human review.
It performs static checks before merge. Maintainers run Pack afterward with the required image-build resources.
Auto-sync does not build service images, publish images, merge PRs, or measure installed dependencies.

The canonical instructions are `.agents/skills/runner-release-sync/SKILL.md`.
`AGENTS.md` supplies project conventions. `.claude/skills` links to the same skill directory.
The workflow configures the model, the read-only GitHub MCP, and the hosted DeepWiki MCP before the research stage starts its headless Qwen sessions.
No personal skills, cached sessions, or off-repository instruction files are required.

## Discovery and release policy

Weekly discovery runs on Sunday at 13:07 UTC, or 21:07 in Asia/Shanghai.
Maintainers can also start discovery manually.
Scheduled and manual discovery use one frozen default-branch revision for controller code, instructions, and validators.
If a run fails on transient errors, re-run its failed jobs from the run page.

There are six subscriptions:

| Backend | vLLM | SGLang |
| --- | --- | --- |
| CUDA | `vllm-project/vllm` | `sgl-project/sglang` |
| ROCm | `vllm-project/vllm` | `sgl-project/sglang` |
| CANN | `vllm-project/vllm-ascend` with its documented stable vLLM engine | `sgl-project/sglang` and documented CANN artifacts |

Select only the newest eligible release per subscription. Stable engines include post releases.
Exclude drafts and unrelated release streams. Do not propose older missing versions as catch-up work.
If the newest candidate is blocked, report it instead of selecting an older release.

CANN/vLLM uses the stable vLLM engine version for Runner releases and image tags.
Ascend plugin prereleases are normal candidates, paired with the stable engine documented upstream.
README marks this support as RC. That display marker does not alter the engine or actual plugin version.
Keep the actual plugin version explicit, including its prerelease suffix.
Historical `(rc)` text has unknown plugin identity; do not derive a plugin suffix from it.
Other engine prereleases require an explicit maintainer request.

Read `gpustack_runner/runner.py.json`, [Support records](support-records.md), and [Supported runners](supported-runners.md) from the frozen default branch.
An exact identity in any source prevents another discovery proposal.
A merged `prepared` record counts while Pack is pending; an unmerged proposal does not.
Compare structured backend, service, accelerator variant, engine version, and actual Ascend plugin version.
Runtime lines and CPU platforms are evaluated when preparing the proposal and promoting its support record.
Dockerfile pins help prepare changes but do not replace the detection sources.
A failed read or parse is a failed inspection, not an absent version or an unchanged result.

CANN aliases follow the packaging matrix: `950`, `A5`, and `950/A5` mean `950`.
`A3`, `910C`, and `A3/910C` mean `a3`. `910B` means `910b`; `310P` means `310p`.
Other hardware names are not inferred as aliases.

At most one managed auto-sync upgrade PR remains open.
Weekly and manual discovery report newer findings in the job summary while that PR is pending.
They do not rewrite it. Only an authorized `/auto-sync` command starts a revision.
After a proposal closes, a later discovery can start a new cycle while retaining old branches and human work.

## Compatibility research

Read release notes, installation guidance, compatibility documentation, and relevant resolved upstream issues.
Pin source evidence to a release or exact commit where possible.
Read upstream Dockerfiles at the selected release tag or resolved commit, rather than the moving default branch.
Follow their referenced requirements files, installation scripts, and patches.
Trace `FROM` ancestry, effective `ARG` overrides, CPU/platform branches, and source-build decisions.
Identify declared Python, Torch, runtime, plugin, and additional package versions along that path.
Read current Dockerfile defaults and matrix overrides together; either can select the effective version.
Inspect actual image manifests and configurations with the installed registry tools.
Resolve each requested platform digest instead of assuming amd64 and arm64 artifacts are equivalent.
Cross-check source declarations against registry evidence. Dockerfile declarations are not measured installed packages in a published image.

For every affected combination, record:

- Backend, engine version, effective runtime version, accelerator variant, and CPU platform.
- Base-image reference, manifest digest, platform digest, and configuration platform.
- Actual accelerator plugin version where applicable.
- Python, Torch, runtime, and additional package versions, with unknown values explicit.
- Package choices, patch dispositions, source-build choices, and disabled features.
- Source links, evidence classification, executed checks, and deferred image/GPU checks.

Classify compatibility conclusions as `upstream`, `inference`, or `unresolved`.
An available manifest proves an artifact exists. It does not prove package or hardware compatibility.
A missing compatibility-table row is an evidence gap, not proof of unsupported hardware.
Conflicting evidence blocks the affected group.

Evaluate Mooncake, LMCache, LMCache-Ascend, Diffusers, and applicable Omni packages with the engine and runtime.
The newest additional package is not necessarily compatible.
Preserve existing cross-image LMCache protocol constraints and group dependent changes together.
Independent ready groups can proceed while blocked groups remain unchanged.

Every affected patch needs one disposition: retain, adapt, remove, or add.
Record its reason, applicable versions and platforms, and upstream issue or commit evidence.
Apply each component's patch sequence against the exact selected source revision when available.
If source is unavailable, mark application checks unverified. Successful application does not prove runtime behavior.

Keep proposed support rows `prepared`, with explicit engine, plugin, runtime, variant, and intended platforms.
Do not populate the generated catalog with guessed package versions.
[Packaging](packaging.md) owns recipe selection; [Dependency metadata](dependency-metadata.md) owns measured dependency semantics.

## Analysis handoff

Research runs as two sequential independent headless stages: analysis, then proposal.
The analysis session confirms compatibility facts and returns analysis schema 1 JSON; it never edits files or proposes changes.
The controller validates that JSON against the frozen identity, the discovered selection, and the acquired source revisions.
An evidence entry that differs from exactly one supplied evidence key only by whitespace is normalized to that key before the citation check.
Forged statuses, missing evidence, or out-of-scope evidence references end the run before the proposal session starts.
The proposal session starts with a fresh conversation containing only the validated analysis, never the analysis transcript.

When a stage's final reply fails the existing parse or validation gates, the controller starts bounded fresh repair sessions instead of failing immediately.
A repair session receives the rejected reply text, the exact parse or validation error, and the stage schema, and must return one corrected raw JSON object without researching, editing, or accessing the network again.
An analysis-stage repair also receives the supplied evidence keys, so a rejected evidence reference can be mapped to the exact supplied key.
A proposal-stage repair reuses the stage workspace, so patch files referenced by the rejected reply persist; the corrected reply keeps its `patch_file` references rather than inlining patches.
Repair output passes through the same parse and validation pipeline; no gate is relaxed and process failures, timeouts, or missing final results are never repaired.
`AUTO_SYNC_MAX_REPAIR_ROUNDS` bounds the repair sessions per stage; default `2`, and `0` disables repairs.
When the rounds are exhausted the run fails with the last error, exactly as an unrepairable rejection does.

All stage and repair sessions share one reported-token budget and the outer deadline; earlier consumption reduces what later sessions may spend.
A stage that exhausts either shared limit fails before starting another session.
The validated analysis persists as `analysis.json` beside `proposal.json` in the research artifact.

## Proposal output

The controller supplies frozen identity and output locations. Return one JSON object as the final Qwen result.
`tools/auto_sync/proposal.py` defines the schema; `checks.py` validates the candidate as data.
Do not replace the supplied identity or produce an interactive question instead of an assessment.

The top-level fields are:

| Field | Content |
| --- | --- |
| `schema_version` | Integer `1` |
| `identity` | Supplied `repository`, `default_sha`, `head_sha`, `mode`, `pr_number`, `command_id`, and `command_digest` |
| `candidates` | One assessment per subscription, including unchanged, blocked, and failed subscriptions |
| `groups` | Compatibility groups referenced by the assessments |

Each candidate has `subscription`, `status`, `groups`, and `reason`.
Its subscription is one of `cuda/vllm`, `cuda/sglang`, `rocm/vllm`, `rocm/sglang`, `cann/vllm`, or `cann/sglang`.
`groups` contains related group IDs. Keep a concrete reason even when no group is needed.

Each group has `id`, `status`, `reason`, `depends_on`, `report`, `patch`, and `rows`.
Group IDs contain letters, digits, underscores, and hyphens, such as `cuda-vllm`.
Use an empty dependency list when independent. A ready group requires a nonempty allowed-path patch and complete compatibility rows.
An unchanged group carries no patch. Groups must not contain cyclic or unknown dependencies.

Each row has these fields:

```text
backend, service, variant, runtime, old_engine_version, engine_version,
plugin_version, platform, base_image, manifest, python, torch,
packages, patches, conclusion, sources, checks, deferred
```

Use canonical matrix variants. `plugin_version` is the actual Ascend version for CANN/vLLM and `null` otherwise.
The row's `runtime` must match the effective `<BACKEND>_VERSION` build argument, including its patch version.
Support records use its catalog runtime line, such as `13.0` for a `13.0.1` configuration.
Keep unknown optional versions as `null`; do not invent them to satisfy a report.
For a ready row, `manifest` contains `digest`, `platform_digest`, `platform`, `config_platform`, and `sources`.
Both platform fields must match the row. An unavailable manifest can be `null` only for a non-ready row.
`sources`, `checks`, and `deferred` are lists. Keep deferred Pack and GPU checks explicit.
The report records runtime and other compatibility reasons that have no dedicated schema field.

Each package choice contains `name`, `version`, `decision`, `reason`, and `sources`.
The `name` is the canonical choice key behind the recipe pin: `lmcache`, `mooncake`, `lmcache-ascend`, `vllm-omni`, or `diffusers`.
Never use the installed distribution name (for example `mooncake-transfer-engine-rocm`) in place of the canonical key.
Decisions are `retain`, `update`, `disable`, or `source`.
Each patch choice contains `path`, `disposition`, `reason`, `versions`, `platforms`, `sources`, `source_repository`, and `source_revision`.
Use an exact source commit or `null` when unavailable.
For engine patches, `versions` includes the selected engine. For Ascend patches, it includes the selected plugin.
For Omni patches, it states engine applicability; the source commit must match the declared Omni package pin.
The controller resolves each selected release or package pin independently before checking the claimed commit.
The controller independently acquires source and Ascend pairing evidence; an agent assertion cannot substitute for it.
If independent target resolution fails, the checked source revision is `null` and its application check is unverified.

| Assessment | Meaning |
| --- | --- |
| `ready` | A complete proposal whose required static checks pass |
| `unchanged` | Successful inspection found no applicable change |
| `blocked` | A required decision or compatibility fact remains unresolved |
| `failed` | Configuration, tools, deadlines, or the output contract failed |

Preserve mixed outcomes and the limits of every group.
The PR report includes old/new versions, release changes, platform evidence, package/patch decisions, checks, and post-merge build targets.
Missing or malformed output remains failed even if the process exits zero.
Only trusted validation can accept a ready group for publication.

Use `tests/auto_sync/fixtures/proposals/ready.json` for the field shape. Its versions and evidence are fixture data.
Write each group's patch to a UTF-8 file inside the session workspace and set the group's `patch_file` to its workspace-relative path.
Return the draft JSON as the final Qwen result; the controller inlines each `patch_file` with `tools.auto_sync.assemble` before validation.
The assembler rejects a `patch_file` that resolves, including through symlinks, outside the session workspace.
The helper does not validate compatibility or generate Git diffs.
Do not hand-escape diffs or create commits and rebases to split them.
Check ordered component patches with `git apply --check` before editing recipes. A fuzzy check does not meet the validation gate.

## Model configuration

The workflow selects and authenticates the model before Qwen starts.
Use the configured model; do not launch another agent to change providers.
No local model installation or interactive login is needed.

Scheduled and manual runs read these repository or organization settings.
A manual dispatch can additionally override the runner profile, the token budget, the repair-round bound,
and the thinking, sampling, and reasoning-effort settings; each dispatch field pre-fills its documented default.
The `llm-*` names below are the workflow's internal settings.

| GitHub configuration | Kind | Setting or purpose |
| --- | --- | --- |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL` | Required Variable | `llm-url`: provider base URL |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL` | Required Variable | `llm-model`: provider model identifier |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN` | Required Secret | `llm-auth-token`: one token or equivalent tokens separated by commas |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL` | Optional Variable | `llm-protocol`: `openai`, `openai-responses`, or `anthropic` |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_USE_ANTHROPIC` | Optional Variable | `llm-use-anthropic`: legacy selector |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING` | Optional Variable | `llm-thinking`: `enabled` or `disabled` |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING_CLEAR` | Optional Variable | `llm-thinking-clear`: boolean string; default `true` |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TEMPERATURE` | Optional Variable | `llm-temperature`: numeric value |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TOP_P` | Optional Variable | `llm-top-p`: numeric value |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_REASONING_EFFORT` | Optional Variable | `llm-reasoning-effort`: `minimal`, `low`, `medium`, `high`, or `max` |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TIMEOUT` | Optional Variable | `llm-timeout`: positive request timeout in seconds |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_CONTEXT_WINDOW_SIZE` | Optional Variable | `llm-context-window-size`: positive integer |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODALITIES` | Optional Variable | `llm-modalities`: JSON object of supported input modality boolean overrides |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_HEADER` | Optional Variable | `llm-auth-header`: custom authentication header name |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_EXTRA_HEADERS` | Optional Secret | `llm-extra-headers`: `K=V,K=V`; values may contain credentials |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_EXTRA_BODY` | Optional Variable | `llm-extra-body`: JSON object without credentials |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_MAX_SESSION_TOKENS` | Optional Variable | `max-session-tokens`: positive cumulative reported-token budget; default `20000000` |
| `CI_GPUSTACK_RUNNER_AUTOSYNC_MAX_REPAIR_ROUNDS` | Optional Variable | `max-repair-rounds`: non-negative repair-session bound per research stage; default `2` |
| `CI_PRT_GENERATOR_ID` | Required Secret | Existing GitHub App ID |
| `CI_PRT_GENERATOR_KEY` | Required Secret | Existing GitHub App private key |
| `AUTOSYNC_RUNNER` | Optional Variable | Linux runner label; default `ubuntu-24.04` |

Protocol defaults effectively to `openai`.
An explicit protocol takes precedence over the legacy selector. Leave the protocol unset when using that selector.
Legacy true values are `true`, `1`, and `yes`; false values are `false`, `0`, `no`, or an empty value.
Protocol and selector values ignore case. Invalid selectors fail when no explicit protocol overrides them.

OpenAI-compatible defaults are thinking `disabled`, thinking-clear `true`, temperature `0.4`, and top-p `0.9`.
GLM's `enable_thinking` also receives native `thinking.clear_thinking`. Explicit native clearing choices take precedence.
This provider setting clears cross-turn history. It does not disable current reasoning or guarantee removal within a tool chain.
Reasoning effort is empty by default. Request timeout defaults to `3600` seconds and is separate from command and session limits.
Do not inject those thinking or sampling defaults into Responses or Anthropic requests.
Validate settings before making provider requests; unsupported explicit combinations fail instead of being silently dropped.

Explicit extra-body fields override corresponding convenience settings, including `reasoning_effort`.
They cannot replace the selected model, credentials, messages, or tool control.
An explicit extra-body `enable_thinking` replaces convenience thinking and receives no conflicting implicit thinking default.
If extra-body explicitly supplies both `enable_thinking` and `thinking`, contradictory states are rejected.
Matching explicit states are preserved.
Context-window and modality overrides belong to the selected Qwen provider's `generationConfig`, not HTTP `extra_body`.
`llm-modalities` accepts boolean overrides for `image`, `pdf`, `audio`, and `video`.
Pinned Qwen replaces overrides for the MiniMax-M3 family. Explicit overrides for those models are rejected before launch.
`llm-context-window-size` sets `contextWindowSize`; `llm-modalities` sets `modalities`.
Omitted capability settings use the pinned Qwen defaults. Automatic memory and autoDream remain disabled.

These protocol restrictions belong to the pinned Qwen adapter, not to every provider API:

- Responses accepts `store:false`, rejects `store:true`, and controls `prompt_cache_key` itself.
- Responses accepts only `include:["reasoning.encrypted_content"]`; effective reasoning settings can control its emitted value.
- Responses uses native reasoning fields and does not accept OpenAI thinking fields.
- Anthropic accepts supported native settings. OpenAI-style reasoning effort is rejected.
- The pinned Anthropic adapter has model-specific thinking and temperature restrictions; inspect `model.py` before selecting them.

For a GLM-5.3 profile, supply the endpoint and exact model identifier selected by the maintainer.
This template does not select a production provider or model:

```yaml
llm-url: "<maintainer-supplied provider base URL>"
llm-model: "<maintainer-supplied GLM-5.3 model identifier>"
llm-protocol: openai
llm-thinking: enabled
llm-thinking-clear: "true"
llm-temperature: "1"
llm-top-p: "0.9"
llm-reasoning-effort: max
llm-timeout: "3600"
```

Store credentials in Secrets, not this template or extra-body settings.
The auth-token Secret accepts `<token-1>,<token-2>` for equivalent tokens with the same endpoint and model access.
Selection trims surrounding whitespace, removes empty entries, and rejects embedded whitespace or an empty usable list.
Before Qwen starts, bounded protocol-aware probes try tokens in order.
Authentication, quota, and rate-limit failures cause selection to try the next token.
Transport errors do not establish a usable credential. If no token succeeds, the run fails.
One invocation keeps its selected token. Mid-run exhaustion fails visibly; a later run selects again.
There is no transparent token swap, provider proxy, or multi-session restart.

## Credentials and publication

Use the repository's existing App secrets; no additional App registration or bot-login setting is required.
Trusted credential steps derive `<app-slug>[bot]` from `actions/create-github-app-token@v2`.
Research receives only a repository-scoped token with explicit read-only permissions.
The agent and GitHub MCP never receive the App private key or publication token.
See the action's [App token documentation](https://github.com/actions/create-github-app-token/blob/v2/README.md).

The workflow separates three jobs:

1. Research produces the candidate patch and report under frozen default-branch policy.
2. Validation checks candidate data without model credentials or repository-write credentials.
3. Publication uses a clean runner, rechecks the artifact, and mints its own App write token.

Validation performs deterministic static checks. Repository CI runs the test suite after the proposal PR opens.

Publication verifies that its App slug matches the identity frozen before research.
It applies only the validated patch with hooks disabled; it does not execute an agent worktree or candidate settings.
Allowed paths are selected recipes, related patches, matrix entries, and support prose.
Automation policy, generated catalog metadata, escaping paths, and unsafe symlinks are rejected.
Treat candidate matrix text as data; its presence does not authorize sourcing generated shell.

Keep the original frozen context and checked artifact for a failed-publication retry.
Observe remote branch, commit, and PR state before retrying; adopt matching landed results rather than duplicating them.
Regenerating context is not equivalent to recovering the original publication attempt.
Recovery retains the original artifact and report identity. Fresh checks appear separately as `revalidation` in the publication result.
A changed accepted patch stops publication; newer check evidence does not replace the original report identity.
Secrets must stay out of tracked files, command arguments, reports, logs, caches, and PRs.

## PR commands

A maintainer with repository write permission can post a new comment in the managed PR's Conversation:

```text
/auto-sync
Keep the engine upgrade.
Pin LMCache to 0.5.4 for CUDA/vLLM.
Check its Torch compatibility and update the report.
Keep unrelated component versions unchanged.
```

This is free text, not a separate pin grammar. It can refer to a submitted review or specific inline comments.
Inline comments, ordinary conversation, and bot replies do not independently start revisions.
The controller checks current permission, PR ownership, open state, and the actual head branch and commit.

Every run restores context from the diff, report, reviews, comments, commits, and recorded decisions.
Preserve direct human commits, accepted versions, unaffected changes, and lasting pins.
Explain necessary compatibility expansion. Ambiguous or conflicting requests return `blocked` without waiting for clarification.
Keep lasting constraints beside the version declaration or in this guide, with scope, reason, and reconsideration condition.
Proposal-only decisions stay in the proposal report.

Publication rechecks the PR head and appends commits without force-pushing.
A changed head defers stale output or requires recomputation.
The reply reports addressed and unresolved items, checks, limits, and commit references.
A valid revision without a source patch still reports its outcome and records the processed command.
It leaves the branch head unchanged. Discovery without a patch does not create a PR.
Review-thread resolution belongs to the reviewer.
Comment ID and content digest prevent duplicate publication. Post a new command to change an already processed request.

Discovery and revisions share one repository-wide concurrency group with `queue: max` and `cancel-in-progress: false`.
This queues pending work without canceling an active revision. GitHub's queue has a finite capacity;
see [concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
Identity, structural checks, and commit ancestry do not prove semantic obedience to natural-language requests.
Human review remains required.

## Headless execution and limits

Production execution requires Linux orphan adoption and reaping through the private subreaper supervisor.
Unsupported hosts fail before execution; there is no weaker production fallback.
macOS can run local protocol fixtures with a bounded private test driver.
Those fixtures verify actual requests and instruction loading, not Linux process cleanup.
Linux CI must run the supervisor and fast-orphan checks without skipping them.

Qwen receives task context on finite stdin with EOF. Authentication is configured before startup.
Enabled task tools use automatic approval and finite budgets.
Task context stays out of process arguments. Reject UTF-8 input above the pinned CLI's 8 MiB limit before authentication probes.
Question tools, interactive planning, nested agents, interactive login, and persistent sessions are disabled.
Project instructions, skill discovery, and read-only MCP remain active; safe mode is unsuitable because it disables required customizations.
Candidate settings, environment files, and Git hooks cannot replace the frozen controlling policy.

| Limit | Default |
| --- | --- |
| Unchanged tool failure | At most two retries |
| External command | 300 seconds |
| Qwen session | 180 turns and 180 tool calls |
| Reported token usage | 10,000,000 cumulative input and output tokens |
| Qwen wall time | No separate limit |
| Outer deadline | 55 minutes |
| Actions job | 60 minutes |

The outer deadline takes precedence over a longer model-request timeout.
Qwen has no separate wall-clock budget. The outer deadline leaves time for cleanup and artifact upload before the job limit.
The turn budget matches the tool budget so sequential tool calls can use the available allowance.
Cleanup must adopt, terminate, and reap orphaned descendants. Unconfirmed cleanup remains failed.
Missing configuration, exhausted credentials, upstream timeouts, and commands waiting for input must end within their bounds.
Unresolved decisions go in the job summary or existing PR. A later maintainer command starts a fresh run.

Reserve the final quarter of session turns for edits and complete JSON. Reuse frozen release notes and acquired source trees.
Batch independent reads and manifest queries. Complete independent groups before expanding research.
Record specific missing facts for blocked groups and retain completed groups. Trusted validation runs in its separate job.

Research uses streaming JSON so completed tool events survive an error or exhausted budget.
Live logs show tool activity, brief updates, elapsed time and reported token usage.
Silent periods produce elapsed-time heartbeats. They do not prove model activity.
Thinking, raw tool contents and proposal bodies stay out of live progress logs.
Complete release records remain in acquired files. Research reads them on demand rather than carrying all notes in its initial prompt.
Search the selected recipe, catalog identity and referenced patches. Avoid dumping unrelated records into the conversation.
The token budget counts reported input and output, including cached input once.
Usage arrives after requests, so an in-flight request can exceed the budget. Provider quotas are required for a strict billing limit.
Cached tokens may have different prices; cumulative usage does not establish an invoice amount.
Its artifact contains `diagnostics.json` with one entry per session phase, including each bounded repair session: exit code, timeout flag, elapsed agent time, reported tokens, parsed events, and stderr, plus the total reported tokens.
Model tokens, GitHub tokens, and configured secret header values are redacted before upload.
Inspect this file to locate repeated requests and tool failures. A diagnostic event is not an accepted proposal.
Research failure reasons use structured CLI errors when available. Stderr remains in the diagnostic artifact.
These artifacts follow the workflow's retention policy. Do not cache them or authentication settings.

Actions summaries show the stage outcome, elapsed time, latest discovered versions, candidate outcomes, and PR link.
The tool summary shows the cache outcome and installation time. Full transport JSON remains in artifacts.
A session-wide failure is described once; candidate rows show its affected subscriptions without repeating the traceback.

## Runner and caches

`AUTOSYNC_RUNNER` defaults to `ubuntu-24.04`, a standard GitHub-hosted runner.
Maintainers can select another label, such as the larger `ubuntu-24.04-8x`, when it is available to the repository and a run needs more capacity.
A manual dispatch can select a larger runner profile for one run through its `runner_profile` input.
Labels alone do not establish hardware specifications. Auto-sync uses remote inference and needs no GPU.
An amd64 research runner can inspect arm64 manifests; final-image execution belongs to native Pack runners.
The separately configured verification CI uses Ubuntu 24.04.

`tools/auto_sync/tool-versions.json` owns exact versions and artifact checksums.
The initial pins include Node `24.14.0`, Qwen `0.25.0`, GitHub MCP `2.0.1`, crane `0.21.9`, actionlint `1.7.12`, and uv `0.8.24`.
Repeat affected contract tests when changing pins. A different installed Node version is not evidence for this combination.
Before extraction, validate stripped member and hard-link paths. Resolve symbolic links relative to their stripped member.

The bootstrap cache key binds OS image, CPU architecture, Node/tool versions, and installer definition.
Only an exact, validated installation can skip installation.
The cache stores the installed dedicated tool directories; npm download caching alone does not preserve Qwen.
Python dependency caching also includes the lockfile and Python identity.
Trusted scheduled/manual bootstrap can save verified installations before agent work.
Comment revisions restore caches without saving them.
Do not cache credentials, generated authentication settings, agent sessions, or proposal worktrees.
Query mutable releases and image tags on every run. Caches are not durable workflow state.
Keep cold installation working after missing, invalid, or evicted caches.
Record cache hits and installation, agent, and check durations for runner sizing.
GitHub removes caches after more than seven days without access.
Weekly discovery cannot assume retention; follow [GitHub's cache limits and eviction policy](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy).

## Local verification

Run from the repository root with fake credentials and local endpoints only:

```sh
make prepare
uv sync --locked --all-packages
```

Install pinned tools into a dedicated temporary directory outside the checkout:

```sh
task_tools_root="$(mktemp -d)"
bash tools/auto_sync/bootstrap.sh --prefix "$task_tools_root/tools"
export AUTO_SYNC_TOOL_BIN="$task_tools_root/tools/bin"
uv run pytest tests/auto_sync/test_project_instructions.py
uv run pytest tests/auto_sync
uv run pytest tests/pack
uv run mkdocs build --strict
```

Bootstrap prints its verified tool directory, cache identity, cache-hit result, and duration.
Missing pinned tools must fail required CLI tests instead of skipping them.
For workflow checks, use the compatibility entry point:

```sh
uv run python tools/auto_sync/lint_workflows.py \
  .github/workflows/auto-sync.yml .github/workflows/pack.yml .github/workflows/ci.yml
```

It validates `concurrency.queue` before linting a temporary copy with pinned actionlint.
It preserves unrelated syntax and ShellCheck diagnostics. Raw actionlint `1.7.12` does not understand the queue field.
Use scoped pre-commit hooks while workers share a checkout; fixing hooks can modify files.
At integration, run the full suite and inspect generated changes from Python package builds.
Do not run `make ci` as an opaque proposal check.

## After merge

Maintainers review the proposal, merge it, and run Pack for the combinations listed in its report.
Pack builds native platform images, records output digests, collects installed dependencies, validates manifests, and proposes catalog updates.
It promotes support only when this invocation measures the declared engine/plugin identity across every intended platform.
Partial coverage or missing measurements leaves support `prepared`.
See [Packaging](packaging.md) for the production path and [Support records](support-records.md) for status rules.

Offline static and CLI tests do not verify real provider access, GitHub MCP permissions, or live PR publication.
Those remain commissioning checks. Actual amd64/arm64 final-image collection requires Pack after merge.
GPU inference requires the corresponding hardware and remains separate from support-status promotion.
