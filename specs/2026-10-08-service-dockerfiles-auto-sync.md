# Spec: Service Dockerfiles and Automated Runner Updates

Status: Building
Type: Feature

## Summary

Maintain each inference service in its own Dockerfile.
Collect dependency metadata centrally from final images, separately for each CPU platform.
Add a repository skill and a weekly GitHub workflow that use Qwen Code to research and propose upstream updates.
Support further revisions through commands in the same pull request.
Keep all automation non-interactive and bounded.
Maintainers review the pull request, merge it, and run Pack with the required build resources.

## Motivation

The inspected repository baseline is commit `80034d199fd29b712f68131ab8d0cdddf9646e8a`.

Current packaging has several maintenance problems:

- Six vendor directories contain both combined Dockerfiles and service-specific Dockerfiles.
- CoreX and MUSA still use combined filenames.
- The combined CUDA and CANN files contain VoxBox and MindIE stages that must survive migration.
- Build entry points fall back to combined files.
- Matrix expansion reads Dockerfiles before it filters supported services.
- Dependency collection requires build arguments, shared contexts, and export stages in individual Dockerfiles.
- The dependency export rebuilds a separate target instead of identifying the final runtime image directly.
- Engine upgrades also depend on accelerator plugins, additional packages, source patches, and hardware variants.
- README mixes usage, support tables, and detailed packaging instructions.

The current catalog already contains dependency differences between CPU platforms.
For the CANN 310P vLLM 0.23.0 image, the arm64 row includes packages absent from its amd64 counterpart.
The CUDA vLLM 0.29.0 rows also record different vLLM-Omni versions.
A shared dependency result for an entire manifest would lose these differences.

### Goals

- Give maintainers one active Dockerfile per supported vendor and service.
- Preserve existing services, image behavior, and historical repair operations during migration.
- Report installed package versions from the correct final image and Python environment.
- Preserve the existing public dependency metadata semantics.
- Make upstream research, compatibility analysis, and patch maintenance repeatable.
- Produce formal pull requests with enough evidence for human review before image builds.
- Let maintainers request focused revisions within the existing pull request.
- Run weekly discovery and requested revisions without interactive prompts or indefinite waits.
- Reduce repeated tool installation through GitHub Actions caches.
- Document the project and automation where maintainers and agents can find them.
- Add contribution certification and an adopter registry; update the project copyright year to 2026.

### Non-Goals

- Build inference images, run GPU workloads, or invoke Pack from auto-sync before merge.
- Automatically merge pull requests, publish runner images, or create releases.
- Treat static checks or upstream claims as proof of runtime compatibility.
- Add SGLang support to CoreX without an existing implementation.
- Automatically track new engine releases for vendors outside CUDA, ROCm, and CANN.
- Rewrite historical repair recipes solely to rename their Dockerfiles.
- Upgrade every engine as part of the structural Dockerfile migration.
- Install or run the configured language model locally on the automation runner.

## Proposal

Separate release proposals from image production.

The release workflow researches upstream changes, edits packaging sources, validates its proposal, and opens a formal pull request.
Maintainers can refine that proposal through explicit comments.
After human review and merge, maintainers run Pack.
Pack builds each platform image and collects its actual dependencies before assembling catalog updates.

Use scripts for repeatable checks and workflow control.
Use the release skill for research, compatibility reasoning, and scoped source changes.
The workflow selects the model and supplies credentials before Qwen Code starts.
AGENTS.md defines project behavior and directs the agent to the release skill.

### User Stories

#### Story 1

As an image maintainer, I want a Dockerfile for each inference service.
This lets me update one engine without maintaining a combined recipe.
Build entry points and documentation must use the same layout.

#### Story 2

As a runner metadata consumer, I want dependencies from the final image for my CPU platform.
This lets me distinguish installed packages, absent packages, and images that were never probed.
Active service Dockerfiles must not require probe instrumentation.

#### Story 3

As a release maintainer, I want one repository skill for upstream research and update preparation.
It must evaluate engine versions, plugins, image availability, additional packages, and patches.
It must provide a supported proposal and explain the remaining uncertainty.

#### Story 4

As a repository maintainer, I want weekly update proposals produced with my configured model.
I want to request revisions in the same pull request.
I review and merge the changes before using dedicated resources to build the images.

### Core Features & Acceptance Criteria

#### F1. Service-specific Dockerfiles

The active layout must preserve these services:

| Vendor directory | Required service files |
| --- | --- |
| `cuda` | `Dockerfile.vllm`, `Dockerfile.sglang`, `Dockerfile.voxbox` |
| `rocm` | `Dockerfile.vllm`, `Dockerfile.sglang` |
| `cann` | `Dockerfile.vllm`, `Dockerfile.sglang`, `Dockerfile.mindie` |
| `corex` | `Dockerfile.vllm` |
| `dtk` | `Dockerfile.vllm`, `Dockerfile.sglang` |
| `hggc` | `Dockerfile.vllm`, `Dockerfile.sglang` |
| `maca` | `Dockerfile.vllm`, `Dockerfile.sglang` |
| `musa` | `Dockerfile.vllm`, `Dockerfile.sglang` |

Acceptance criteria:

- Remove the unsuffixed Dockerfile from each active vendor directory after preserving its required behavior.
- Keep existing service-specific recipes as the maintenance source where they already exist.
- Split CoreX and MUSA using the HGGC separation of service recipes as a guide.
- Preserve existing base images, runtime preparation, build arguments, patches, entry points, and supported platforms.
- Do not invent new base-image tags merely to match the HGGC layout.
- Extract CUDA VoxBox and CANN MindIE before removing their combined files.
- Align matrix expansion, Pack, local Make targets, comments, and documentation with the new paths.
- Filter unsupported vendor/service pairs before resolving their Dockerfile.
- Skip unsupported pairs when expanding a broad selection.
- Fail clearly if a supported, selected pair has no required Dockerfile.
- Limit unsuffixed fallback to explicitly selected operations below `pack/.post_operation`.
- Preserve historical operation selection and behavior without automatically rerunning those operations.
- Keep runtime service stages as usable build outputs after removing metadata export stages.

#### F2. Central dependency collection during catalog preparation

The collector belongs to the Pack metadata flow.
It must inspect the final image after all package installation and patch steps.

Acceptance criteria:

- Active Dockerfiles require no dependency-probe build argument, shared context, embedded output file, or export stage.
- Move or reuse the shared probe logic centrally without changing the final image to support collection.
- Do not rebuild an alternative service target merely to obtain dependency metadata.
- Identify every collection result by the final single-platform image digest and full platform.
- Bind internal artifacts to the build invocation and dependency mapping used for collection.
- Define a build invocation by workflow run, source revision, selected matrix, and dependency mapping.
- Record each job attempt and validate partial reruns against that frozen invocation.
- Do not mix results from different platforms, digests, build invocations, or incompatible dependency mappings.
- Carry the Package step digest through collection, manifest assembly, and catalog validation.
- Assemble manifests from digest references and verify their platform descriptors before updating the catalog.
- Inspect each platform independently, including platforms whose package sets appear identical.
- Use an execution environment compatible with the target Linux architecture.
- Do not silently execute an arm64 collector against an amd64 image or substitute another platform's result.
- Read distribution metadata from the Python environment used by the service.
- Respect virtual environments, including the ROCm SGLang environment at `/opt/venv`.
- Do not force system Python when the service uses a virtual environment.
- Avoid importing GPU packages or starting inference merely to read installed distribution versions.
- Preserve original installed version strings, including prerelease and local version identifiers.
- Preserve the ordered distribution aliases in `pack/dependencies.json`.
- Assemble changed catalog rows only after all required collection results are valid.
- Reject missing, malformed, conflicting, stale, or incorrectly identified results.
- Do not copy old dependencies into a replacement image when its new collection failed.
- Keep untouched historical rows unchanged.
- Preserve the existing post-operation rule: update dependencies on one matching existing row without creating a new runner entry.
- Apply centralized collection when historical operations are executed in the future; keep their naming exception.

The public catalog contract remains:

| Value | Meaning |
| --- | --- |
| Missing `dependencies` | Dependencies are unknown because collection has not completed for this image |
| `dependencies: {}` | Collection succeeded; no configured dependency was present |
| Missing package key in a collected result | That package was not installed |
| Present package key | The recorded installed distribution version |

The catalog already distinguishes rows by platform and image name.
Digest provenance may remain in internal artifacts; this feature does not require a public schema expansion.
If collection is intentionally disabled, retain unknown metadata rather than fabricating an empty successful result.

#### F3. Repository release skill

The canonical skill will be `.agents/skills/runner-release-sync/SKILL.md`.
It must support discovery and focused revision of an existing proposal.

The skill must inspect these upstream sources:

