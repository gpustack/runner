# ruff: noqa: E402
"""Offline controller stages use real Git, HTTP, registry tools and pinned Qwen."""

import copy
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent / "fixtures/github"))
sys.path.insert(0, str(Path(__file__).parent / "fixtures/e2e"))
sys.path.insert(0, str(Path(__file__).parent / "fixtures/model"))
import server
from boundaries import ExhaustedModel, GitHTTP, Registry, Upstreams, encoded
from test_agent import _local_cli_process

from tools.auto_sync import run
from tools.auto_sync.checks import _run as run_command
from tools.auto_sync.run import (
    _acquire_candidate,
    _env,
    _permissions,
    _redact,
    _registry,
    _source,
)

BOT = "runner-sync[bot]"
REPOSITORY = "gpustack/runner"


def git(repo, *args):
    return subprocess.run(  # noqa: S603 - disposable real Git fixtures.
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    repo = tmp_path / "objects"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    for path in (
        "AGENTS.md",
        ".agents/skills/runner-release-sync/SKILL.md",
        "docs/release-automation.md",
    ):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    shutil.copytree(
        ROOT / "tools",
        repo / "tools",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (repo / ".claude").mkdir()
    (repo / ".claude/skills").symlink_to("../.agents/skills")
    (repo / "gpustack_runner").mkdir()
    (repo / "gpustack_runner/runner.py.json").write_text("[]\n")
    (repo / "README.md").write_text(
        "# Runner\n[Supported runners](docs/supported-runners.md)\n",
    )
    (repo / "docs/supported-runners.md").write_text(
        "<!-- runner-support-records:start -->\n| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| cuda | 13.0.1 | vllm | - | 0.29.0 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->\n",
    )
    (repo / "pack/cuda").mkdir(parents=True)
    (repo / "pack/matrix.yaml").write_text(
        "rules:\n  - backend: cuda\n    services: [vllm]\n    platforms: [linux/amd64]\n    args: [VLLM_VERSION=0.29.0]\n",
    )
    source = tmp_path / "upstream"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "Dockerfile").write_text(
        "FROM scratch\nCOPY requirements.txt /requirements.txt\n",
    )
    (source / "requirements.txt").write_text("torch==2.9.0\n")
    upstream = commit(source)
    for tag in ("v0.30.0", "v0.29.0", "v0.5.0", "v0.30.0rc1"):
        git(source, "tag", tag)
    git(source, "update-server-info")
    with GitHTTP(tmp_path) as http, Registry() as registry:
        (repo / "pack/cuda/Dockerfile.vllm").write_text(
            "ARG VLLM_VERSION=0.29.0\nARG CUDA_VERSION=13.0.1\n"
            f"ARG VLLM_BASE_IMAGE={registry.image.replace('0.30.0', '${VLLM_VERSION}')}\n"
            "ARG PYTHON_VERSION=3.12\nARG VLLM_LMCACHE_VERSION=0.5.4\nFROM ${VLLM_BASE_IMAGE} AS vllm\n",
        )
        sha = commit(repo)
        with Upstreams(repo, REPOSITORY, BOT, upstream, http.url) as api:
            monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
            monkeypatch.setenv("GITHUB_API_URL", api.url)
            monkeypatch.setenv("AUTO_SYNC_GITHUB_TOKEN", "fake-read-token")
            monkeypatch.setenv("AUTO_SYNC_BOT_LOGIN", BOT)
            yield repo, sha, api, registry, source


def invoke(*args):
    code = run.main(list(map(str, args)))
    return code


def prepare(scenario, tmp_path, event=None):
    repo, sha, *_ = scenario
    output = tmp_path / "prepared"
    argv = [
        "prepare",
        "--repo",
        repo,
        "--repository",
        REPOSITORY,
        "--default-sha",
        sha,
        "--output",
        output,
    ]
    if event:
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "event.json"
        path.write_text(json.dumps(event))
        argv += ["--event", path]
    assert invoke(*argv) == 0
    return output


def proposal(scenario, context):
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/ready.json").read_text(),
    )
    raw["identity"] = context["identity"]
    row = raw["groups"][0]["rows"][0]
    row["base_image"] = scenario[3].image
    row["manifest"].update(
        digest=scenario[3].index_digest,
        platform_digest=scenario[3].child_digest,
    )
    return raw


def research_bundle(scenario, tmp_path, prepared):
    # Output data is the controlled model boundary, not a mock of the controller.
    output = tmp_path / "research"
    output.mkdir()
    context = json.loads((prepared / "context.json").read_text())
    shutil.copyfile(prepared / "context.json", output / "context.json")
    (output / "proposal.json").write_text(json.dumps(proposal(scenario, context)))
    return output


