"""Contract tests for .auto-sync/taskpack.yaml and .auto-sync/instructions.md."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

ROOT = Path(__file__).resolve().parents[2]
AUTO_SYNC_DIR = ROOT / ".auto-sync"
TASKPACK_PATH = AUTO_SYNC_DIR / "taskpack.yaml"
INSTRUCTIONS_PATH = AUTO_SYNC_DIR / "instructions.md"
SKILL_PATH = ROOT / ".agents" / "skills" / "runner-release-sync" / "SKILL.md"
BUILTIN_PROTECTED_PATHS = (
    ".github",
    ".claude",
    ".codex",
    ".agents",
    ".loopwright/policies",
    "AGENTS.md",
    "CLAUDE.md",
    ".auto-sync",
)


def _find_loopwright_index() -> Path | None:
    candidates: list[Path] = []
    env_path = os.environ.get("LOOPWRIGHT_DIST_INDEX", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(
        ROOT.parent / "loopwright" / "packages/github-app/dist/index.js",
    )
    candidates.extend(
        sorted(ROOT.parents[1].glob("*/loopwright/packages/github-app/dist/index.js")),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _check_unique_yaml_keys(node: Node, seen: set[int]) -> None:
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[object] = set()
        for key, value in node.value:
            if isinstance(key, ScalarNode):
                assert key.value not in keys, f"duplicate YAML key: {key.value!r}"
                keys.add(key.value)
            _check_unique_yaml_keys(key, seen)
            _check_unique_yaml_keys(value, seen)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            _check_unique_yaml_keys(item, seen)


def _path_covered_by(candidate: str, root: str) -> bool:
    return candidate == root or candidate.startswith(root.rstrip("/") + "/")


def test_taskpack_manifest_structure_and_scopes() -> None:
    raw_text = TASKPACK_PATH.read_text(encoding="utf-8")
    assert "${" not in raw_text
    node = yaml.compose(raw_text, Loader=yaml.SafeLoader)
    assert node is not None
    _check_unique_yaml_keys(node, set())

    data = yaml.safe_load(raw_text)
    assert data["apiVersion"] == "loopwright.dev/v1alpha1"
    assert data["kind"] == "Taskpack"
    assert data["metadata"]["name"] == "auto-sync"

    spec = data["spec"]
    assert "sandbox" not in spec
    assert spec["instructions"] == [".auto-sync/instructions.md"]
    assert spec["proposal"]["path"] == ".autosync/proposal.json"
    assert spec["proposal"]["schemaVersion"] == 1
    assert set(spec["proposal"]["requiredFields"]) >= {
        "schema_version",
        "summary",
        "subscriptions",
    }

    writable = spec["scope"]["writable"]
    protected = spec["scope"]["protected"]
    assert writable == [
        ".autosync",
        "pack/matrix.yaml",
        "pack/cuda",
        "pack/rocm",
        "pack/cann",
        "docs/support-records.md",
        "docs/supported-runners.md",
        "README.md",
    ]
    assert protected == [
        "pack/cuda/Dockerfile.voxbox",
        "pack/cann/Dockerfile.mindie",
        "pack/cann/mindie-atb-models_2.3.0_linux-amd64_py3.11_torch2.1.0-abi0.tar.gz",
        "pack/cann/mindie-atb-models_2.3.0_linux-arm64_py3.11_torch2.1.0-abi0.tar.gz",
        "pack/cann/patches/hixl",
        "pack/cann/patches/mindie.zip",
    ]

    effective_protected = [*BUILTIN_PROTECTED_PATHS, *protected]
    for w_path in writable:
        for builtin_path in BUILTIN_PROTECTED_PATHS:
            assert not _path_covered_by(w_path, builtin_path)
            assert not _path_covered_by(builtin_path, w_path)
        for p_path in effective_protected:
            assert not _path_covered_by(w_path, p_path), (
                f"writable {w_path} lives inside protected {p_path}"
            )

    for p_path in protected:
        assert (ROOT / p_path).exists(), f"protected path missing on disk: {p_path}"
        assert any(
            p_path != w_path and _path_covered_by(p_path, w_path) for w_path in writable
        ), f"redundant protected path outside writable scope: {p_path}"

    def _effective_verdict(rel_path: str) -> str:
        if any(_path_covered_by(rel_path, p_path) for p_path in effective_protected):
            return "protected"
        if any(_path_covered_by(rel_path, w_path) for w_path in writable):
            return "writable"
        return "outside_writable"

    assert _effective_verdict(".autosync/proposal.json") == "writable"
    assert _effective_verdict("pack/cuda/Dockerfile.vllm") == "writable"
    assert _effective_verdict("pack/cuda/Dockerfile.voxbox") == "protected"
    assert _effective_verdict("pack/cann/Dockerfile.mindie") == "protected"
    assert (
        _effective_verdict("pack/cann/patches/hixl/001_channel_generation.patch")
        == "protected"
    )
    assert _effective_verdict("gpustack_runner/runner.py.json") == "outside_writable"
    assert _effective_verdict("pack/dependencies.json") == "outside_writable"

    git_bin = shutil.which("git")
    if git_bin is not None and (ROOT / ".git").exists():
        tracked_res = subprocess.run(  # noqa: S603 - fixed read-only git ls-files check.
            [git_bin, "-C", str(ROOT), "ls-files"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert tracked_res.returncode == 0, tracked_res.stderr
        writable_tracked = {
            line
            for line in tracked_res.stdout.splitlines()
            if line and _effective_verdict(line) == "writable"
        }
        expected_writable_tracked = {
            "README.md",
            "docs/support-records.md",
            "docs/supported-runners.md",
            "pack/matrix.yaml",
            "pack/cuda/Dockerfile.vllm",
            "pack/cuda/Dockerfile.sglang",
            "pack/rocm/Dockerfile.vllm",
            "pack/rocm/Dockerfile.sglang",
            "pack/cann/Dockerfile.vllm",
            "pack/cann/Dockerfile.sglang",
            *(
                line
                for line in tracked_res.stdout.splitlines()
                if line.endswith(".patch")
                and (
                    line.startswith(
                        (
                            "pack/cuda/patches/",
                            "pack/rocm/patches/",
                            "pack/cann/patches/vllm/",
                            "pack/cann/patches/vllm_ascend/",
                            "pack/cann/patches/vllm_omni/",
                            "pack/cann/patches/sglang/",
                        ),
                    )
                )
            ),
        }
        assert writable_tracked == expected_writable_tracked

    command_checks = [
        check
        for check in spec["verification"]["localChecks"]
        if check["implementation"] == "command.v1"
    ]
    assert len(command_checks) == 1
    params = command_checks[0]["parameters"]
    assert params["script"] == ".auto-sync/checks/validate_candidate.sh"
    assert params["timeoutSeconds"] == 300

    mcp_servers = spec["mcp"]["servers"]
    assert mcp_servers == [
        {
            "id": "github",
            "transport": "stdio",
            "command": "github-mcp-server",
            "args": [
                "stdio",
                "--read-only",
                "--toolsets",
                "repos,pull_requests,issues",
            ],
            "envFrom": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": "GITHUB_TOKEN",
            },
            "readOnly": True,
            "timeoutSeconds": 60,
        },
        {
            "id": "deepwiki",
            "transport": "http",
            "url": "https://mcp.deepwiki.com/mcp",
            "readOnly": True,
            "timeoutSeconds": 60,
        },
    ]
    assert "GITHUB_TOKEN" not in params["env"]

    limits = spec["limits"]
    assert limits == {
        "wallTimeSeconds": 3000,
        "totalTokens": 20000000,
        "maxOutputTokens": 65536,
        "maxModelCalls": 256,
        "maxAttempts": 3,
        "toolTimeoutSeconds": 300,
        "commandTimeoutSeconds": 600,
    }

    validator_sh = ROOT / params["script"]
    assert validator_sh.is_file()
    assert stat.S_IMODE(validator_sh.stat().st_mode) & stat.S_IXUSR
    assert (AUTO_SYNC_DIR / "memory" / ".gitkeep").is_file()
    assert spec["models"] == [
        {
            "provider": "zai-coding-cn",
            "id": "glm-5.3",
            "thinking": "low",
            "samplingParams": {
                "temperature": 0.4,
                "top_p": 0.9,
            },
            "apiKeyEnv": "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN",
        },
    ]


def test_instructions_byte_limit_and_required_coverage() -> None:
    raw_bytes = INSTRUCTIONS_PATH.read_bytes()
    assert len(raw_bytes) <= 24_576
    text = raw_bytes.decode("utf-8")

    required_tokens = [
        "cuda/vllm",
        "cuda/sglang",
        "rocm/vllm",
        "rocm/sglang",
        "cann/vllm",
        "cann/sglang",
        "LMCACHE_UPSTREAM_TAG",
        "lmcache_ascend/__init__.py",
        "TheRock",
        "VLLM_TORCHCODEC_VERSION",
        "VLLM_HIXL_COMMIT",
        "SGLANG_NVIDIA_HPCX_VERSION",
        "pack/prereleases.yaml",
        "delete",
        ".autosync/proposal.json",
        "prepared",
        "published",
        "PACK_RUN_URL",
    ]
    for token in required_tokens:
        assert token in text, f"instructions.md missing required token: {token}"


def test_runner_release_sync_skill_thin_wrapper_contract() -> None:
    raw_text = SKILL_PATH.read_text(encoding="utf-8")
    lines = raw_text.splitlines()
    assert 15 <= len(lines) <= 35, (
        f"expected concise ~20-25 line wrapper, got {len(lines)}"
    )
    assert raw_text.startswith("---\n")
    parts = raw_text.split("---\n", 2)
    assert len(parts) == 3
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["name"] == "runner-release-sync"
    assert isinstance(frontmatter["description"], str)
    assert frontmatter["description"].strip()

    body = parts[2]
    for required_ref in (
        ".auto-sync/taskpack.yaml",
        ".auto-sync/instructions.md",
        ".auto-sync/memory/",
        "docs/release-automation.md",
        'LOOPWRIGHT_CANDIDATE_DIR="$PWD" bash .auto-sync/checks/validate_candidate.sh',
        "git status",
    ):
        assert required_ref in body, (
            f"SKILL.md missing required reference: {required_ref}"
        )

    for duplicated_rule in (
        "LMCACHE_UPSTREAM_TAG",
        "VLLM_TORCHCODEC_VERSION",
        "SGLANG_NVIDIA_HPCX_VERSION",
        "910c",
    ):
        assert duplicated_rule not in body, (
            f"SKILL.md should not duplicate domain rule {duplicated_rule!r}"
        )


def test_loopwright_runtime_contract_if_available(tmp_path: Path) -> None:
    node_bin = shutil.which("node")
    loopwright_index = _find_loopwright_index()
    if node_bin is None or loopwright_index is None:
        pytest.skip("local Loopwright checkout or node binary is unavailable")

    models_json_path = tmp_path / "models.json"
    gen = subprocess.run(  # noqa: S603 - fixed helper script and controlled env.
        [
            sys.executable,
            str(AUTO_SYNC_DIR / "checks" / "write_models_json.py"),
            "--output",
            str(models_json_path),
        ],
        env={
            **os.environ,
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://api.example.com/v1",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL": "openai",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING": "enabled",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert gen.returncode == 0, gen.stderr

    run_root = tmp_path / "run-root"
    run_root.mkdir()
    cli_run_root = tmp_path / "cli-run-root"
    cli_run_root.mkdir()
    step_summary_path = tmp_path / "github_step_summary.md"
    github_output_path = tmp_path / "github_output.txt"
    script = """
