"""Tests for .auto-sync/checks/write_models_json.py and lint_workflows.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKS_DIR = ROOT / ".auto-sync" / "checks"
WRITE_MODELS_SCRIPT = CHECKS_DIR / "write_models_json.py"
LINT_WORKFLOWS_SCRIPT = CHECKS_DIR / "lint_workflows.py"


def _run_write_models(
    tmp_path: Path,
    env_overrides: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    output_json = tmp_path / "models.json"
    github_output = tmp_path / "github_output.txt"
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_")
    }
    clean_env.update(env_overrides)
    result = subprocess.run(  # noqa: S603 - fixed helper script and controlled env.
        [
            sys.executable,
            str(WRITE_MODELS_SCRIPT),
            "--output",
            str(output_json),
            "--github-output",
            str(github_output),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return result, output_json, github_output


def _parse_github_output(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


def test_empty_env_falls_back_to_taskpack_models(tmp_path: Path) -> None:
    result, output_json, github_output = _run_write_models(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert not output_json.exists()
    outputs = _parse_github_output(github_output)
    assert outputs == {
        "provider": "",
        "model": "",
        "thinking": "",
        "api": "",
        "base-url": "",
        "models-json": "",
    }


@pytest.mark.parametrize(
    "extra_env, expected_api",
    [
        ({"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL": "openai"}, "openai-completions"),
        (
            {"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL": "openai-responses"},
            "openai-responses",
        ),
        (
            {"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL": "anthropic"},
            "anthropic-messages",
        ),
        (
            {"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_USE_ANTHROPIC": "true"},
            "anthropic-messages",
        ),
        ({}, "openai-completions"),
    ],
)
def test_protocol_and_parameters_generation(
    tmp_path: Path,
    extra_env: dict[str, str],
    expected_api: str,
) -> None:
    env = {
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://gateway.example.com/v1",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TEMPERATURE": "0.4",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TOP_P": "0.9",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MAX_TOKENS": "65536",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_CONTEXT_WINDOW_SIZE": "200000",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_REASONING_EFFORT": "medium",
        **extra_env,
    }
    result, output_json, github_output = _run_write_models(tmp_path, env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    provider = payload["providers"]["custom-gateway"]
    assert provider["baseUrl"] == "https://gateway.example.com/v1"
    assert provider["api"] == expected_api
    assert provider["apiKey"] == "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_AUTH_TOKEN"
    model = provider["models"][0]
    assert model["id"] == "glm-5.3"
    assert model["reasoning"] is True
    assert model["maxTokens"] == 65536
    assert model["contextWindow"] == 200000
    assert model["samplingParams"] == {"temperature": 0.4, "top_p": 0.9}
    if expected_api == "openai-completions":
        assert model["compat"] == {"thinkingFormat": "zai"}
    else:
        assert "compat" not in model

    outputs = _parse_github_output(github_output)
    assert outputs["provider"] == "custom-gateway"
    assert outputs["model"] == "glm-5.3"
    assert outputs["thinking"] == "medium"
    assert outputs["api"] == expected_api
    assert outputs["base-url"] == "https://gateway.example.com/v1"
    assert outputs["models-json"] == str(output_json)


@pytest.mark.parametrize(
    "bad_env",
    [
        {"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://gateway.example.com/v1"},
        {"CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3"},
        {
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "http://example.com/v1",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
        },
        {
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://example.com/v1?foo=bar",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
        },
        {
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://example.com/v1",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_PROTOCOL": "grpc",
        },
        {
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://example.com/v1",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING": "disabled",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_REASONING_EFFORT": "invalid",
        },
        {
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "http://[::1]:8080/v1",
            "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
        },
    ],
)
def test_rejects_invalid_model_configurations(
    tmp_path: Path,
    bad_env: dict[str, str],
) -> None:
    result, _, _ = _run_write_models(tmp_path, bad_env)
    assert result.returncode != 0


def test_disabled_thinking_overrides_default_effort_and_normalizes_negative_zero(
    tmp_path: Path,
) -> None:
    env = {
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://open.bigmodel.cn/api/paas/v4",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "glm-5.3",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_THINKING": "disabled",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_REASONING_EFFORT": "high",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_TEMPERATURE": "-0.0",
    }
    result, output_json, github_output = _run_write_models(tmp_path, env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    model = payload["providers"]["custom-gateway"]["models"][0]
    assert model["reasoning"] is False
    assert model["compat"] == {"thinkingFormat": "zai"}
    temp = model["samplingParams"]["temperature"]
    assert temp == 0.0
    assert str(temp) == "0.0"

    outputs = _parse_github_output(github_output)
    assert outputs["thinking"] == "off"


def test_zai_base_url_enables_compat_for_non_glm_model(tmp_path: Path) -> None:
    env = {
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_URL": "https://api.z.ai/zai/v1",
        "CI_GPUSTACK_RUNNER_AUTOSYNC_LLM_MODEL": "custom-model",
    }
    result, output_json, _ = _run_write_models(tmp_path, env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    model = payload["providers"]["custom-gateway"]["models"][0]
    assert model["compat"] == {"thinkingFormat": "zai"}


def _workflow(concurrency: str) -> str:
    return (
        "name: Fixture\non: push\n"
        f"{concurrency}"
        "jobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo ok\n"
    )


def test_lint_workflows_valid_queue_max_and_repo_workflows(tmp_path: Path) -> None:
    wf = tmp_path / "valid.yml"
    wf.write_text(
        _workflow(
            "concurrency:\n  group: fixture\n  queue: max\n  cancel-in-progress: false\n",
        ),
        encoding="utf-8",
    )
    res = subprocess.run(  # noqa: S603 - fixed linter script and temp workflow fixture.
        [sys.executable, str(LINT_WORKFLOWS_SCRIPT), str(wf)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr

    repo_res = subprocess.run(  # noqa: S603 - fixed linter script and repo workflows.
        [
            sys.executable,
            str(LINT_WORKFLOWS_SCRIPT),
            str(ROOT / ".github/workflows/auto-sync.yml"),
            str(ROOT / ".github/workflows/pack.yml"),
            str(ROOT / ".github/workflows/ci.yml"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert repo_res.returncode == 0, repo_res.stdout + repo_res.stderr

    no_bin_env = {**os.environ, "PATH": "", "CI": "false"}
    fallback_res = subprocess.run(  # noqa: S603 - fixed linter script without actionlint.
        [sys.executable, str(LINT_WORKFLOWS_SCRIPT), str(wf)],
        cwd=ROOT,
        env=no_bin_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert fallback_res.returncode == 0, fallback_res.stderr

    require_res = subprocess.run(  # noqa: S603 - fixed linter script requiring actionlint.
        [sys.executable, str(LINT_WORKFLOWS_SCRIPT), "--require-actionlint", str(wf)],
        cwd=ROOT,
        env=no_bin_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert require_res.returncode != 0
    assert "actionlint" in require_res.stderr


@pytest.mark.parametrize(
    "content, expected_msg",
    [
        (
            _workflow(
                "concurrency:\n  group: fixture\n  queue: max\n  queue: single\n",
            ),
            "duplicate",
        ),
        (
            _workflow("concurrency:\n  group: fixture\n  queue: invalid\n"),
            "queue",
        ),
        (
            _workflow(
                "concurrency:\n  group: fixture\n  queue: max\n  cancel-in-progress: true\n",
            ),
            "cancel-in-progress",
        ),
    ],
)
def test_lint_workflows_rejects_invalid_yaml_and_queue(
    tmp_path: Path,
    content: str,
    expected_msg: str,
) -> None:
    wf = tmp_path / "invalid.yml"
    wf.write_text(content, encoding="utf-8")
    res = subprocess.run(  # noqa: S603 - fixed linter script and temp workflow fixture.
        [sys.executable, str(LINT_WORKFLOWS_SCRIPT), str(wf)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert res.returncode != 0
    assert expected_msg in res.stderr


def test_auto_sync_and_ci_workflow_contracts() -> None:
    auto_sync_path = ROOT / ".github/workflows/auto-sync.yml"
    ci_path = ROOT / ".github/workflows/ci.yml"

    auto_sync_raw = auto_sync_path.read_text(encoding="utf-8")
    ci_raw = ci_path.read_text(encoding="utf-8")
    assert "tools/auto_sync" not in auto_sync_raw
    assert "tools.auto_sync" not in auto_sync_raw
    assert "tools/auto_sync" not in ci_raw
    assert "tools.auto_sync" not in ci_raw

    auto_sync_wf = yaml.safe_load(auto_sync_raw)
    assert list(auto_sync_wf["jobs"].keys()) == ["sync"]
    assert auto_sync_wf["concurrency"]["queue"] == "max"
    assert auto_sync_wf["concurrency"]["cancel-in-progress"] is False
    assert auto_sync_wf["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }

    sync_steps = auto_sync_wf["jobs"]["sync"]["steps"]
    assert any(
        ".auto-sync/checks/write_models_json.py" in step.get("run", "")
        for step in sync_steps
    )
    loopwright_steps = [
        step for step in sync_steps if step.get("uses") == "gpustack/loopwright@main"
    ]
    assert len(loopwright_steps) == 1
    lw_step = loopwright_steps[0]
    assert lw_step["with"]["taskpack-path"] == ".auto-sync/taskpack.yaml"
    assert lw_step["with"]["output"] == "json,github-step-summary"
    assert "publication-endpoint-url" in lw_step["with"]
    assert lw_step["env"]["PYTHON_BIN"] == "${{ github.workspace }}/.venv/bin/python"

    ci_wf = yaml.safe_load(ci_raw)
    assert "macos-14" not in ci_raw
    assert "macos-15" in ci_wf["jobs"]["ci"]["runs-on"]
    contract_steps = ci_wf["jobs"]["auto-sync-contract"]["steps"]
    combined_runs = "\n".join(step.get("run", "") for step in contract_steps)
    assert "uv run pytest tests/auto_sync" in combined_runs
    assert "uv run python .auto-sync/checks/lint_workflows.py" in combined_runs
    assert "uv run mkdocs build --strict" in combined_runs