def test_automatic_sourced_pairing_and_all_six_discovery_results(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    result = json.loads((prepared / "result.json").read_text())
    assert result["ready"]
    assert len(result["candidates"]) == 6
    cann = next(c for c in result["discovery"] if c["subscription"] == "cann/vllm")
    assert cann["engine_version"] == "0.30.0"
    assert cann["plugin_version"] == "0.30.0rc1"
    assert cann["pair_source"].endswith("/releases/tag/v0.30.0rc1")
    assert all(method == "GET" for method, _, _ in scenario[2].requests)


def test_pairing_never_inferred_from_equal_version_tag(scenario, tmp_path):
    scenario[2].releases["vllm-project/vllm-ascend"][0]["body"] = (
        "No compatibility statement."
    )
    prepared = prepare(scenario, tmp_path)
    result = json.loads((prepared / "result.json").read_text())
    cann = next(c for c in result["discovery"] if c["subscription"] == "cann/vllm")
    assert cann["status"] == "blocked"
    assert len(result["candidates"]) == 6


def test_validation_registry_truth_and_clean_publication(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    checked = tmp_path / "checked"
    monkeypatch.delenv("AUTO_SYNC_GITHUB_TOKEN")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-model-must-not-enter-child")
    real_command = run_command
    children = []

    def credential_free(argv, env, **kwargs):
        assert not any("TOKEN" in key or "SECRET" in key or "LLM" in key for key in env)
        assert not any(
            "fake-read-token" in value
            or "fake-write-token" in value
            or "fake-model" in value
            for value in env.values()
        )
        children.append(argv[0])
        return real_command(argv, env, **kwargs)

    monkeypatch.setattr(run, "_run", credential_free)
    monkeypatch.setattr(run.checks, "_run", credential_free)
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 0
    )
    artifact = json.loads((checked / "artifact.json").read_text())
    assert artifact["patch"]
    assert artifact["groups"][0]["validation"]["status"] == "passed"
    assert all("Authorization" not in headers for _, headers in scenario[3].requests)
    monkeypatch.setenv("AUTO_SYNC_GITHUB_TOKEN", "fake-write-token")
    result = tmp_path / "published.json"
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            result,
        )
        == 0
    )
    assert json.loads(result.read_text())["status"] == "published"
    assert len(scenario[2].prs) == 1
    assert not scenario[2].prs[1]["draft"]
    assert "blocked" in scenario[2].prs[1]["body"]
    assert "failed" in scenario[2].prs[1]["body"]
    assert git(scenario[0], "status", "--porcelain") == ""
    assert any("crane" in name for name in children)
    assert "git" in children
    assert "yq" in children
    for path in checked.iterdir():
        assert "fake-" not in path.read_text()


def test_fabricated_manifest_rejected_before_write(scenario, tmp_path, monkeypatch):
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"][0]["rows"][0]["manifest"]["platform_digest"] = "sha256:" + "f" * 64
    (bundle / "proposal.json").write_text(json.dumps(raw))
    monkeypatch.delenv("AUTO_SYNC_GITHUB_TOKEN")
    checked = tmp_path / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 1
    )
    result = json.loads((checked / "result.json").read_text())
    assert not result["publishable"]
    assert (
        next(c for c in result["candidates"] if c["subscription"] == "cuda/vllm")[
            "status"
        ]
        == "failed"
    )
    assert not scenario[2].prs


def test_exact_source_acquisition_reads_release_tree(scenario, tmp_path):
    target, sha = _source(
        run.PublicUpstream(),
        "vllm-project/vllm",
        "v0.30.0",
        tmp_path / "sources",
        _env(tmp_path / "home"),
    )
    assert sha == git(scenario[4], "rev-parse", "HEAD")
    assert (
        target / "Dockerfile"
    ).read_text() == "FROM scratch\nCOPY requirements.txt /requirements.txt\n"
    assert (target / "requirements.txt").read_text() == "torch==2.9.0\n"
    assert git(target, "rev-parse", "HEAD") == sha


def test_upstream_failure_keeps_independent_candidate_outcomes(scenario, tmp_path):
    scenario[2].outages.add("vllm-project/vllm")
    prepared = prepare(scenario, tmp_path)
    result = json.loads((prepared / "result.json").read_text())
    outcomes = {c["subscription"]: c["status"] for c in result["candidates"]}
    assert outcomes["cuda/vllm"] == outcomes["rocm/vllm"] == "failed"
    assert outcomes["cuda/sglang"] == "blocked"
    assert result["ready"]