import fs from 'node:fs';

const [
  lwUrl,
  repoRoot,
  runRoot,
  cliRunRoot,
  modelsJsonPath,
  stepSummaryPath,
  githubOutputPath,
] = process.argv.slice(1);
const lw = await import(lwUrl);

const manifest = await lw.loadDeclarativeTaskpack({
  manifestPath: '.auto-sync/taskpack.yaml',
  repositoryRoot: repoRoot,
});
const policy = lw.resolveEffectiveTaskpackSandboxPolicy(manifest, {
  workspaceRoot: repoRoot,
  relativeTaskpackPath: '.auto-sync/taskpack.yaml',
  env: { GITHUB_ACTIONS: 'true' },
});
const negotiated = lw.negotiateSandboxBackend(policy, {
  platform: process.platform,
  arch: process.arch,
});
const modelsConfig = lw.parsePiModelsJson(fs.readFileSync(modelsJsonPath));

let capturedTurnkeyReport = null;
const dryRun = await lw.runGitHubActionEntrypoint({
  repositoryRoot: repoRoot,
  repositoryFullName: 'gpustack/runner',
  taskpackPath: '.auto-sync/taskpack.yaml',
  runRoot,
  runId: 'contract-test-1',
  mode: 'candidate',
  eventName: 'workflow_dispatch',
  baseRevision: '0'.repeat(40),
  upstreamRecords: [{ upstreamId: 'vllm', status: 'available', version: '0.34.0' }],
  gateEndpoints: [{
    id: 'local-command-gate',
    url: 'http://127.0.0.1:43123/gate',
    signingCredentialRef: 'local-cmd-signing',
  }],
  publicationEndpoint: {
    id: 'pr-publisher',
    url: 'http://127.0.0.1:43124/publish',
    signingCredentialRef: 'pub-signing',
  },
  env: {
    ...process.env,
    GITHUB_ACTIONS: 'true',
    CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN: 'test-token-value',
  },
  dryRun: true,
  output: 'json,github-step-summary',
  onTurnkeyReport: (info) => {
    capturedTurnkeyReport = info;
  },
});