| Backend | vLLM source | SGLang source |
| --- | --- | --- |
| CUDA | `vllm-project/vllm` | `sgl-project/sglang` |
| ROCm | `vllm-project/vllm` | `sgl-project/sglang` |
| CANN | Stable vLLM plus `vllm-project/vllm-ascend` | `sgl-project/sglang` and its documented CANN artifacts |

Latest-version detection:

- Maintain explicit subscriptions for the supported upstream/backend combinations in this spec.
- Consider only the newest eligible upstream release for each subscription.
- Exclude draft releases and unrelated release streams.
- Compare normalized release versions under the subscription's stable or Ascend prerelease policy.
- Do not open catch-up proposals for older missing releases.
- Read the default branch's `gpustack_runner/runner.py.json` and README support tables before deciding an update is needed.
- After the documentation split, include the authoritative support tables linked from README.
- Count explicit `prepared` rows on the default branch as represented while Pack is pending.
- Promote a prepared row to `published` only when Pack has verified its declared identity and platform coverage.
- If the latest subscribed version is absent from both sources, mark it as requiring an update proposal.
- A matching entry in either source means that version is already represented; do not open another discovery proposal for it.
- Match structured engine, backend, variant, and version identities rather than arbitrary text occurrences.
- For Ascend, compare the selected stable engine and actual plugin version together.
- A stable engine entry alone does not prove that a particular Ascend prerelease plugin is already represented.
- Treat historical `(rc)` annotations as unknown plugin identity; never infer the missing prerelease suffix.
- Report partial historical identity separately from a failed read or malformed source.
- A failed source read or parse blocks detection; it never proves absence.
- Read the Dockerfiles and matrix to prepare the proposal, but do not use their version pins as a substitute for these detection sources.
- Absence detection identifies required work; compatibility and artifact checks still govern which edits can be proposed as ready.
- If the newest candidate is blocked, report it rather than silently proposing an older release.

Release selection:

- Track stable vLLM and SGLang releases by default, including post releases.
- Treat vLLM-Ascend prereleases as normal plugin candidates for GPUStack Runner.
- Pair each Ascend plugin candidate with the stable vLLM version supported by upstream.
- Preserve the actual Ascend prerelease version instead of relabeling it as an upstream stable release.
- Explain this project policy in README and the release guide.
- Handle other engine prereleases only when a maintainer explicitly requests them.

For every candidate, the skill must:

1. Compare upstream releases with current Dockerfile defaults, matrix overrides, and existing update pull requests.
2. Read release notes, installation guidance, compatibility documentation, and relevant upstream fixes.
3. Identify changes to CPU platforms, accelerator families, runtime versions, image variants, and package requirements.
4. Inspect actual image manifests and configurations with crane or skopeo.
5. Resolve available platform-specific digests and verify the requested artifacts exist.
6. Evaluate additional packages and patches as part of the same version combination.
7. Modify the affected Dockerfiles, matrix entries, patches, and documentation.
8. Run permitted static checks and produce an evidence-based report.

A compatibility row must identify:

- Backend, engine version, accelerator variant, and CPU platform.
- Base-image reference and resolved platform digest.
- Accelerator plugin version, where applicable.
- Python, Torch, accelerator runtime, and additional package versions, where known.
- Patch dispositions and any source-build or disabled-feature decisions.
- Sources supporting the conclusion.
- Whether the conclusion is an upstream statement, a reasoned inference, or unresolved.
- Checks performed and work deferred to Pack.

Unknown fields must remain explicit.
Absence from a release table does not prove that an artifact or platform is unsupported.
Manifest availability does not prove package or hardware compatibility.
Conflicting evidence blocks the affected proposal until it can be resolved.

Additional packages include Mooncake, LMCache, LMCache-Ascend, Diffusers, and applicable Omni packages.
Their versions must follow the selected engine and runtime combination.
Do not select the newest additional package solely because it has a higher version number.

Preserve existing cross-image constraints, including LMCache protocol compatibility where the recipes require it.
Keep dependent updates in one reviewable change group.
Allow independent groups to proceed while blocked groups remain unchanged.

Every affected patch needs one disposition: retain, adapt, remove, or add.
Record the reason, applicable versions and platforms, and available upstream issue or commit evidence.
Check application against the selected source revision when that source is available.
Report unavailable source checks as unverified.
Successful patch application is not runtime validation.

#### F4. Weekly auto-sync workflow

Add an auto-sync workflow with scheduled discovery, manual invocation, and pull-request revision entry points.

Acceptance criteria:

- Schedule discovery once per week.
- Use Monday at 01:23 UTC as the default, equivalent to 09:23 in Asia/Shanghai.
- Keep manual invocation and authorized comment commands available between scheduled runs.
- Run the scheduled controller from the default branch.
- Pin the installed Qwen Code release and supporting tool versions.
- Configure the selected model, AGENTS.md context, repository skill discovery, and GitHub MCP before starting the agent.
- Use GitHub MCP for read-only repository research.
- Keep branch publication and pull-request creation in workflow-controlled steps.
- Reuse the repository's GitHub App authentication pattern for pull-request writes.
- Create formal, non-draft pull requests for valid proposals.
- Require human review and merge before Pack is invoked.
- Do not invoke Pack, build service images, publish images, or populate guessed catalog dependencies in auto-sync.
- Do not open an empty pull request when no update is needed.
- Keep at most one open auto-sync upgrade pull request for the repository.
- Use a stable automation identity that does not include the proposed release version.
- Inspect open pull requests before creation, including proposals for an earlier upstream release.
- Reuse the existing proposal or report a deferral while it remains open; never create a second proposal.
- A new upstream version does not bypass this rule.
- Group changes according to compatibility dependencies within that proposal.
- Scheduled discovery must not rewrite any open auto-sync proposal, including proposals without human review.
- Report newer targets in the job summary while a proposal remains open.
- Require an authorized `/auto-sync` command to revise or refresh an existing proposal.
- Do not create duplicate pull requests on repeated discovery or concurrent invocations.
- Recheck for an existing proposal immediately before creation.
- Preserve human reviews and direct human commits when processing an authorized revision.
- Record newly discovered upstream information without replacing the pending proposal.
- An unmerged reviewed proposal remains pending; its age does not authorize another pull request.
- Never classify a failed upstream query as a successful no-update result.

Each pull request must include:

- Proposed old and new versions and the affected combinations.
- Relevant release-note changes and source links.
- Base-image and platform evidence.
- Additional package and patch decisions.
- The compatibility matrix and its evidence classifications.
- Executed checks, failures, and unresolved limitations.
- The combinations maintainers should build after merge.

Only publish change groups whose required static checks passed.
Report skipped or blocked groups explicitly.
A report must distinguish proposed configuration from measured runtime metadata.
Do not advertise a candidate image as already built or published.

#### F5. Model configuration contract

Follow the parameter conventions of the organization's existing code-review integration.
The contract below is self-contained and does not depend on that integration's source tree.

| Input | Contract |
| --- | --- |
| `llm-url` | Required provider base URL; normalize it for the selected protocol without duplicating API path segments |
| `llm-model` | Required provider model identifier; no hardcoded provider or implicit model fallback |
| `llm-protocol` | Optional explicit `openai`, `openai-responses`, or `anthropic`; overrides the legacy selector |
| `llm-use-anthropic` | Legacy string selector; default `false`; documented true values select Anthropic when no explicit protocol exists |
| `llm-thinking` | Provider thinking setting, `enabled` or `disabled`; default `disabled` for the OpenAI-compatible GLM profile |
| `llm-thinking-clear` | Provider-specific boolean string; default `false` for the OpenAI-compatible GLM profile |
| `llm-temperature` | Optional validated numeric value; compatible profile default `0.4` |
| `llm-top-p` | Optional validated numeric value; compatible profile default `0.9` |
| `llm-reasoning-effort` | Empty by default; otherwise `minimal`, `low`, `medium`, `high`, or `max` |
| `llm-timeout` | Positive request timeout in seconds; default `3600`; separate from command and total-run deadlines |
| `llm-auth-header` | Optional custom authentication header |
| `llm-extra-headers` | Optional additional headers, following the documented `K=V,K=V` input convention |
| `llm-extra-body` | Optional JSON object for provider-specific request fields |
| `llm-auth-token` | Required secret; a single token or a comma-separated list of equivalent tokens |

Provide a reusable invocation interface using these names.
Scheduled and manual runs must resolve the same settings from repository or organization variables and secrets.
Document a GLM-5.3 example with a maintainer-supplied endpoint and model identifier.

Configuration requirements:

- Normalize protocol and selector values without case sensitivity.
- For the legacy selector, accept `true`, `1`, and `yes` as true.
- Accept `false`, `0`, `no`, and an omitted or empty value as false.
- Reject other legacy selector values when no explicit protocol overrides them.
- Validate types, numeric ranges, protocol values, and JSON before model execution.
- Apply explicit extra-body fields over corresponding convenience settings.
- An explicit extra-body `reasoning_effort` takes precedence over the named effort input.
- Do not let extra-body fields override credentials, the selected model, conversation messages, or tool control.
- Merge effective parameters before adapting them to the selected protocol.
- Apply GLM-compatible thinking defaults only to OpenAI-compatible requests.
- Do not inject those defaults into Anthropic or Responses requests.
- Adapt explicitly supplied request fields or reject unsupported combinations.
- Do not forward OpenAI-style reasoning effort or provider-specific thinking defaults blindly to Anthropic.
- Reject explicitly unsupported combinations instead of silently dropping requested settings.
- Convert timeout units correctly for the selected Qwen provider configuration.
- Confirm the actual emitted request contains the intended model settings.
- Trim surrounding whitespace from comma-separated tokens and discard empty entries.
- Reject embedded token whitespace and an empty usable-token list.
- If multiple equivalent tokens are supplied, use bounded, protocol-aware selection.
- Fail if no token succeeds; do not select a token merely because a transport request failed.
- Mask each token and treat transport failure as failure, not evidence of a usable credential.
- Do not fall back to an interactive login or an unconfigured model.
- Keep secrets out of tracked files, command arguments, reports, logs, caches, and pull requests.

AGENTS.md must explain that the workflow selects the model.
The agent must not launch another agent instance merely to switch providers.
Model configuration and project instructions have separate responsibilities.

#### F6. Revisions inside an existing pull request

A maintainer can write a command in the pull request's Conversation:

```text
/auto-sync
Keep the engine upgrade.
Pin LMCache to 0.5.4 for CUDA/vLLM.
Check its Torch compatibility and update the report.
Keep unrelated component versions unchanged.
```

The command may also refer to the maintainer's submitted review or specific inline comments.
Inline comments do not independently start a model run.
Ordinary conversation and bot replies must not trigger revisions.

Acceptance criteria:

- Accept commands only from maintainers with repository write permission.
- Verify the pull request is open and managed by this repository's auto-sync workflow.
- Resolve its actual head branch and commit; the comment event's default-branch SHA is not the proposal head.
- Restore context from the current diff, report, reviews, comments, and recorded decisions.
- Do not depend on cached Qwen sessions.
- Apply only the requested revisions and necessary compatibility changes.
- Preserve accepted versions, unaffected changes, and direct human commits.
- Explain any necessary expansion caused by a shared compatibility constraint.
- Report conflicting or ambiguous requests without guessing the required version.
- Append commits to the existing branch and update its report.
- Reply with addressed items, unresolved items, checks, and commit references.
- Leave review-thread resolution to the reviewer.
- Serialize proposal creation and updates across discovery and revision runs.
- Use one repository-wide concurrency group with `queue: max` and `cancel-in-progress: false`.
- Do not cancel an active revision merely because weekly discovery starts.
- Recheck the PR head before publication.
- If the head changed, discard stale output or recompute against the new head.
- Do not force-push over concurrent human work.
- Make repeated delivery of the same command idempotent using its comment ID and content digest.
- Trigger on newly created commands; require a new comment to change an already processed request.

Persist lasting version constraints beside the relevant version declaration or in the release guide.
Record their scope, reason, and condition for reconsideration.
Keep decisions limited to one proposal in that proposal's report.
Do not turn a temporary version choice into an unexplained permanent ban.

#### F7. Non-interactive execution and bounded completion

Non-interactive behavior is REQUIRED for both discovery and revision.
The release skill must not invoke another workflow that waits for user confirmation.

Acceptance criteria:

- Use a single-run headless Qwen invocation without a terminal interface.
- Supply model authentication and MCP configuration before startup.
- Automatically approve the tools enabled for the authorized task in the ephemeral runner.
- Disable question tools and transitions into interactive planning.
- Preserve AGENTS.md, skill, and MCP loading while disabling interactive behavior.
- Do not use Qwen safe mode as a shortcut, because it disables required project customizations.
- Close standard input after supplying the task.
- Disable interactive Git, package-manager, installer, credential, and editor prompts.
- Treat missing credentials or configuration as an immediate configuration failure.
- Keep the agent's available credentials and tools within the proposal task.
- Reserve remote repository writes to a separate publication job on a clean runner.
- Run candidate validation without model credentials or repository-write credentials.
- Load controlling code and agent policy from one frozen default-branch revision.
- Prevent candidate settings, environment files, and Git hooks from overriding that policy.
- Set finite limits for model requests, external commands, retries, tool calls, session turns, and agent wall time.
- Add an outer process deadline that can terminate stuck child processes.
- Set the Actions job deadline later than the agent deadline to allow result collection.
- Stop retrying unchanged failures after the configured limit.
- Continue independent work when one candidate is blocked.
- Record missing information and exit instead of waiting for a human reply.

Each candidate must produce one assessment:

| Assessment | Meaning |
| --- | --- |
| `ready` | A proposal is complete and its required static checks passed |
| `unchanged` | Successful inspection found no applicable change |
| `blocked` | A required decision or compatibility fact remains unresolved |
| `failed` | A tool, configuration, deadline, or output contract failed |

The workflow must validate the structured assessment before publication.
A question without the required assessment is incomplete output.
Process exit alone is not proof that the task completed.
Any timeout or incomplete result must remain visible as a failure.
A mixed run must preserve the outcomes of all candidates instead of reporting universal success.

Publish unresolved decisions in an existing pull request or the job summary.
A later maintainer command starts a new run.
Do not keep a job alive while waiting for review.

Acceptance must include missing credentials, ambiguous feedback, a command waiting for input, and an upstream timeout.
Each case must terminate within its configured bound and report the correct outcome.
Also verify that the headless run actually loads the project instructions and release skill.

#### F8. Runner and cache behavior

Use `ubuntu-22.04` as the default runner.
Allow maintainers to select a runner through `AUTO_SYNC_RUNNER`.
Support the supplied `ubuntu-22.04-4x` and `ubuntu-22.04-8x` labels when the repository can access them.

This task uses remote model inference and static repository checks.
It does not require a GPU or one automation runner per target CPU architecture.
Inspecting an arm64 manifest from an amd64 runner is permitted.
Executing final-image dependency collection remains a separate Pack responsibility.

Production agent execution requires Linux process supervision that can adopt and reap orphaned descendants.
Unsupported hosts must fail before production execution; do not provide a weaker production fallback.
macOS can run Qwen Code, but is not a required automation platform for this feature.
Local protocol fixtures may replace the private execution boundary with a bounded test driver.
Those fixtures verify requests and instruction loading, not Linux process cleanup.
Ubuntu CI must execute the supervisor and fast-orphan regression tests without skipping them.
The custom 4x and 8x labels do not imply specific hardware specifications.
Use actual organization configuration when comparing those machines.

Cache requirements:

- Use a shared bootstrap path for scheduled, manual, and revision runs.
- Select Node 24 and a pinned Qwen release whose contract tests pass.
- Record exact tool versions and artifact checksums in the shared bootstrap manifest.
- Prefer runner-provided tools and fixed-version precompiled binaries where suitable.
- Cache the dedicated Qwen installation and supporting tool directories with Actions cache.
- Key installed-tool caches by operating system image, CPU architecture, Node version, tool versions, and installer definition.
- Skip installation only after an exact cache match and tool validation.
- Do not assume npm download caching preserves the installed Qwen program.
- Use the existing uv setup pattern for Python dependency caching, including the lockfile and Python identity.
- Let trusted scheduled or manual bootstrap steps establish caches.
- Use restore-only caching for comment-triggered revisions.
- Save only verified tool installations, before agent work can alter them.
- Do not cache credentials, generated authentication settings, agent sessions, or proposal worktrees.
- Query mutable upstream releases and image tags again on each run.
- Preserve a complete installation path when caches are absent, evicted, or invalid.
- Do not use cache contents as durable workflow state.
- Record cache hits and installation, agent, and check durations for later runner sizing.

GitHub removes caches that have not been accessed for more than seven days.
Weekly discovery therefore cannot depend on guaranteed cache retention.
Do not add more frequent release discovery just to keep installation caches alive.

#### F9. Project instructions and documentation

Acceptance criteria:

- Add a concise project-specific AGENTS.md.
- Include source navigation, evidence rules, coding conventions, and behavior-focused verification.
- Keep contributor sign-off instructions beside the project commands.
- Describe repository purpose, important paths, commands, Dockerfile ownership, metadata semantics, and patch rules.
- Document the auto-sync scope and its non-interactive behavior.
- Direct Qwen to the canonical release skill and the model already configured by the workflow.
- Keep skill content under `.agents/skills`.
- Add the relative symlink `.claude/skills -> ../.agents/skills`.
- Preserve existing local content below `.claude`.
- Narrow the ignore rules enough to track the skill symlink while keeping local specs and worktrees ignored.
- Keep README focused on overview, quick usage, documentation entry points, and essential compatibility caveats.
- Retain a brief explanation of Ascend prerelease plugin policy in README.
- Move detailed support tables, packaging rules, dependency metadata, and release automation guidance into `docs`.
- Add these guides to MkDocs navigation without removing API documentation.
- Keep links valid and avoid duplicated authoritative version tables.
- Distinguish `prepared` support from images that have actually been built and `published`.
- Keep engine and actual Ascend plugin versions explicit in new support records.
- Document weekly discovery, cache behavior, model settings, PR commands, and post-merge Pack responsibilities.
- Do not require personal machine paths, private notes, or off-repository skills to understand or run the workflow.

#### F10. Contribution and adoption files

- Add the unmodified Developer Certificate of Origin 1.1 as `DCO`.
- Add an empty `ADOPTERS.md` table with instructions for companies and projects to submit entries.
- Do not infer adoption or copy another project's adopters.
- Update the GPUStack copyright line in `LICENSE` to 2026.
- Preserve the Apache license terms and their original version date.
- Document signed-off commits; repository files do not prove that the organization DCO app is enabled.

### Notes / Constraints / Caveats

#### Repository constraints

The project uses Python 3.10 or later, uv, Bash, jq, yq, Docker Buildx, and GitHub Actions.
Its existing CI exercises Python 3.10, 3.11, and 3.12.
Maintain that supported language floor unless a separate change authorizes otherwise.

`pack/expand_matrix.sh`, `pack/merge_runner.sh`, `pack/matrix.yaml`, and `pack/dependencies.json` form the current packaging contract.
`.github/workflows/pack.yml` owns image production and catalog-update orchestration.
`gpustack_runner/runner.py` and `gpustack_runner/runner.py.json` expose runner metadata.

Current tests include `tests/pack/test_probe_wiring.py`, `tests/pack/test_merge_runner.py`, and `tests/pack/test_dependencies.py`.
Some wiring assertions describe the intrusive probe design.
Replace those assertions with the new contract while preserving meaningful behavior coverage.

The existing probe can force system Python even when the service uses a virtual environment.
The current merge path can retain previous dependencies when new metadata is missing.
Both behaviors require attention for changed images under F2.

Some historical operation recipes also mount the existing shared probe.
Keep the shared helper and named context available only for those explicitly selected historical builds.
Central collection remains authoritative when those operations run again.
Do not delete the helper solely because active recipes no longer call it.

Current CI path filters ignore tools, documentation, and Markdown files.
Update those filters so changes to automation and instructions receive their required checks.

The Makefile lint target can modify files through formatter and linter fixes.
Dependency setup can also regenerate version metadata or update the lockfile.
Automation must inspect these changes before proposing a commit.

#### Upstream evidence informing the design

These examples explain required checks.
They are not instructions to upgrade to these specific versions.