def test_model_cannot_hide_acquisition_failure_as_unchanged(scenario, tmp_path):
    scenario[2].outages.add("vllm-project/vllm")
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"] = []
    for candidate in raw["candidates"]:
        candidate.update(status="unchanged", groups=[], reason="Already represented.")
    (bundle / "proposal.json").write_text(json.dumps(raw))
    checked = tmp_path / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 1
    )
    result = json.loads((checked / "result.json").read_text())
    outcomes = {c["subscription"]: c["status"] for c in result["candidates"]}
    assert outcomes["cuda/vllm"] == outcomes["rocm/vllm"] == "failed"
    assert outcomes["cuda/sglang"] == "blocked"
    assert not result["publishable"]


def test_model_cannot_propose_an_already_represented_version(scenario, tmp_path):
    support = scenario[0] / "docs/supported-runners.md"
    support.write_text(support.read_text().replace("0.29.0", "0.30.0"))
    scenario = (scenario[0], commit(scenario[0]), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"][0]["patch"] = raw["groups"][0]["patch"].split(
        "diff --git a/docs/supported-runners.md",
    )[0]
    (bundle / "proposal.json").write_text(json.dumps(raw))
    checked = tmp_path / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 1
    )
    result = json.loads((checked / "result.json").read_text())
    assert not result["publishable"]
    artifact = json.loads((checked / "artifact.json").read_text())
    assert "represented" in artifact["groups"][0]["reason"]
    assert not artifact["patch"]
    assert not scenario[2].prs


def test_ready_rows_cannot_target_an_already_represented_variant(scenario, tmp_path):
    support = scenario[0] / "docs/supported-runners.md"
    support.write_text(
        support.read_text().replace(
            "<!-- runner-support-records:end -->",
            "| cann | 8.3.0 | vllm | a3 | 0.30.0 | 0.30.0rc1 | linux/amd64 | prepared |\n<!-- runner-support-records:end -->",
        ),
    )
    scenario = (scenario[0], commit(scenario[0]), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    raw = proposal(scenario, context)
    row = raw["groups"][0]["rows"][0]
    row.update(
        backend="cann",
        variant="a3",
        runtime="8.3.0",
        plugin_version="0.30.0rc1",
    )
    raw["groups"][0]["patch"] = raw["groups"][0]["patch"].replace(
        "pack/cuda",
        "pack/cann",
    )
    for candidate in raw["candidates"]:
        if candidate["subscription"] == "cuda/vllm":
            candidate.update(status="blocked", groups=[])
        elif candidate["subscription"] == "cann/vllm":
            candidate.update(status="ready", groups=["cuda-vllm"])
    checked, *_ = _acquire_candidate(raw, context, tmp_path / "acquisition")
    assert checked["groups"][0]["status"] == "failed"
    assert "variant" in checked["groups"][0]["reason"]


@pytest.mark.parametrize(
    "architecture,descriptor_variant,config_variant,expected,valid",
    [
        ("arm64", "v8", None, "linux/arm64", True),
        ("arm64", None, "v8", "linux/arm64", True),
        ("amd64", "v1", None, "linux/amd64", True),
        ("amd64", None, "v1", "linux/amd64", True),
        ("arm64", "v9", "v9", "linux/arm64", False),
        ("arm64", "v8", "v9", "linux/arm64", False),
        ("amd64", "v2", "v2", "linux/amd64", False),
        ("amd64", "v1", "v2", "linux/amd64", False),
    ],
)
def test_actual_registry_normalizes_only_default_platform_variants(
    tmp_path,
    architecture,
    descriptor_variant,
    config_variant,
    expected,
    valid,
):
    descriptor = {"os": "linux", "architecture": architecture}
    config = dict(descriptor)
    if descriptor_variant:
        descriptor["variant"] = descriptor_variant
    if config_variant:
        config["variant"] = config_variant
    with Registry(descriptor, config) as registry:
        row = {"base_image": registry.image, "platform": expected}
        if valid:
            measured = _registry(row, _env(tmp_path / "home"))
            assert measured["platform"] == measured["config_platform"] == expected
            assert measured["platform_digest"] == registry.child_digest
        else:
            with pytest.raises(ValueError, match="platform"):
                _registry(row, _env(tmp_path / "home"))


@pytest.mark.parametrize("architecture,variant", [("arm64", "v8"), ("amd64", "v1")])
def test_default_variant_aliases_cannot_hide_ambiguous_descriptors(
    tmp_path,
    architecture,
    variant,
):
    with Registry(
        {"os": "linux", "architecture": architecture, "variant": variant},
    ) as registry:
        manifest = json.loads(registry.objects[registry.index_digest])
        alias = copy.deepcopy(manifest["manifests"][0])
        alias["platform"].pop("variant")
        manifest["manifests"].append(alias)
        content, registry.index_digest = encoded(manifest)
        registry.objects[registry.index_digest] = content
        with pytest.raises(ValueError, match="ambiguous"):
            _registry(
                {"base_image": registry.image, "platform": "linux/" + architecture},
                _env(tmp_path / "home"),
            )


def test_missing_research_configuration_keeps_six_failure_assessments(
    scenario,
    tmp_path,
):
    prepared = prepare(scenario, tmp_path)
    output = tmp_path / "research"
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            output,
        )
        == 1
    )
    result = json.loads((output / "result.json").read_text())
    assert len(result["candidates"]) == 6
    assert {c["status"] for c in result["candidates"]} == {"failed"}
    assert not (output / "proposal.json").exists()