const cliExitCode = await lw.runActionCli({
  ...process.env,
  GITHUB_ACTIONS: 'true',
  GITHUB_WORKSPACE: repoRoot,
  GITHUB_REPOSITORY: 'gpustack/runner',
  GITHUB_SHA: '0'.repeat(40),
  GITHUB_EVENT_NAME: 'workflow_dispatch',
  GITHUB_RUN_ID: 'contract-cli-1',
  GITHUB_STEP_SUMMARY: stepSummaryPath,
  GITHUB_OUTPUT: githubOutputPath,
  'INPUT_TASKPACK-PATH': '.auto-sync/taskpack.yaml',
  INPUT_MODE: 'candidate',
  'INPUT_EVENT-NAME': 'workflow_dispatch',
  'INPUT_RUN-ROOT': cliRunRoot,
  'INPUT_RUN-ID': 'contract-cli-1',
  'INPUT_STORAGE-PROFILE': 'actions-basic',
  INPUT_PROVIDER: 'custom-gateway',
  INPUT_MODEL: 'glm-5.3',
  INPUT_THINKING: 'high',
  INPUT_API: 'openai-completions',
  'INPUT_BASE-URL': 'https://api.example.com/v1',
  'INPUT_MODELS-JSON': modelsJsonPath,
  'INPUT_ALLOW-CUSTOM-BASE-URL': 'true',
  'INPUT_PROVIDER-TOKEN-ENV': 'CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN',
  CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN: 'test-token-value',
  INPUT_OUTPUT: 'json,github-step-summary',
  'INPUT_DRY-RUN': 'true',
  'INPUT_PUBLICATION-ENDPOINT-URL': 'http://127.0.0.1:43124/publish',
  LOOPWRIGHT_PUBLICATION_SIGNING_SECRET: 'pub-signing-secret',
  'INPUT_UPSTREAM-RECORDS': JSON.stringify([
    { upstreamId: 'vllm', status: 'available', version: '0.34.0' },
  ]),
});

