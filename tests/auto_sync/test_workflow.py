"""Check Actions configuration; controller fixtures prove runtime authorization."""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/auto-sync.yml"


class WorkflowLoader(yaml.SafeLoader):
    """Keep the Actions `on` key while retaining boolean types."""


WorkflowLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in WorkflowLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def load(path):
    return yaml.load(path.read_text(), Loader=WorkflowLoader)  # noqa: S506 - SafeLoader subclass.


def step(job, step_id):
    return next(item for item in job["steps"] if item.get("id") == step_id)


def model_boundary(workflow):
    research = workflow["jobs"]["research"]
    prepare = step(research, "prepare")
    proposal = step(research, "proposal")
    assert research["steps"].index(prepare) < research["steps"].index(proposal)
    assert proposal["if"] == "steps.prepare.outputs.ready == 'true'"
    assert "AUTO_SYNC_LLM_AUTH_TOKEN" not in prepare.get("env", {})
    assert " prepare " in prepare["run"]
    assert "--bundle" in proposal["run"]


def test_triggers_queue_and_job_boundaries():
    workflow = load(WORKFLOW)
    assert workflow["on"]["schedule"] == [{"cron": "7 13 * * 0"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["issue_comment"]["types"] == ["created"]
    assert workflow["concurrency"] == {
        "group": "${{ github.repository }}-auto-sync",
        "queue": "max",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"research", "validation", "publication", "retry"}
    for job in workflow["jobs"].values():
        assert (
            job["runs-on"]
            == "${{ inputs.runner_profile && inputs.runner_profile != 'normal' && format('ubuntu-24.04-{0}', inputs.runner_profile) || vars.AUTOSYNC_RUNNER || 'ubuntu-24.04' }}"
        )
        assert 0 < job["timeout-minutes"] <= 60


def test_authorization_precedes_model_secrets():
    workflow = load(WORKFLOW)
    model_boundary(workflow)
    guard = workflow["jobs"]["research"]["if"]
    assert "github.event.issue.pull_request" in guard
    assert "github.event.comment.body" in guard
    assert "github.event.action == 'created'" in guard
    assert "github.event.comment.user.type != 'Bot'" in guard


@pytest.mark.parametrize(
    "job,stage,field",
    [("research", "prepare", "ready"), ("validation", "validate", "publishable")],
)
@pytest.mark.parametrize("value", [True, False, "true", None])
def test_controller_flags_require_real_booleans(tmp_path, job, stage, field, value):
    workflow = load(WORKFLOW)
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.mkdir()\n"
        "(output / 'result.json').write_text(os.environ['FIXTURE_RESULT'])\n",
    )
    uv.chmod(0o755)
    output = tmp_path / "step-output"
    output.touch()
    env = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_WORKSPACE": str(tmp_path / "checkout"),
        "GITHUB_REPOSITORY": "fixture/runner",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "AUTO_SYNC_DEFAULT_SHA": "a" * 40,
        "FIXTURE_RESULT": json.dumps({field: value}),
    }
    bash = shutil.which("bash")
    assert bash
    result = subprocess.run(  # noqa: S603 - actual workflow shell with a local controller fixture.
        [bash, "-e", "-o", "pipefail", "-c", step(workflow["jobs"][job], stage)["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if type(value) is bool:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == field + "=" + str(value).lower() + "\n"
    else:
        assert result.returncode != 0
        assert output.read_text() == ""


@pytest.mark.parametrize("mutation", ["unguarded", "early_secret", "order"])
def test_model_boundary_rejects_known_bad_workflows(mutation):
    workflow = copy.deepcopy(load(WORKFLOW))
    job = workflow["jobs"]["research"]
    if mutation == "unguarded":
        step(job, "proposal")["if"] = "always()"
    elif mutation == "early_secret":
        step(job, "prepare")["env"]["AUTO_SYNC_LLM_AUTH_TOKEN"] = "fake-token"  # noqa: S105 - negative fixture.
    else:
        job["steps"].remove(step(job, "prepare"))
        job["steps"].append({"id": "prepare"})
    with pytest.raises(AssertionError):
        model_boundary(workflow)


def test_dispatch_inputs_and_exact_configuration_mapping():
    workflow = load(WORKFLOW)
    assert "workflow_call" not in workflow["on"]
    invocation = workflow["on"]["workflow_dispatch"]
    dispatch = {
        "runner_profile",
        "max-session-tokens",
        "max-repair-rounds",
        "llm-thinking",
        "llm-thinking-clear",
        "llm-temperature",
        "llm-top-p",
        "llm-reasoning-effort",
        "attempt",
    }
    assert set(invocation["inputs"]) == dispatch
    for name in dispatch - {
        "runner_profile",
        "llm-thinking",
        "llm-thinking-clear",
        "llm-reasoning-effort",
    }:
        assert invocation["inputs"][name]["type"] == "string"
    for name in [
        "runner_profile",
        "llm-thinking",
        "llm-thinking-clear",
        "llm-reasoning-effort",
    ]:
        assert invocation["inputs"][name]["type"] == "choice"
    assert invocation["inputs"]["runner_profile"]["options"] == ["normal", "4x", "8x"]
    assert invocation["inputs"]["llm-reasoning-effort"]["default"] == "low"
    env = step(workflow["jobs"]["research"], "proposal")["env"]
    assert env["AUTO_SYNC_MAX_SESSION_TOKENS"] == (
        "${{ inputs.max-session-tokens || vars.CI_GPUSTACK_RUNNER_AUTOSYNC_MAX_SESSION_TOKENS || '20000000' }}"
    )
    assert env["AUTO_SYNC_MAX_REPAIR_ROUNDS"] == (
        "${{ inputs.max-repair-rounds || vars.CI_GPUSTACK_RUNNER_AUTOSYNC_MAX_REPAIR_ROUNDS || '2' }}"
    )
    for name in [
        "thinking",
        "thinking-clear",
        "temperature",
        "top-p",
        "reasoning-effort",
    ]:
        config = name.replace("-", "_").upper()
        assert env["AUTO_SYNC_LLM_" + config] == (
            "${{ inputs.llm-"
            + name
            + " || vars.CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_"
            + config
            + " }}"
        )
    for name in [
        "url",
        "model",
        "protocol",
        "use-anthropic",
        "timeout",
        "context-window-size",
        "modalities",
        "auth-header",
        "extra-body",
    ]:
        config = name.replace("-", "_").upper()
        assert env["AUTO_SYNC_LLM_" + config] == (
            "${{ vars.CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_" + config + " }}"
        )
    for name in ["auth-token", "extra-headers"]:
        config = name.replace("-", "_").upper()
        assert env["AUTO_SYNC_LLM_" + config] == (
            "${{ secrets.CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_" + config + " }}"
        )
    assert "BOT_LOGIN" not in WORKFLOW.read_text().replace("AUTO_SYNC_BOT_LOGIN", "")


def test_failed_run_redispatches_exactly_once():
    workflow = load(WORKFLOW)
    retry = workflow["jobs"]["retry"]
    assert retry["needs"] == ["research", "validation", "publication"]
    condition = retry["if"]
    assert "failure()" in condition
    assert "github.event_name == 'schedule'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "inputs.attempt != '2'" in condition
    assert retry["permissions"] == {"actions": "write"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["attempt"]["type"] == "string"
    assert inputs["attempt"]["default"] == "1"
    dispatch = retry["steps"][-1]
    assert dispatch["env"]["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105 - workflow expression fixture.
    assert "gh workflow run auto-sync.yml" in dispatch["run"]
    assert "-f attempt=2" in dispatch["run"]


def test_app_scope_identity_and_clean_validation():
    workflow = load(WORKFLOW)
    research = workflow["jobs"]["research"]
    publication = workflow["jobs"]["publication"]
    for job, token_id, level in [
        (research, "read-token", "read"),
        (publication, "write-token", "write"),
    ]:
        token = step(job, token_id)
        assert token["uses"] == "actions/create-github-app-token@v2"
        assert token["with"]["repositories"] == "${{ github.event.repository.name }}"
        assert token["with"]["permission-contents"] == level
        assert token["with"]["permission-pull-requests"] == level
        assert token["with"]["app-id"] == "${{ secrets.CI_PRT_GENERATOR_ID }}"
        assert token["with"]["private-key"] == "${{ secrets.CI_PRT_GENERATOR_KEY }}"
    assert (
        step(research, "prepare")["env"]["AUTO_SYNC_BOT_LOGIN"]
        == "${{ steps.read-token.outputs.app-slug }}[bot]"
    )
    assert (
        step(publication, "publish")["env"]["AUTO_SYNC_BOT_LOGIN"]
        == "${{ steps.write-token.outputs.app-slug }}[bot]"
    )
    validation = workflow["jobs"]["validation"]
    text = yaml.safe_dump(validation)
    assert "secrets." not in text
    assert "create-github-app-token" not in text
    assert "AUTO_SYNC_LLM_" not in text
    assert publication["if"] == "needs.validation.outputs.publishable == 'true'"


def test_frozen_code_and_retry_artifacts():
    workflow = load(WORKFLOW)
    research = workflow["jobs"]["research"]
    assert (
        step(research, "checkout")["with"]["ref"]
        == "${{ github.event.repository.default_branch }}"
    )
    for name in ["validation", "publication"]:
        job = workflow["jobs"][name]
        checkout = step(job, "checkout")
        assert checkout["with"]["ref"] == "${{ needs.research.outputs.default-sha }}"
        assert checkout["with"]["persist-credentials"] is False
    assert workflow["jobs"]["publication"]["needs"] == ["research", "validation"]
    download = step(workflow["jobs"]["publication"], "bundle")
    assert download["with"]["name"] == "${{ needs.validation.outputs.artifact-name }}"
    assert download["with"]["path"].startswith("${{ runner.temp }}/")
    for name in ["research", "validation"]:
        upload = step(workflow["jobs"][name], "upload")
        assert upload["if"] == "always()"
        assert "${{ github.run_attempt }}" in upload["with"]["name"]
    assert "research" not in step(workflow["jobs"]["publication"], "publish")["run"]


def test_verified_cache_is_saved_before_agent_and_revisions_restore_only():
    workflow = load(WORKFLOW)
    research = workflow["jobs"]["research"]
    restore = step(research, "restore-tools")
    save = step(research, "save-tools")
    bootstrap = step(research, "tools")
    assert restore["uses"] == "actions/cache/restore@v4"
    assert "restore-keys" not in restore["with"]
    assert save["uses"] == "actions/cache/save@v4"
    assert "github.event_name != 'issue_comment'" in save["if"]
    assert research["steps"].index(restore) < research["steps"].index(bootstrap)
    assert research["steps"].index(bootstrap) < research["steps"].index(save)
    assert research["steps"].index(save) < research["steps"].index(
        step(research, "proposal"),
    )
    assert "bootstrap.sh" in bootstrap["run"]
    assert "--cache-key" in step(research, "tool-key")["run"]
    assert restore["with"]["path"] == "${{ runner.temp }}/auto-sync-tools"
    for name in ["research", "validation", "publication"]:
        uv = step(workflow["jobs"][name], "uv")
        assert uv["uses"] == "astral-sh/setup-uv@v7"
        assert uv["with"]["enable-cache"] is True
        assert uv["with"]["version"] == "0.8.24"


def test_ci_requires_pinned_linux_contracts_and_covers_changed_paths():
    workflow = load(ROOT / ".github/workflows/ci.yml")
    for trigger in ["push", "pull_request"]:
        ignored = workflow["on"][trigger].get("paths-ignore", [])
        for path in [
            "tools/**",
            "docs/**",
            "**.md",
            "pack/**",
            ".agents/**",
            "AGENTS.md",
        ]:
            assert path not in ignored
    job = workflow["jobs"]["auto-sync-contract"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert "continue-on-error" not in job
    tests = step(job, "contracts")
    assert tests["env"]["AUTO_SYNC_TOOL_BIN"] == "${{ steps.tools.outputs.bin }}"
    assert "tests/auto_sync" in tests["run"]
    assert "-k" not in tests["run"]
    assert "|| true" not in tests["run"]
    assert "make ci" not in tests["run"]
    assert "lint_workflows.py" in step(job, "workflow-lint")["run"]
    assert (
        'export PATH="$AUTO_SYNC_TOOL_BIN:$PATH"' in step(job, "workflow-lint")["run"]
    )


@pytest.mark.parametrize(
    "workflow_path,job_name",
    [
        (WORKFLOW, "research"),
        (WORKFLOW, "validation"),
        (WORKFLOW, "publication"),
        (ROOT / ".github/workflows/ci.yml", "auto-sync-contract"),
    ],
)
def test_dependency_step_initializes_a_fresh_checkout(
    tmp_path,
    workflow_path,
    job_name,
):
    git = shutil.which("git")
    bash = shutil.which("bash")
    assert git
    assert bash
    checkout = tmp_path / "checkout"
    subprocess.run(  # noqa: S603 - local clone without credentials or network.
        [git, "clone", "--quiet", "--no-hardlinks", str(ROOT), str(checkout)],
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        check=True,
        timeout=30,
    )
    appendix = checkout / "gpustack_runner/_version_appendix.py"
    assert not appendix.exists()
    job = load(workflow_path)["jobs"][job_name]
    install = next(
        s for s in job["steps"] if s.get("name") == "Install locked Python dependencies"
    )
    env = {
        **os.environ,
        "PATH": os.environ["AUTO_SYNC_TOOL_BIN"] + os.pathsep + os.environ["PATH"],
        "UV_OFFLINE": "1",
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "environment"),
        "UV_PYTHON": sys.executable,
        "UV_PYTHON_DOWNLOADS": "never",
    }
    result = subprocess.run(  # noqa: S603 - execute the actual trusted workflow step offline.
        [bash, "-e", "-o", "pipefail", "-c", install["run"]],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert appendix.is_file()
    assert (tmp_path / "environment/bin/python").is_file()