def test_all_represented_means_no_agent_without_model_secrets(scenario, tmp_path):
    repo = scenario[0]
    support = repo / "docs/supported-runners.md"
    rows = []
    for backend, service, variants in run.discovery.SUBSCRIPTIONS:
        for variant in variants:
            rows.append(
                f"| {backend} | {'8.3.0' if backend == 'cann' else '13.0.1'} | {service} | {variant or '-'} | {'0.30.0' if service == 'vllm' else '0.5.0'} | {'0.30.0rc1' if (backend, service) == ('cann', 'vllm') else '-'} | linux/amd64 | prepared |\n",
            )
    support.write_text(
        support.read_text().replace(
            "<!-- runner-support-records:end -->",
            "".join(rows) + "<!-- runner-support-records:end -->",
        ),
    )
    scenario = (repo, commit(repo), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    result = json.loads((prepared / "result.json").read_text())
    assert result["status"] == "unchanged"
    assert not result["ready"]
    assert {c["status"] for c in result["candidates"]} == {"unchanged"}


def validate_bundle(scenario, tmp_path, prepared):
    research = research_bundle(scenario, tmp_path, prepared)
    checked = tmp_path / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            research,
            "--output",
            checked,
        )
        == 0
    )
    return checked


def test_repeat_and_unauthorized_revision_never_require_research(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "first.json",
        )
        == 0
    )
    again = prepare(scenario, tmp_path / "again")
    result = json.loads((again / "result.json").read_text())
    assert result["status"] == "deferred"
    assert not result["ready"]
    assert len(scenario[2].prs) == 1
    event = scenario[2].comment_event("/auto-sync\nPin LMCache to 0.5.4.")
    scenario[2].permission = "read"
    unauthorized = prepare(scenario, tmp_path / "unauthorized", event)
    assert json.loads((unauthorized / "result.json").read_text())["status"] == "ignored"


@pytest.mark.parametrize("point", ["ref", "pr"])
def test_original_bundle_recovers_in_fresh_controller_process(
    scenario,
    tmp_path,
    point,
):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    original = {p.name: p.read_bytes() for p in checked.iterdir()}
    scenario[2].fail_after = point
    failed = tmp_path / "interrupted.json"
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            failed,
        )
        == 1
    )
    # A new upstream target must not replace the original recovery decision.
    scenario[2].releases["vllm-project/vllm"].insert(0, scenario[2].release("0.31.0"))
    recovered = tmp_path / "recovered.json"
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "HOME",
            "AUTO_SYNC_TOOL_BIN",
            "GITHUB_API_URL",
            "AUTO_SYNC_GITHUB_TOKEN",
            "AUTO_SYNC_BOT_LOGIN",
            "GITHUB_REPOSITORY",
        }
    }
    result = subprocess.run(  # noqa: S603 - real offline controller against local fake APIs.
        [
            sys.executable,
            "-m",
            "tools.auto_sync.run",
            "publish",
            "--repo",
            str(scenario[0]),
            "--bundle",
            str(checked),
            "--output",
            str(recovered),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(recovered.read_text())["status"] in {
        "published",
        "duplicate",
        "deferred",
    }
    assert len(scenario[2].prs) == 1
    assert {p.name: p.read_bytes() for p in checked.iterdir()} == original


def test_publication_refuses_changed_registry_and_wrong_app(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    monkeypatch.setenv("AUTO_SYNC_BOT_LOGIN", "other[bot]")
    result = tmp_path / "wrong-app.json"
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            result,
        )
        == 1
    )
    assert not scenario[2].prs
    monkeypatch.setenv("AUTO_SYNC_BOT_LOGIN", BOT)
    scenario[3].index_digest = scenario[3].child_digest
    result = tmp_path / "moved.json"
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            result,
        )
        == 1
    )
    assert not scenario[2].prs