const instructionResources = (dryRun.taskpack?.instructionResources ?? []).map((item) => ({
  id: item.id,
  kind: item.kind,
  path: item.path,
  digest: item.digest,
}));
const localCommandGates = (dryRun.taskpack?.localCommandGates ?? []).map((gate) => ({
  checkId: gate.checkId,
  gateId: gate.gateId,
  script: gate.script,
  timeoutSeconds: gate.timeoutSeconds,
  allowReadOnlyGitHubToken: gate.allowReadOnlyGitHubToken,
  env: gate.env,
}));

const compiledScope = dryRun.taskpack?.config?.spec?.task?.spec?.scope ?? null;
const compiledBudgets = dryRun.taskpack?.config?.spec?.task?.spec?.budgets ?? null;

const badMcpResult = await lw.runGitHubActionEntrypoint({
  repositoryRoot: repoRoot,
  repositoryFullName: 'gpustack/runner',
  taskpackPath: '.auto-sync/taskpack.yaml',
  runRoot,
  runId: 'contract-bad-mcp',
  mode: 'candidate',
  eventName: 'workflow_dispatch',
  baseRevision: '0'.repeat(40),
  mcpServersJson: JSON.stringify([{ id: 'insecure', transport: 'http', url: 'http://example.com/mcp' }]),
  env: {
    ...process.env,
    GITHUB_ACTIONS: 'true',
    CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN: 'test-token-value',
  },
  dryRun: true,
});

const badLimitsResult = await lw.runGitHubActionEntrypoint({
  repositoryRoot: repoRoot,
  repositoryFullName: 'gpustack/runner',
  taskpackPath: '.auto-sync/taskpack.yaml',
  runRoot,
  runId: 'contract-bad-limits',
  mode: 'candidate',
  eventName: 'workflow_dispatch',
  baseRevision: '0'.repeat(40),
  upstreamRecords: [{ upstreamId: 'vllm', status: 'available', version: '0.34.0' }],
  env: {
    ...process.env,
    GITHUB_ACTIONS: 'true',
    CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN: 'test-token-value',
    LOOPWRIGHT_TOTAL_TOKENS: '-5',
  },
  dryRun: true,
});