| Source | Relevant finding and limit |
| --- | --- |
| [vLLM v0.31.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.31.0) | CUDA and ROCm artifacts have distinct image variants. Inspect each requested artifact and platform. |
| [vLLM-Ascend v0.27.1rc1 release](https://github.com/vllm-project/vllm-ascend/releases/tag/v0.27.1rc1) | The prerelease plugin pairs with stable vLLM 0.27.1. Validation scope varies by model and accelerator. |
| [SGLang v0.5.21 release](https://github.com/sgl-project/sglang/releases/tag/v0.5.21) | ROCm artifacts distinguish accelerator families. Release-note image lists alone do not settle CANN availability. |
| [LMCache compatibility guidance](https://github.com/LMCache/LMCache/blob/1a1828cad4e9bde3740add51c7cb259c48bff56e/docs/source/getting_started/compatibility.rst) | Binary dependencies, engine connector interfaces, and feature support are separate compatibility concerns. |
| [LMCache-Ascend matrix](https://github.com/LMCache/LMCache-Ascend/blob/19c13d849d6bcdea6316cdd8674fae210b3326f4/README.md#compatibility-matrix) | Documented combinations can lag newer engine releases. A missing row is an evidence gap, not proof of incompatibility. |
| [vLLM-Omni installation guidance](https://github.com/vllm-project/vllm-omni/blob/8894dd46f3d0983585c51a0c18467b4b1e232f59/docs/getting_started/installation/README.md) | Released Omni packages target corresponding vLLM release lines. Check the selected pair explicitly. |

Read-only registry inspection confirmed multi-platform CUDA and Ascend examples.
Inspected ROCm examples exposed only linux/amd64.
These observations came from manifests and image configurations.
No image layers were executed, and no installed dependency or GPU compatibility was measured during specification research.

Qwen Code 0.25.0 was used to inspect available command-line options.
Its help exposes headless execution, approval modes, model configuration, and finite execution budgets.
That inspection is not an end-to-end automation test.
The implementation must validate the chosen pinned release with the actual workflow contract.

Pinned Qwen source uses different parameter merge orders for Chat and Responses.
Chat applies extra-body fields after convenience fields.
Responses can keep an existing convenience field when the same extra-body field is present.
Normalize the effective values before provider mapping, then test requests emitted by the actual CLI.
See the pinned [Chat provider](https://github.com/QwenLM/qwen-code/blob/6788c035698a0ada471c958d1e789e96c6cddd9b/packages/core/src/core/openaiContentGenerator/provider/default.ts#L237)
and [Responses pipeline](https://github.com/QwenLM/qwen-code/blob/6788c035698a0ada471c958d1e789e96c6cddd9b/packages/core/src/core/openaiResponsesContentGenerator/responses-pipeline.ts#L473).

Relevant platform contracts:

- [Qwen headless execution](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) describes output and execution budgets.
- [Qwen settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/) covers context files and tool configuration.
- [GitHub schedule events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) run from the default branch and can be delayed.
- [GitHub comment events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment) require explicit PR context resolution.
- [Actions caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) defines branch scope, retention, and restore-only use.
- [setup-node caching](https://github.com/actions/setup-node#caching-global-packages-data) caches package downloads rather than installed node_modules.
- [Actions concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) supports `queue: max` for pending runs without canceling the running task.

### Boundaries

- Always: preserve existing supported services and explicit historical naming exceptions.
- Always: separate upstream statements, analysis, successful checks, and unverified runtime behavior.
- Always: keep actual dependency collection tied to the final platform image.
- Always: honor maintainer feedback within its stated scope and preserve direct human work.
- Always: terminate unattended work with a complete result or an explicit failure.
- Ask first: obtain human review through the pull request before merging or publishing an upgrade.
- Ask first: report unresolved scope or compatibility decisions and end the affected task; resume only on a new maintainer instruction.
- Never: wait inside a running CI job for interactive approval, login, review, or clarification.
- Never: run Pack, build service images, auto-merge, or publish images from auto-sync.
- Never: fabricate package versions, infer cross-platform equality, or label static analysis as runtime validation.
- Never: let an upgrade agent rewrite its own controlling workflow, skill, or instruction policy as part of a dependency update.
- Never: expose credentials or execute comment text as shell code.

Changes to the automation policy itself remain ordinary maintainer-reviewed repository changes.
Support removals may be proposed when upstream evidence requires them.
They must be visible in the compatibility report and reviewed before merge.

### Risks and Mitigations

- Unique stages can be lost during file removal → Extract VoxBox and MindIE before deleting combined recipes.
- Strict selection can break broad expansion → Filter supported pairs before resolving their files.
- Tags can move between collection and publication → Use build-output digests through manifest assembly and descriptor validation.
- Partial reruns can mix results → Match the frozen invocation and replace only the selected job's receipt.
- Virtual environments can hide packages → Select the service interpreter centrally and reject ambiguous environments.
- Historical operations still mount the probe → Retain their helper and scoped context while using central results for catalog updates.
- Additional packages can lack compatibility evidence → Report the gap and leave the affected change group blocked.
- Patches can apply yet remain incorrect → Separate source applicability from deferred runtime validation.
- Protocol adapters can ignore or replace model settings → Normalize parameters and capture actual requests in contract tests.
- Candidate configuration can override agent policy → Load trusted policy from the default branch and suppress candidate configuration.
- Agent processes can outlive their work → Use an outer process deadline and a separate clean publication runner.
- Model output can appear complete without valid changes → Validate assessments, patch scope, and deterministic checks before publication.
- Human review can start without changing the PR head → Weekly discovery never rewrites an existing proposal.
- Human and automated commits can race → Recheck the head and use fast-forward publication without force-push.
- Retries can create duplicate PRs or revisions → Use a stable proposal identity and persist processed command identity in PR history.
- Weekly caches can expire → Keep fixed-version cold installation working and validate restored tools.
- Documentation can claim unavailable images → Keep prepared status explicit and promote only measured platform coverage.
- Existing CI filters can skip new automation → Include tools, skills, instructions, and related documentation in validation triggers.

## Design Details

### Commands

The maintainer confirmed local macOS static checks and offline tests, followed by Ubuntu 22.04 CI.
Use the local shell for development and GitHub Actions for Linux validation.
Keep the current Python 3.10, 3.11, and 3.12 CI coverage.
The Qwen contract job uses the pinned Node 24 installation.
Do not infer its behavior from a different Node version already installed on the workstation.

These commands are validation requirements, not evidence that they have already passed.
Run them from the repository root.
Install locked dependencies first.
Each task lists its focused tests; run the broader suite at the integration checkpoints.

| Command | Purpose and constraint |
| --- | --- |
| `uv sync --locked --all-packages` | Install locked dependencies without updating the lockfile |
| `bash tools/auto_sync/bootstrap.sh` | Proposed T1 entry point; install and verify tools in a dedicated temporary prefix |
| `uv run pytest tests/pack` | Exercise Dockerfile selection, collection, and catalog behavior |
| `uv run pytest tests/auto_sync` | Exercise model, discovery, proposal, publication, and workflow contracts |
| `uv run pytest` | Run the complete project suite at integration checkpoints |
| `uv run pre-commit run --all-files --show-diff-on-failure` | Run repository checks; inspect changes from fixing hooks |
| `uv run mkdocs build --strict` | Build and validate documentation |
| `actionlint .github/workflows/auto-sync.yml .github/workflows/pack.yml .github/workflows/ci.yml` | Validate affected workflows with configured custom runner labels |
| `make build` | Build the Python distribution; inspect generated version metadata |
| `make package` | Local image packaging; excluded from auto-sync and pre-merge verification |

The proposed bootstrap command must expose its dedicated tool directory to subsequent commands.
Use it before tests that invoke Qwen or supporting binaries.
A required CLI contract test must fail clearly when its pinned tool is unavailable.
Do not count a skipped CLI test as acceptance.

Do not use `make ci` as an opaque auto-sync check.
It includes dependency setup, hook installation, cleanup, and package generation.
Use trusted validation code and inspect any generated changes.

Local and CI tests use fake credentials and local model endpoints.
They must not invoke paid model APIs, create real pull requests, build service images, or run Pack.
Actual provider access and native image collection remain post-merge commissioning checks.

Baseline validation found six warnings in the strict documentation build.
Three filter-method docstrings omit parameter types.
Three image-format examples are parsed as unresolved Markdown links.
T12 fixes these documentation defects without changing public function behavior or suppressing warnings.
Baseline actionlint also reports 18 ShellCheck findings in Pack metadata and manifest scripts.
T7 corrects the affected variable quoting and grouped output redirection as it changes those steps.

### Project Structure

Existing paths affected by the feature:

```text
.github/workflows/pack.yml       Image builds, dependency collection, catalog updates
Makefile                        Local packaging selection and documented commands
pack/matrix.yaml                Supported combinations and build overrides
pack/expand_matrix.sh           Matrix selection and Dockerfile resolution
pack/merge_runner.sh            Dependency folding and catalog assembly
pack/dependencies.json          Public dependency names and ordered package aliases
pack/shared/probe_dependencies.sh
                                Existing collection logic to centralize
pack/<vendor>/                  Active service recipes and patches
pack/.post_operation/           Historical operations with scoped naming compatibility
gpustack_runner/runner.py        Public dependency semantics
gpustack_runner/runner.py.json   Generated runner catalog
tests/pack/                     Packaging and metadata behavior checks
.github/workflows/ci.yml         Existing validation matrix and path filters
pyproject.toml                  Python compatibility and development dependencies
README.md                       Project overview and quick entry points
mkdocs.yml                      Documentation navigation
.gitignore                      Local agent files and the tracked skill symlink
```

Proposed additions and documentation destinations:

```text
AGENTS.md
.agents/skills/runner-release-sync/SKILL.md
.claude/skills -> ../.agents/skills
.github/workflows/auto-sync.yml
docs/supported-runners.md
docs/packaging.md
docs/dependency-metadata.md
docs/release-automation.md
pack/resolve_dockerfile.sh       Shared selector for active and historical recipes
pack/probe_dependencies.py       Standard-library metadata reader run by service Python
pack/collect_dependencies.py     Image execution and receipt validation
tools/auto_sync/bootstrap.sh     Dedicated, fixed-version tool installation
tools/auto_sync/tool-versions.json
                                Tool versions and artifact checksums
tools/auto_sync/model.py         Input normalization and protocol mapping
tools/auto_sync/agent.py         Headless invocation and process limits
tools/auto_sync/discovery.py     Latest-only selection and dual-source detection
tools/auto_sync/proposal.py      Structured proposal and patch validation
tools/auto_sync/checks.py        Trusted, credential-free candidate checks
tools/auto_sync/publish.py       Single-PR control and focused revision publication
tools/auto_sync/run.py           Workflow entry-point orchestration
tests/auto_sync/                 Offline automation tests and fixtures
.github/actionlint.yaml         Declared custom runner labels
```

The additions above are proposed implementation paths, not claims that these files already exist.
Keep supporting scripts under their owning packaging or automation directory.
Keep the skill as the single source of release instructions.
Do not introduce a second editable copy below `.claude`.

### Code Style

Preserve the existing typed dataclass contract in `gpustack_runner/runner.py`:

```python
dependencies: dict[str, str] | None = field(
    default=None,
    metadata={"dataclasses_json": {"exclude": lambda v: v is None}},
)
```

This omission behavior is part of the public metadata semantics.
Do not replace unknown dependencies with an empty dictionary.

Follow existing Python formatting and pre-commit conventions.
Keep shell scripts compatible with Bash.
Use structured JSON and YAML serialization instead of interpolating untrusted text into shell programs.
Use argument arrays for new subprocess calls; do not execute comment text or generated configuration as shell code.
Keep automation helpers outside the public runner API.
Render complete candidate metadata before replacing output files.
Keep temporary files, mock credentials, and generated agent settings outside tracked paths.
Write concise English repository documentation.
Keep compatibility reasons beside the relevant version or patch.
Use finite, explicit failure paths rather than interactive recovery.

### Execution Contracts

#### Final-image collection and catalog updates

Use a Python standard-library probe based on `importlib.metadata`.
Send it to the selected service interpreter in the final image.
Override the image entrypoint so metadata inspection does not start inference.
Use the image's virtual environment and PATH, including the known ROCm SGLang environment.
An ambiguous or unavailable interpreter is a collection failure.
Do not install packages or import GPU modules to make the probe work.

Run the collector on the native Linux runner already selected by Pack for that CPU architecture.
Set an execution timeout and keep temporary probe data outside the final image.
Mock image execution in pre-merge tests.
Do not treat temporary Python-environment tests as proof that a service image runs.

Capture the digest from the successful Package step.
The trusted collector uses that digest rather than resolving a mutable platform tag.
Each internal receipt records:

- Workflow run and source revision.
- Selected matrix identity and dependency-mapping content digest.
- Build job and attempt.
- Backend, service, image identity, full platform, and final image digest.
- Successful raw distribution versions or an explicit collection failure.

Freeze the source revision, selected matrix, and mapping for a workflow invocation.
Record attempts separately.
A partial rerun may reuse a successful job only within that same frozen invocation.
A replacement job result supersedes the prior receipt for its expected identity.
Reject conflicting duplicates and unexpected receipts.

The expected platform set comes from the selected build matrix.
Build output supplies digest authority; a receipt's own digest is not independent proof.
Assemble manifests from `repository@digest` references.
Verify published manifest descriptors against the expected platform receipts before catalog assembly.
A moved platform tag must not change the selected child image.

Serialize Pack publication for overlapping image names through manifest and catalog preparation.
If the published tag no longer resolves to the validated manifest, fail that publication attempt.
An independently changed external registry tag cannot be prevented by local validation.

Validate the complete expected collection set before changing catalog rows.
Generate the catalog and related fixture outputs from that validated set.
On validation failure, leave existing outputs unchanged.
Preserve ordered alias selection and original installed version strings.
Keep public dependency omission semantics unchanged.
Post operations still update exactly one existing matching row.

Historical recipes retain their filename exception.
Some also need the existing shared probe mount to remain buildable.
Keep that helper and context scoped to explicit historical operations.
Their embedded output is not an authority for new catalog updates.

#### Detection identity and support status

Keep one authoritative support document at `docs/supported-runners.md`, linked from README.
Preserve existing support information during migration.
New records state backend, runtime line, service, accelerator variant, engine version, and plugin version where applicable.
List the intended CPU platforms separately.

Use canonical variant identities from the packaging matrix.
Normalize documented aliases explicitly, such as CANN 950 and A5.
Do not infer hardware aliases from similar names.
Keep the selected stable engine and actual Ascend plugin version as a pair.

A candidate has an exact match, no exact match, or insufficient historical identity.
Historical engine-only `(rc)` text has insufficient plugin identity.
It does not match a particular plugin prerelease.
Report that limitation without inventing the missing version.
A failed read or malformed source is an inspection failure, not a missing version.

An exact match in either the catalog or authoritative support records prevents another discovery proposal.
A `prepared` record counts only after its proposal has merged into the default branch.
It means configuration was prepared; it does not claim an image exists.
Pack promotes that record to `published` only when measured results cover its declared identity and platforms.
Do not publish guessed package versions while preparing the upgrade.

Read only the newest eligible release for each of the six backend/service subscriptions.
If that candidate is blocked, report the blocker.
Do not fall back to an older missing release.

#### Model adapter and tool bootstrap

Use these initial pins:

| Tool | Version |
| --- | --- |
| Node | `24.14.0` |
| Qwen Code | `0.25.0` |
| GitHub MCP Server | `2.0.1` |
| crane | `0.21.9` |
| actionlint | `1.7.12` |
| uv | `0.8.24`, matching the repository setup |

These are implementation inputs, not a claim that the combination has passed contract tests.
Record installation artifacts and checksums in `tools/auto_sync/tool-versions.json`.
T1 must validate the combination before dependent work relies on it.
Changing a tool pin requires repeating its affected contract tests.
Use runner-provided Git, Bash, jq, and yq only after checking the required interfaces.

Prefer the GitHub MCP native stdio binary.
Supply its token before startup and expose only research tools.
Do not start an OAuth browser flow in Actions.
Use a dedicated temporary configuration directory.
Point Qwen at the trusted project instructions and canonical skill.

Normalize model inputs into one effective request configuration.
Apply explicit extra-body fields over convenience fields before protocol mapping.
Preserve selected model, conversation, credentials, and tool-control fields.
The GLM-compatible defaults apply only to OpenAI-compatible requests.
Anthropic and Responses receive supported native fields or a configuration error.
Do not add a provider proxy or silently weaken the requested settings.

Interpret the authentication secret as one token or a comma-separated list.
Trim surrounding whitespace, discard empty entries, and reject embedded whitespace.
Mask each usable token.
Use bounded, protocol-aware selection.
No successful response means authentication selection failed.
A transport error does not qualify a token.

Test all three protocols with the actual pinned CLI and fake credentials.
Capture at least two request turns through local endpoints.
Check effective values, custom headers, normalized paths, timeout units, and unsupported combinations.
A generated settings file alone is not enough evidence.
T1 uses fixture instructions, a fixture skill, and a local MCP fixture because the canonical project files arrive in T12.
T12 and T13 repeat discovery checks against the actual project instructions and release skill.

Install tools into a dedicated directory without credentials.
Validate exact restored versions before skipping installation.
Save caches before agent work starts.
Comment-triggered revisions restore caches but do not save them.
Cold installation must remain complete and bounded.

#### Workflow boundaries and publication

Use three jobs:

1. Research and proposal: resolve current state, configure Qwen, and produce a candidate patch and structured report.
2. Validation: check candidate data without model credentials or repository-write credentials.
3. Publication: use a clean runner to verify the result and publish the authorized branch and PR changes.

Freeze one default-branch revision for controller code, bootstrap, validators, AGENTS.md, and the release skill.
For revisions, resolve the PR head separately and bind the candidate to that head.
Do not execute candidate project settings, environment files, hooks, or shell fragments as controlling code.
The existing matrix expansion can source generated shell.
Therefore, reading candidate matrix data is not equivalent to safely executing it.
Use trusted parsing and validation for candidate data.

The candidate artifact contains an allowed-path patch and a structured report.
Bind it to repository, default revision, selected PR/head, mode, and command identity where applicable.
Allow dependency updates only in the selected recipes, matrix, relevant patches, and support documentation.
Reject automation-policy edits, generated catalog metadata, escaping paths, and symlinks outside the checkout.
Validate these constraints before issuing write credentials.

Do not pass an agent worktree or executable artifact to the publication job.
Apply the validated patch to a clean checkout with hooks disabled.
Create the GitHub App write token only in that job.
Use the repository's existing App credential pattern.
Never expose that token to the agent.

Use one stable auto-sync PR identity across release versions.
Schedule and manual discovery both defer source changes while that proposal remains open.
Keep newer findings in the job summary.
An authorized `/auto-sync` command starts a focused revision against the current PR head.
Append commits without replacing human commits or accepted constraints.

Serialize runs with one repository-wide concurrency group.
Set `queue: max` and `cancel-in-progress: false`.
Recheck PR ownership, open state, head, and command state before publication.
A stale head requires recomputation or an explicit deferred result.
Never force-push.

Persist processed command identity in PR history and commit metadata.
Use the original comment ID and content digest.
An edited command does not silently authorize another revision; require a new comment.
On retry, inspect whether the branch commit or PR already exists before publishing again.

#### Bounded execution

Use these initial limits:

| Limit | Default |
| --- | --- |
| Repeated unchanged tool failure | At most two retries |
| External command | 300 seconds |
| Qwen session | 60 turns and 180 tool calls |
| Qwen wall time | 2400 seconds |
| Outer process deadline | 2700 seconds |
| Actions job deadline | 60 minutes |

Keep the model-request timeout separate from these limits.
The outer deadline remains authoritative even when the request timeout is longer.
Use shorter fixture deadlines in tests.

Run one headless invocation with standard input closed after task delivery.
Disable question tools, interactive planning, nested agents, persistent sessions, and interactive login.
Keep the configured AGENTS.md, skill, and MCP active.
Terminate the full child-process group when the outer deadline expires.
Reserve time to collect and publish the structured failure result.
A missing or invalid assessment is a failure even if the process exits successfully.

### Implementation Plan

Task paths below are proposed ownership boundaries.
Run each task's focused verification before marking it complete.
T1 and T2 are early feasibility gates.
Do not interpret their offline results as provider or image runtime acceptance.

- [ ] **T1 · Prove the Qwen model and non-interactive contract**

  Blocked by: None

  Owns: `tools/auto_sync/bootstrap.sh`, `tools/auto_sync/tool-versions.json`, `tools/auto_sync/model.py`, `tools/auto_sync/agent.py`, `tests/auto_sync/test_model.py`, `tests/auto_sync/test_agent.py`, `tests/auto_sync/fixtures/model/**`

  Gate: review

  Acceptance: Install pinned tools cold and from a verified cache. Capture actual Chat, Responses, and Anthropic requests with fake credentials. Test extra-body precedence, model/URL/header/timeout mapping, token-list failures, unsupported settings, instruction/skill/MCP loading, stdin EOF, disabled questions/planning/subagents, and process-tree deadlines. No paid model requests.

  Verify: `uv run pytest tests/auto_sync/test_model.py tests/auto_sync/test_agent.py`

- [x] **T2 · Prove centralized dependency collection and receipt identity**

  Blocked by: None

  Owns: `pack/collect_dependencies.py`, `pack/probe_dependencies.py`, `tests/pack/test_collect_dependencies.py`, `tests/pack/fixtures/dependencies/**`

  Gate: review

  Acceptance: Read real temporary Python distribution metadata through the selected service interpreter. Preserve aliases and raw versions. Cover empty success versus unknown/failure, different architecture receipts, stale digest/source/mapping, duplicate or missing results, and bounded execution. Mock the container driver; real service-image execution remains a post-merge check.

  Verify: `uv run pytest tests/pack/test_collect_dependencies.py`

- [x] **T3 · Centralize Dockerfile selection before migration**

  Blocked by: None

  Owns: `pack/resolve_dockerfile.sh`, `pack/expand_matrix.sh`, `Makefile`, `.github/workflows/pack.yml`, `tests/pack/test_dockerfile_selection.py`, `tests/pack/test_probe_wiring.py`

  Gate: review

  Acceptance: All three build entry points use one resolver. Filter supported vendor/service pairs before reading defaults. Temporarily retain existing active fallback for migration and preserve historical operation selection. Exercise real matrix expansion and reject selected missing files; broad unsupported selections skip cleanly.

  Verify: `uv run pytest tests/pack/test_dockerfile_selection.py tests/pack/test_probe_wiring.py`

- [x] **T4 · Preserve CUDA VoxBox and CANN MindIE independently**

  Blocked by: T3

  Owns: `pack/cuda/Dockerfile.voxbox`, `pack/cann/Dockerfile.mindie`

  Acceptance: Extract all required stage ancestry and preserve base references, arguments, installation, patches, entrypoint, and platforms. Keep the old combined files until contract. Compare source behavior with the baseline; do not claim build parity from static checks.

  Verify: `uv run pytest tests/pack/test_dockerfile_selection.py tests/pack/test_probe_wiring.py`

- [x] **T5 · Split CoreX and MUSA recipes**

  Blocked by: T3

  Owns: `pack/corex/Dockerfile.vllm`, `pack/musa/Dockerfile.vllm`, `pack/musa/Dockerfile.sglang`

  Acceptance: Use HGGC's service separation while retaining the existing actual vendor image references and independent runtime stages. Do not add CoreX SGLang or upgrade engines. Keep old combined files until contract.

  Verify: `uv run pytest tests/pack/test_dockerfile_selection.py tests/pack/test_probe_wiring.py`

- [x] **T6 · Remove active combined files and enforce strict selection**

  Blocked by: T4, T5

  Owns: `pack/*/Dockerfile`, `pack/resolve_dockerfile.sh`, `pack/matrix.yaml`, `tests/pack/test_dockerfile_selection.py`

  Gate: review

  Acceptance: All eight active vendors resolve only `Dockerfile.<service>`; missing active files fail. Historical unsuffixed files remain supported only for explicit post operations. Update affected comments and compare expanded jobs with the baseline. Preserve the dependency-probe contract until T7/T8.

  Verify: `uv run pytest tests/pack/test_dockerfile_selection.py tests/pack/test_probe_wiring.py`

- [ ] **T7 · Connect final-image receipts to manifest and catalog publication**

  Blocked by: T2, T6

  Owns: `.github/workflows/pack.yml`, `pack/collect_dependencies.py`, `pack/merge_runner.sh`, `tests/pack/test_collect_dependencies.py`, `tests/pack/test_merge_runner.py`, `tests/pack/test_probe_wiring.py`, `tests/pack/fixtures/dependencies/**`

  Gate: review

  Acceptance: Capture Package digest; collect on each native platform; assemble manifests from the exact verified digests; verify descriptors before atomic catalog replacement. Reject stale/missing/mismatched receipts and never reuse old dependencies for changed images. Preserve untouched rows and the exactly-one-row post-operation rule. Define partial-rerun receipt replacement. Replace export-stage workflow use while retaining old Dockerfile context until T8. Resolve baseline ShellCheck findings in the affected workflow scripts without suppressing checks.

  Verify: `uv run pytest tests/pack`

- [ ] **T8 · Remove dependency instrumentation from active recipes**

  Blocked by: T7

  Owns: `pack/*/Dockerfile.*`, `pack/shared/probe_dependencies.sh`, `.github/workflows/pack.yml`, `tests/pack/test_probe_wiring.py`, `pack/.post_operation/README.md`

  Gate: review

  Acceptance: Remove probe arguments, RUN mounts, embedded metadata copies, and dependency export stages from active recipes. Drop active workflow contexts and export code. Keep runtime targets usable. Retain the shared helper and context for existing historical callers, and document that central collection is authoritative. Replace wiring assertions with selection and collection behavior checks.

  Verify: `uv run pytest tests/pack`

- [ ] **T9 · Implement latest-only discovery against catalog and support documentation**

  Blocked by: T7

  Owns: `tools/auto_sync/discovery.py`, `tests/auto_sync/test_discovery.py`, `tests/auto_sync/fixtures/discovery/**`, `README.md`, `docs/supported-runners.md`, `mkdocs.yml`, `pack/merge_runner.sh`, `tests/pack/test_merge_runner.py`

  Gate: review

  Acceptance: Move existing support data without loss and define prepared/published identity rows. Latest stable/post candidates and Ascend stable-engine/actual-plugin pairs use the two-source OR rule. Cover all six subscriptions and explicit CANN aliases. No backlog fallback, raw text matches, or false unchanged on errors. A merged prepared row prevents repeats until Pack confirms publication. Promote only identity-matched rows from measured results.

  Verify: `uv run pytest tests/auto_sync/test_discovery.py tests/pack/test_merge_runner.py`

- [ ] **T10 · Validate complete release proposals as data**

  Blocked by: T9

  Owns: `tools/auto_sync/proposal.py`, `tools/auto_sync/checks.py`, `tests/auto_sync/test_proposal.py`, `tests/auto_sync/test_checks.py`, `tests/auto_sync/fixtures/proposals/**`

  Gate: review

  Acceptance: Validate candidate statuses, compatibility groups, manifest/platform evidence, additional-package choices, and patch dispositions. Bind allowed-path patches and reports to default/head SHA. Check patch application against available exact source revisions. Reject malformed output, policy/workflow edits, escaping symlinks, unsafe matrix input, and fabricated catalog metadata before publication. Run candidate checks without model or write credentials.

  Verify: `uv run pytest tests/auto_sync/test_proposal.py tests/auto_sync/test_checks.py`

- [ ] **T11 · Implement single-PR publication and focused revision**

  Blocked by: T10

  Owns: `tools/auto_sync/publish.py`, `tests/auto_sync/test_publish.py`, `tests/auto_sync/fixtures/github/**`

  Gate: review

  Acceptance: Use a stable bot identity and one open PR across all versions. Weekly runs defer when any managed PR remains open. Authorized Conversation commands reconstruct current context, preserve human commits and lasting pins, and append only requested changes. Check ownership, command identity, current head, and ready report before a fast-forward push. Cover concurrent creation, duplicate delivery, partial publication recovery, unauthorized comments, and stale heads using a stateful fake GitHub service.

  Verify: `uv run pytest tests/auto_sync/test_publish.py`

- [ ] **T12 · Publish canonical release instructions and finish documentation split**

  Blocked by: T1, T8, T11

  Owns: `AGENTS.md`, `.agents/skills/runner-release-sync/**`, `.claude/skills`, `.gitignore`, `README.md`, `mkdocs.yml`, `docs/packaging.md`, `docs/dependency-metadata.md`, `docs/release-automation.md`, `tests/auto_sync/test_project_instructions.py`, `gpustack_runner/__utils__.py` (docstrings only), `gpustack_runner/runner.py` (docstrings only)

  Acceptance: Add the canonical skill and relative symlink without disturbing local Claude content. Document research, compatibility, patches, headless blocked/failed outcomes, configured model use, PR commands, cache behavior, and post-merge Pack. Keep README concise with Ascend rc policy and authoritative links. Include source navigation, evidence rules, coding and testing conventions, DCO sign-off, and the adopter registry. Preserve API navigation. Fix the six baseline docstring warnings and stale README section references without public API behavior changes. Verify tracked-link behavior and instruction discovery.

  Verify: `uv run pytest tests/auto_sync/test_project_instructions.py`; `uv run mkdocs build --strict`

- [ ] **T13 · Wire weekly, manual, and comment workflows with offline end-to-end gates**

  Blocked by: T12

  Owns: `.github/workflows/auto-sync.yml`, `.github/workflows/ci.yml`, `.github/actionlint.yaml`, `tools/auto_sync/run.py`, `tests/auto_sync/test_workflow.py`, `tests/auto_sync/test_e2e.py`, `tests/auto_sync/fixtures/e2e/**`, `tests/auto_sync/test_bootstrap.py`

  Gate: review

  Acceptance: Wire frozen-default-branch research, separate credential-free validation, and clean publication jobs. Expose the agreed model interface and variable/secret mapping. Use Monday 01:23 UTC, configurable Ubuntu runner, repository-wide queued concurrency, verified tool caching, restore-only revisions, and bounded execution. Fix CI path coverage for automation, skills, and docs. Simulate discover/propose/repeat/revise/fail without real GitHub writes or service builds; require Linux CLI contract tests to run, not skip.

  Verify: `uv run pytest tests/auto_sync/test_bootstrap.py tests/auto_sync/test_workflow.py tests/auto_sync/test_e2e.py`; `actionlint .github/workflows/auto-sync.yml .github/workflows/pack.yml .github/workflows/ci.yml`

- [x] **T14 · Add contribution certification and the adopter registry**

  Blocked by: None

  Owns: `DCO`, `ADOPTERS.md`, `LICENSE`

  Acceptance: Preserve the DCO 1.1 text verbatim. Add a Runner-specific empty adopter table and contribution instructions. Change only the GPUStack copyright year to 2026 in LICENSE. Do not claim DCO app enforcement was configured.

  Verify: Compare DCO with the supplied committed reference; inspect the complete LICENSE diff; run repository text checks on all three files.

T2 validation: 73 collector checks and 244 packaging regression checks passed.
Tests read real temporary distribution metadata through the selected Python environment.
Independent review and lead reproduction found three defects; all have regression coverage and fixes.
The fixes reject missing service environments, bound timeout cleanup, and normalize default image platform variants.
Receipt identity remains exact. Scoped hooks passed. Native final-image execution remains unverified.

T3 validation: 115 focused tests and 165 packaging regression tests passed.
Active matrix and manifest outputs match the baseline for all 15 pairs and 31 build jobs.
Selected historical operations also match their baseline outputs.
Independent read-only review found no verified defects.
Scoped hooks and Bash syntax checks passed; existing Pack ShellCheck findings remain assigned to T7.
No service image or GitHub workflow execution was performed.

T4 validation: Source comparison and independent review confirmed complete retained stage bodies.
The six extraction checks and 121 selector/probe checks passed.
The new files preserve configurable bases, runtime outputs, platform branches, and entrypoints.
Image builds and runtime parity remain unverified.

T5 validation: The 19 extraction checks and 121 selector/probe checks passed.
Independent review confirmed nine retained stages and 24 global arguments against the baseline.
All 12 mutated stage or argument controls were rejected. Original vendor base references remain unchanged.
The active matrix still matches all 31 baseline jobs. Scoped hooks passed; image execution remains unverified.

T6 validation: 147 selector/probe checks and 270 packaging regression checks passed.
Independent review confirmed strict active selection and all 17 retained service recipes.
Full active job and manifest output matches the baseline, including 31 jobs and 21 manifests.
Sampled historical operations preserve selection and output; all historical source files remain unchanged.
Scoped hooks and Bash checks passed. Image execution and Ubuntu CI remain unverified.

T14 validation: DCO matches the supplied committed reference byte for byte.
The LICENSE diff changes only the project copyright year.
Scoped pre-commit checks passed for DCO, ADOPTERS.md, LICENSE, and this spec.
The organization DCO app configuration was not changed or verified.

Checkpoints:

- T1, T2, and T3 can start independently.
- T4 and T5 can proceed in parallel after T3.
- After T6, active selection is strict while the existing probe flow still works.
- After T7, digest-bound central metadata replaces the export workflow.
- T8 and T9 can proceed in parallel after T7.
- After T11, offline discovery, proposal validation, and publication behavior form a complete testable path.
- T12 and T13 integrate the canonical instructions and workflow entry points.
- Run the full suite, repository hooks, documentation build, workflow checks, and Python package build before implementation delivery.

Tasks with overlapping ownership run in dependency order.
Keep the system working between migration steps.
Do not remove the old recipe or probe path before its replacement is covered.

### Test Plan

- [ ] I/we understand the owners of the involved components may require updates to existing tests before implementation is complete.

#### Prerequisite testing updates

- Replace probe-stage wiring assumptions while retaining matrix selection and alias behavior coverage.
- Use non-empty fixtures derived from the current catalog, README, matrix, and historical operation behavior.
- Cover all six subscriptions and both CPU platforms.
- Feed every new rejection gate a valid case and an invalid case.
- Use local HTTP and MCP fixtures, stateful GitHub responses, registry descriptors, and temporary Python environments.
- Keep fixture credentials fake and test outputs outside tracked source paths.
- Require the pinned CLI contract tests in Ubuntu CI; missing tools must fail those checks.
- Update CI path filters so tools, skills, AGENTS.md, and related documentation cannot bypass required checks.

#### Unit tests

Every added unit needs behavior coverage.
No numeric coverage baseline was measured during planning.
Do not invent a percentage or measurement date.

| Target | Required cases |
| --- | --- |
| Dockerfile resolver and matrix expansion | Supported pairs, broad unsupported selection, selected missing file, active suffix requirement, explicit historical fallback |
| Central collector | Service interpreter, virtual environment, ordered aliases, raw prerelease/local versions, empty success, failed or unknown collection |
| Receipt validation and catalog merge | Platform differences, digest/source/mapping mismatch, missing and duplicate receipts, partial reruns, unchanged outputs on failure, post-operation zero/one/two matches |
| Model adapter and agent runner | Each exposed input maps correctly or fails explicitly; extra-body precedence; token parsing and masking; protocol differences; EOF and process deadlines |
| Discovery | Latest stable/post policy, Ascend engine/plugin pair, canonical variants, either-source presence, both absent, prepared rows, unknown historical plugin, failed reads, malformed data |
| Proposal validation | Candidate statuses, compatibility groups, patch evidence, missing source checks, permitted paths, generated metadata rejection, policy edits and escaping symlinks |
| Publication | Authorized commands, stable single-PR identity, duplicate events, pending proposals, preserved human commits, stale heads, partial publication recovery |
| Bootstrap and workflow | Cold install, exact cache restore, incompatible cache keys, restore-only revision mode, bounded jobs, required trigger paths |

#### Integration tests

- Invoke the real Bash selector and catalog merge on controlled fixtures.
- Compare expanded jobs with the current behavior before deleting combined recipes.
- Read real distribution metadata through temporary Python environments; mock only the container driver.
- Simulate a platform tag moving after collection; manifest assembly must keep the selected digest or fail.
- Capture requests from the pinned Qwen CLI through local Chat, Responses, and Anthropic endpoints.
- Exercise at least two turns and verify actual AGENTS.md, skill, and MCP loading.
- Check parameter precedence, model selection, URL normalization, custom authentication headers, and timeout units.
- Reject unsupported protocol settings before any provider request.
- Verify that stdin EOF, disabled question tools, and the outer deadline prevent indefinite waits.
- Test cold installation and cache restoration separately; corrupt or incompatible entries must not be trusted.
- Inject candidate Qwen configuration, Git hooks, shell substitutions, and escaping symlinks.
- Confirm candidate validation has no model or write credentials and publication uses only validated data.
- Use a stateful fake GitHub service to exercise concurrent creation, repeated delivery, and interrupted publication.
- Build documentation strictly and verify the skill symlink remains inside the repository.

#### e2e tests

Run an offline scenario through the real controller entry point:

1. The newest eligible release is absent from both detection sources.
2. Research fixtures produce a ready compatibility group and an allowed candidate patch.
3. Validation accepts the complete proposal and creates one simulated formal PR.
4. Repeated discovery reports the existing PR without creating or rewriting another proposal.
5. An authorized command pins one additional package and appends a commit to the same branch.
6. A simulated merge adds a prepared support row.
7. Discovery remains deduplicated while Pack has not run.
8. Simulated measured Pack receipts update the catalog and promote only the verified support coverage.

Also exercise blocked and failed paths:

- An unauthorized comment does not start a model run.
- Ambiguous feedback reports a blocker without waiting for clarification.
- An upstream outage or malformed result is not reported as unchanged.
- A blocked compatibility group does not erase the outcome of an independent ready group.
- Missing credentials, exhausted tokens, waiting commands, and stuck child processes terminate within their limits.
- A changed PR head prevents stale publication.
- An older pending proposal prevents a second PR for a newer release.
- Repeated command delivery does not repeat an already published revision.

Ubuntu CI runs the pinned CLI contract and offline workflow tests.
These tests do not call paid models, write to GitHub, build service images, invoke Pack, or use GPUs.
Actual configured-provider access, MCP permissions, and real PR publication remain post-merge commissioning checks.
Actual amd64 and arm64 final-image collection must be verified through post-merge Pack.
GPU inference checks require the corresponding hardware.
Record all unexecuted checks as unverified.

## Alternatives

- Keep combined Dockerfiles. Rejected because engine maintenance remains coupled and duplicate recipes drift.
- Keep per-Dockerfile probe stages. Rejected because every service must carry metadata instrumentation.
- Infer installed packages from build arguments. Rejected because base images, conditional installs, and patches can change the result.
- Probe once per multi-platform image. Rejected because installed versions already differ between platforms.
- Build all candidates before opening a pull request. Rejected because required Pack resources are available only after merge.
- Use draft pull requests whenever runtime validation is absent. Rejected because the agreed review gate is a formal proposal with explicit limits.
- Trigger a model on every inline comment. Rejected because one review can cause overlapping, incomplete revisions.
- Preserve a long-running agent session for review. Rejected because review must not keep CI resources waiting.
- Depend on cached agent sessions or installed tools for correctness. Rejected because caches expire and cannot serve as durable state.
- Refresh an unreviewed PR automatically. Rejected because human review can start without changing its head SHA; explicit commands avoid that race.
- Generate settings without request-level tests. Rejected because protocol adapters can merge the same fields differently.
- Publish from the agent runner. Rejected because its processes and hooks can outlive the proposal step.
- Remove all historical probe support. Rejected because existing historical recipes still mount the shared helper.
- Use larger or macOS runners by default. Rejected because the current work has no demonstrated need for those resources.

## Open Questions

No blocking product decisions remain.

Deployment must supply the model endpoint, model identifier, model credential, and GitHub App credentials.
The default runner and weekly schedule are defined above.
Maintainers may select another available Linux runner without changing the release contract.

The central collector mechanism, initial tool pins, task dependencies, and test environment are defined above.
T1 must prove the pinned CLI and protocol contract before dependent work proceeds.
T2 must prove collector and receipt behavior with offline fixtures.
Provider access, image execution, and GPU compatibility remain explicitly unverified until their commissioning checks run.