@pytest.fixture
def pinned_tools(tmp_path, monkeypatch):
    value = os.environ.get("AUTO_SYNC_TOOL_BIN")
    assert value, (
        "Required pinned CLI unavailable; bootstrap tools and set AUTO_SYNC_TOOL_BIN"
    )
    binary = Path(value)
    for tool, argument, version in (
        ("node", "--version", "v24.14.0"),
        ("qwen", "--version", "0.25.0"),
        ("crane", "version", "0.21.9"),
    ):
        actual = subprocess.run(  # noqa: S603 - required pinned binaries.
            [str(binary / tool), argument],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=tmp_path,
            env={"PATH": str(binary) + os.pathsep + os.defpath, "HOME": str(tmp_path)},
        ).stdout.strip()
        assert actual == version
    native = subprocess.run(  # noqa: S603 - required pinned native MCP.
        [str(binary / "github-mcp-server"), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "Version: 2.0.1" in native.stdout
    if sys.platform == "darwin":
        monkeypatch.setattr(run.agent, "_process_runner", lambda: _local_cli_process)
    return binary


@pytest.mark.usefixtures("pinned_tools")
@pytest.mark.parametrize("protocol", ["openai", "openai-responses", "anthropic"])
def test_real_controller_qwen_loads_canonical_policy_skill_and_native_mcp(
    scenario,
    tmp_path,
    monkeypatch,
    protocol,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setattr(server, "FINAL", json.dumps(proposal(scenario, context)))
    with server.endpoint(
        protocol,
        calls=[("skill", {"skill": "runner-release-sync"})],
    ) as (url, requests):
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", url + "/v1")
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-model-token")
        monkeypatch.setenv("AUTO_SYNC_LLM_PROTOCOL", protocol)
        monkeypatch.setenv("AUTO_SYNC_LLM_TIMEOUT", "2")
        output = tmp_path / "research"
        assert (
            invoke(
                "research",
                "--repo",
                scenario[0],
                "--bundle",
                prepared,
                "--output",
                output,
            )
            == 0
        )
    assert len(requests) == 2
    assert "GPUStack Runner registers accelerated backends" in json.dumps(
        requests[0]["body"],
    )
    assert "Give every affected patch a disposition" in json.dumps(requests[1]["body"])
    assert "get_file_contents" in json.dumps(requests[0]["body"]["tools"])
    assert "create_pull_request" not in json.dumps(requests[0]["body"]["tools"])
    assert "fork_repository" not in json.dumps(requests[0]["body"]["tools"])
    raw = json.loads((output / "proposal.json").read_text())
    assert raw["identity"] == context["identity"]
    assert raw["groups"][0]["status"] == "ready"
    assert all("fake-model-token" not in p.read_text() for p in output.iterdir())
    assert all("fake-read-token" not in p.read_text() for p in output.iterdir())
    checked = tmp_path / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            output,
            "--output",
            checked,
        )
        == 0
    )
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "final.json",
        )
        == 0
    )
    assert len(scenario[2].prs) == 1


def test_revision_preserves_human_work_and_recovers_original_command(
    scenario,
    tmp_path,
):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "initial.json",
        )
        == 0
    )
    service = scenario[2]
    human = service.human_commit("human.txt", "Preserve this human file.\n")
    event = service.comment_event(
        "/auto-sync\nKeep the engine. Pin LMCache to 0.5.4. Update its report.",
    )
    revision_root = tmp_path / "revision"
    prepared = prepare(scenario, revision_root, event)
    bundle = research_bundle(scenario, revision_root, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    assert raw["identity"]["head_sha"] == human
    raw["groups"][0]["rows"][0]["old_engine_version"] = "0.30.0"
    raw["groups"][0]["patch"] = (
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,2 +1,3 @@\n # Runner\n [Supported runners](docs/supported-runners.md)\n+LMCache remains pinned after compatibility review.\n"
    )
    (bundle / "proposal.json").write_text(json.dumps(raw))
    checked = revision_root / "checked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 0
    )
    service.fail_after = "report"
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            revision_root / "failed.json",
        )
        == 1
    )
    commit_sha = git(scenario[0], "rev-parse", service.prs[1]["head"]["ref"])
    assert git(scenario[0], "rev-parse", commit_sha + "^") == human
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            revision_root / "recovered.json",
        )
        == 0
    )
    assert git(scenario[0], "rev-parse", service.prs[1]["head"]["ref"]) == commit_sha
    assert (
        git(scenario[0], "show", commit_sha + ":human.txt")
        == "Preserve this human file."
    )
    assert "0.5.4" in git(
        scenario[0],
        "show",
        commit_sha + ":pack/cuda/Dockerfile.vllm",
    )
    duplicate = prepare(scenario, tmp_path / "duplicate", event)
    assert json.loads((duplicate / "result.json").read_text())["status"] == "duplicate"