console.log(JSON.stringify({
  manifestName: manifest.metadata.name,
  mcpServerIds: (manifest.spec.mcp?.servers ?? []).map((s) => s.id),
  manifestTotalTokens: manifest.spec.limits?.totalTokens ?? null,
  compiledTotalTokens: compiledBudgets?.totalTokens ?? null,
  compiledWallTimeMs: compiledBudgets?.wallTimeMs ?? null,
  badMcpKind: badMcpResult.kind,
  badLimitsKind: badLimitsResult.kind,
  preferredBackends: policy.preferredBackends,
  negotiatedBackendId: negotiated.backendId,
  hasCustomGateway: modelsConfig.providers.has('custom-gateway'),
  dryRunKind: dryRun.kind,
  dryRunReason: dryRun.reason ?? null,
  compiledScope,
  instructionResources,
  localCommandGates,
  capturedReportStatus: capturedTurnkeyReport?.report?.status ?? null,
  cliExitCode,
}));
"""
    result = subprocess.run(  # noqa: S603 - fixed node runtime contract probe.
        [
            node_bin,
            "--input-type=module",
            "-e",
            script,
            loopwright_index.as_uri(),
            str(ROOT),
            str(run_root),
            str(cli_run_root),
            str(models_json_path),
            str(step_summary_path),
            str(github_output_path),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # runActionCli prints one JSON result line to stdout before our final console.log line.
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["manifestName"] == "auto-sync"
    assert payload["mcpServerIds"] == ["github", "deepwiki"]
    assert payload["manifestTotalTokens"] == 20_000_000
    assert payload["compiledTotalTokens"] == 20_000_000
    assert payload["compiledWallTimeMs"] == 3_000_000
    assert payload["badMcpKind"] == "blocked"
    assert payload["badLimitsKind"] == "blocked"
    assert payload["preferredBackends"] == ["direct-dedicated"]
    assert payload["negotiatedBackendId"] == "direct-dedicated"
    assert payload["hasCustomGateway"] is True
    assert payload["dryRunKind"] == "compiled"
    assert payload["capturedReportStatus"] == "dry_run"
    assert payload["cliExitCode"] == 0
    compiled_scope = payload["compiledScope"]
    assert compiled_scope is not None
    assert "pack/cuda/**" in compiled_scope["writable"]
    assert "pack/cuda/Dockerfile.voxbox/**" in compiled_scope["protected"]
    assert "pack/cann/Dockerfile.mindie/**" in compiled_scope["protected"]
    assert "pack/cann/patches/hixl/**" in compiled_scope["protected"]

    instruction_resources = payload["instructionResources"]
    assert len(instruction_resources) == 1
    assert instruction_resources[0]["path"] == ".auto-sync/instructions.md"
    digest = instruction_resources[0]["digest"]
    assert digest["algorithm"] == "sha256"
    assert len(digest["hex"]) == 64
    assert all(ch in "0123456789abcdef" for ch in digest["hex"])

    local_gates = payload["localCommandGates"]
    assert len(local_gates) == 1
    assert local_gates[0]["checkId"] == "runner-static-checks"
    assert local_gates[0]["script"] == ".auto-sync/checks/validate_candidate.sh"
    assert local_gates[0]["timeoutSeconds"] == 300
    assert local_gates[0]["allowReadOnlyGitHubToken"] is True
    assert local_gates[0]["env"] == ["PACK_RUN_URL", "PYTHON_BIN"]

    summary_text = step_summary_path.read_text(encoding="utf-8")
    assert summary_text.startswith("#") or "## " in summary_text
    assert "contract-cli-1" in summary_text
    assert "dry_run" in summary_text

    output_lines = github_output_path.read_text(encoding="utf-8").splitlines()
    assert "result<<LOOPWRIGHT_EOF" in output_lines
    result_idx = output_lines.index("result<<LOOPWRIGHT_EOF")
    assert output_lines[result_idx + 2] == "LOOPWRIGHT_EOF"
    cli_result = json.loads(output_lines[result_idx + 1])
    assert cli_result["kind"] == "compiled"
    assert cli_result["taskpack"]["name"] == "auto-sync"
    assert "registryBytes" not in cli_result["taskpack"]
    assert "configBytes" not in cli_result["taskpack"]
    assert cli_result["taskpack"]["registryByteLength"] > 0
    assert "test-token-value" not in github_output_path.read_text(encoding="utf-8")