def test_empty_and_ambiguous_feedback_stays_bounded(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "initial.json",
        )
        == 0
    )
    event = scenario[2].comment_event("/auto-sync\n")
    empty = prepare(scenario, tmp_path / "empty", event)
    assert json.loads((empty / "result.json").read_text())["status"] == "blocked"
    event = scenario[2].comment_event(
        "/auto-sync\nChoose something compatible; versions are unspecified and conflicting.",
    )
    prepared = prepare(scenario, tmp_path / "ambiguous", event)
    bundle = research_bundle(scenario, tmp_path / "ambiguous", prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"] = []
    for candidate in raw["candidates"]:
        candidate.update(
            status="blocked",
            groups=[],
            reason="Maintainer intent is ambiguous.",
        )
    (bundle / "proposal.json").write_text(json.dumps(raw))
    checked = tmp_path / "blocked"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 0
    )
    assert json.loads((checked / "result.json").read_text())["status"] == "blocked"
    assert not json.loads((checked / "result.json").read_text())["publishable"]


def test_later_jobs_bind_default_repository_and_keep_original_output(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    original = {p.name: p.read_bytes() for p in bundle.iterdir()}
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            bundle,
        )
        == 1
    )
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == original
    monkeypatch.setenv("GITHUB_REPOSITORY", "another/repo")
    checked = tmp_path / "foreign"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 1
    )
    assert "repository" in json.loads((checked / "result.json").read_text())["reason"]
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    context = json.loads((bundle / "context.json").read_text())
    context["identity"].update(default_sha="a" * 40, head_sha="a" * 40)
    (bundle / "context.json").write_text(json.dumps(context))
    checked = tmp_path / "wrong-default"
    assert (
        invoke(
            "validate",
            "--repo",
            scenario[0],
            "--bundle",
            bundle,
            "--output",
            checked,
        )
        == 1
    )
    assert "HEAD" in json.loads((checked / "result.json").read_text())["reason"]


def test_fresh_validation_and_publication_acquire_original_head(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "initial.json",
        )
        == 0
    )
    event = scenario[2].comment_event(
        "/auto-sync\nKeep all versions. Update the report.",
    )
    root = tmp_path / "revision"
    prepared = prepare(scenario, root, event)
    bundle = research_bundle(scenario, root, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"][0]["rows"][0]["old_engine_version"] = "0.30.0"
    raw["groups"][0]["patch"] = (
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,2 +1,3 @@\n # Runner\n [Supported runners](docs/supported-runners.md)\n+Compatibility report updated.\n"
    )
    (bundle / "proposal.json").write_text(json.dumps(raw))
    fresh = tmp_path / "fresh"
    subprocess.run(  # noqa: S603 - separate clean job object store.
        [
            shutil.which("git"),
            "clone",
            "--quiet",
            "--depth=1",
            "--single-branch",
            "--branch",
            "main",
            "--",
            run.PublicUpstream().get("/repos/" + REPOSITORY)["clone_url"],
            str(fresh),
        ],
        check=True,
        capture_output=True,
    )
    head = raw["identity"]["head_sha"]
    missing = subprocess.run(  # noqa: S603 - prove this object is absent before acquisition.
        ["git", "-C", str(fresh), "cat-file", "-e", head + "^{commit}"],  # noqa: S607
        check=False,
        capture_output=True,
    )
    assert missing.returncode != 0
    validation = root / "checked"
    assert (
        invoke("validate", "--repo", fresh, "--bundle", bundle, "--output", validation)
        == 0
    )
    assert git(fresh, "rev-parse", head + "^{commit}") == head
    assert (
        invoke(
            "publish",
            "--repo",
            fresh,
            "--bundle",
            validation,
            "--output",
            root / "result.json",
        )
        == 0
    )
    assert len(scenario[2].prs) == 1


@pytest.mark.parametrize(
    "instruction,expected",
    [
        ("Use vLLM 0.31.0rc1 for CUDA.", {("cuda", "vllm", "0.31.0rc1")}),
        ("Please pin ROCm/SGLang to v0.6.0rc2.", {("rocm", "sglang", "0.6.0rc2")}),
        ("Do not use vLLM 0.31.0rc1 for CUDA.", set()),
        ("If compatible, use vLLM 0.31.0rc1 for CUDA.", set()),
        ("Consider vLLM 0.31.0rc1 for CUDA.", set()),
        ("Use vLLM 0.31.0rc1 or 0.31.0rc2 for CUDA.", set()),
        ("Use vLLM 0.31.0rc1 for CUDA.\nUse vLLM 0.31.0rc2 for CUDA.", set()),
        ("Use vLLM 0.31.0rc1 for CANN.", set()),
        ("Use vLLM 0.31.0rc1.", set()),
        ("Use vLLM 0.31.0rc1 for CUDA but keep the engine at 0.30.0.", set()),
    ],
)
def test_prerelease_permission_derives_only_from_positive_exact_comment(
    instruction,
    expected,
):
    body = "/auto-sync\n" + instruction
    context = {
        "identity": {
            "mode": "revise",
            "command_id": 10,
            "command_digest": hashlib.sha256(body.encode()).hexdigest(),
        },
        "command": {"id": 10, "body": body},
    }
    assert _permissions(context) == expected
    context["identity"]["mode"] = "discover"
    assert _permissions(context) == set()


@pytest.mark.usefixtures("pinned_tools")
@pytest.mark.parametrize(
    "forged_identity,symlink_output",
    [(False, False), (True, False), (False, True)],
)
def test_model_cannot_forge_comment_or_original_context(
    scenario,
    tmp_path,
    monkeypatch,
    forged_identity,
    symlink_output,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    output = tmp_path / "research"
    raw = proposal(scenario, context)
    changed = copy.deepcopy(context)
    changed["identity"].update(
        head_sha="f" * 40,
        command_id=999,
        command_digest="e" * 64,
    )
    changed["bot_login"] = "attacker[bot]"
    changed_discovery = copy.deepcopy(context["discovery"])
    for candidate in changed_discovery:
        candidate["status"] = "unchanged"
    if forged_identity:
        raw["identity"] = changed["identity"]
    script = (
        "from pathlib import Path;"
        f"Path({str(output / 'context.json')!r}).write_text({json.dumps(changed)!r});"
        f"Path({str(prepared / 'context.json')!r}).write_text({json.dumps(changed)!r});"
        f"Path({str(prepared / 'discovery.json')!r}).write_text({json.dumps(changed_discovery)!r});"
        f"Path({str(output / 'executable.py')!r}).write_text('untrusted');"
        "print('MUTATION_EXECUTED')"
    )
    command = shlex.join([sys.executable, "-c", script])
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_text("Do not overwrite this target.")
    if symlink_output:
        script += (
            ";import os,shutil;"
            f"shutil.rmtree({str(prepared)!r});"
            f"shutil.rmtree({str(output)!r});"
            f"os.symlink({str(foreign)!r}, {str(prepared)!r});"
            f"os.symlink({str(foreign)!r}, {str(output)!r})"
        )
        command = shlex.join([sys.executable, "-c", script])
    monkeypatch.setattr(server, "FINAL", json.dumps(raw))
    with server.endpoint(
        "openai",
        calls=[("run_shell_command", {"command": command})],
    ) as (url, requests):
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", url + "/v1")
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
        assert invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            output,
        ) == int(forged_identity)
    assert len(requests) == 2
    assert "MUTATION_EXECUTED" in json.dumps(requests[1]["body"])
    assert json.loads((prepared / "context.json").read_text()) == context
    assert json.loads((prepared / "discovery.json").read_text()) == context["discovery"]
    assert json.loads((output / "context.json").read_text()) == context
    assert not (output / "executable.py").exists()
    assert not output.is_symlink()
    assert not prepared.is_symlink()
    assert list(foreign.iterdir()) == [foreign / "sentinel"]
    assert (foreign / "sentinel").read_text() == "Do not overwrite this target."
    if forged_identity:
        assert (
            "frozen identity"
            in json.loads((output / "result.json").read_text())["reason"]
        )


def test_required_cli_missing_is_a_failure(scenario, tmp_path, monkeypatch):
    prepared = prepare(scenario, tmp_path)
    monkeypatch.delenv("AUTO_SYNC_TOOL_BIN", raising=False)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    output = tmp_path / "research"
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            output,
        )
        == 1
    )
    assert "pinned tool" in json.loads((output / "result.json").read_text())["reason"]


@pytest.mark.usefixtures("pinned_tools")
def test_exhausted_tokens_fail_before_agent_and_retain_six_outcomes(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    with ExhaustedModel() as model:
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", model.url)
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-first,fake-second")
        output = tmp_path / "research"
        assert (
            invoke(
                "research",
                "--repo",
                scenario[0],
                "--bundle",
                prepared,
                "--output",
                output,
            )
            == 1
        )
    assert len(model.requests) == 2
    assert all(not body.get("stream") for body, _ in model.requests)
    result = json.loads((output / "result.json").read_text())
    assert len(result["candidates"]) == 6
    assert {c["status"] for c in result["candidates"]} == {"failed"}
    assert "fake-first" not in json.dumps(result)
    assert "fake-second" not in json.dumps(result)


@pytest.mark.usefixtures("pinned_tools")
def test_actual_qwen_deadline_yields_complete_failure(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    real = run.agent.run_agent

    def bounded(*args, **kwargs):
        return real(*args, **kwargs, deadline=0.2)

    monkeypatch.setattr(run.agent, "run_agent", bounded)
    with server.endpoint("openai", delay=2, tools=False) as (url, _requests):
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", url + "/v1")
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
        output = tmp_path / "research"
        started = time.monotonic()
        assert (
            invoke(
                "research",
                "--repo",
                scenario[0],
                "--bundle",
                prepared,
                "--output",
                output,
            )
            == 1
        )
        assert time.monotonic() - started < 10
    result = json.loads((output / "result.json").read_text())
    assert len(result["candidates"]) == 6
    assert result["status"] == "failed"
    assert "timed out" in result["reason"]


def test_output_inside_checkout_is_rejected_without_mutation(scenario):
    output = scenario[0] / "docs"
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert (
        invoke(
            "prepare",
            "--repo",
            scenario[0],
            "--repository",
            REPOSITORY,
            "--default-sha",
            scenario[1],
            "--output",
            output,
        )
        == 1
    )
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_upstream_timeout_terminates_and_keeps_other_results(
    scenario,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(run, "HTTP_TIMEOUT", (0.05, 0.05))
    scenario[2].delays["vllm-project/vllm"] = 0.15
    started = time.monotonic()
    prepared = prepare(scenario, tmp_path)
    assert time.monotonic() - started < 3
    result = json.loads((prepared / "result.json").read_text())
    statuses = {c["subscription"]: c["status"] for c in result["candidates"]}
    assert len(statuses) == 6
    assert statuses["cuda/vllm"] == "failed"
    assert statuses["cuda/sglang"] == "blocked"
    assert "transport" in json.dumps(result)


def test_simulated_merge_prepared_dedup_and_measured_promotion(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    checked = validate_bundle(scenario, tmp_path, prepared)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "first.json",
        )
        == 0
    )
    git(scenario[0], "merge", "--ff-only", scenario[2].prs[1]["head"]["ref"])
    scenario[2].prs[1]["state"] = "closed"
    new = (scenario[0], git(scenario[0], "rev-parse", "HEAD"), *scenario[2:])
    prepared = prepare(new, tmp_path / "merged")
    result = json.loads((prepared / "result.json").read_text())
    assert (
        next(c for c in result["candidates"] if c["subscription"] == "cuda/vllm")[
            "status"
        ]
        == "unchanged"
    )
    support = (scenario[0] / "docs/supported-runners.md").read_text()
    assert "0.30.0 | - | linux/amd64 | prepared" in support
    job = {
        "backend": "cuda",
        "backend_version": "13.0.1",
        "service": "vllm",
        "backend_variant": "",
        "service_version": "0.30.0",
        "platform": "linux/amd64",
        "platform_tag": "fixture-amd64",
        "tag": "fixture",
    }
    # These are simulated validated Pack outputs, never image measurements.
    assert (
        run.discovery.promote_support(
            support,
            [job],
            {"fixture-amd64": {"vllm": "0.29.0"}},
        )
        == support
    )
    promoted = run.discovery.promote_support(
        support,
        [job],
        {"fixture-amd64": {"vllm": "0.30.0"}},
    )
    assert "0.30.0 | - | linux/amd64 | published" in promoted
    assert len(scenario[2].prs) == 1


def test_transport_redaction_masks_longest_credentials_and_preserves_types():
    value = {"status": "fake-token-long/fake-token", "ready": True, "number": 2}
    assert _redact(value, ["fake-token", "fake-token-long"]) == {
        "status": "[REDACTED]/[REDACTED]",
        "ready": True,
        "number": 2,
    }
