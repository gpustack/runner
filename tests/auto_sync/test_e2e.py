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
from tools.auto_sync.agent import ProcessResult
from tools.auto_sync.checks import _clone as clone_source
from tools.auto_sync.checks import _git as source_git
from tools.auto_sync.checks import _run as run_command
from tools.auto_sync.checks import _source_patch_checks as source_patch_checks
from tools.auto_sync.run import (
    _acquire_candidate,
    _env,
    _permissions,
    _redact,
    _registry,
    _source,
    _strip_untrusted_config,
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


def test_discovery_bind_allows_a_variant_outside_the_universe():
    # A variant dropped earlier is absent from the discovery universe; a
    # ready group may add it back when upstream support returns.
    discovery = [
        {
            "subscription": f"{backend}/{service}",
            "backend": backend,
            "service": service,
            "status": "unchanged",
            "variants": [{"variant": "", "status": "unchanged"}],
            "engine_version": "0.29.0",
            "plugin_version": None,
        }
        for backend, service, _ in run.discovery.SUBSCRIPTIONS
    ]
    cann = next(row for row in discovery if row["subscription"] == "cann/vllm")
    cann.update(
        status="needs_update",
        engine_version="0.27.1",
        plugin_version="0.27.1rc1",
        variants=[
            {"variant": "a3", "status": "needs_update"},
            {"variant": "910b", "status": "unchanged"},
        ],
    )
    context = {"identity": {"mode": "discover"}, "discovery": discovery}

    def bound(variant):
        row = {
            "backend": "cann",
            "service": "vllm",
            "variant": variant,
            "engine_version": "0.27.1",
            "plugin_version": "0.27.1rc1",
        }
        data = {
            "groups": [
                {
                    "id": "cann-vllm",
                    "status": "ready",
                    "reason": "Ready.",
                    "depends_on": [],
                    "report": {},
                    "patch": "",
                    "rows": [row],
                },
            ],
            "candidates": [
                {
                    "subscription": entry["subscription"],
                    "status": "ready"
                    if entry["subscription"] == "cann/vllm"
                    else "unchanged",
                    "groups": ["cann-vllm"]
                    if entry["subscription"] == "cann/vllm"
                    else [],
                    "reason": "Ready.",
                }
                for entry in discovery
            ],
        }
        return run._bind_discovery(data, context)["groups"][0]  # noqa: SLF001 - the bind guard is exercised directly, without the fixture stack.

    # 950 is outside the derived universe and may be added back; a3 is
    # flagged needs_update. Both rows stay ready.
    assert bound("950")["status"] == "ready"
    assert bound("a3")["status"] == "ready"
    # 910b is already represented at the candidate and cannot be proposed.
    rejected = bound("910b")
    assert rejected["status"] == "failed"
    assert "already represented or blocked" in rejected["reason"]


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
    (repo / "docs/support-records.md").write_text(
        "<!-- runner-support-records:start -->\n| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| cuda | 13.0 | vllm | - | 0.29.0 | - | linux/amd64 | prepared |\n<!-- runner-support-records:end -->\n",
    )
    (repo / "docs/supported-runners.md").write_text(
        "# Supported runners\n\n### Iluvatar CoreX\n\n"
        "| CoreX Version <br/> (Variant) | vLLM    |\n"
        "|-------------------------------|---------|\n"
        "| 4.2                           | `0.8.3` |\n",
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


def analysis(scenario, context):
    raw = json.loads(
        (Path(__file__).parent / "fixtures/proposals/analysis.json").read_text(),
    )
    raw["identity"] = context["identity"]
    revision = git(scenario[4], "rev-parse", "HEAD")
    for candidate in raw["candidates"]:
        if candidate["status"] == "analyzed":
            candidate["source_revision"] = revision
    return raw


def agent_stream(data, *extra_events):
    events = [
        *extra_events,
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(data),
        },
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def final_text(text, *extra_events):
    events = [
        *extra_events,
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": text,
        },
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def local_deepwiki(monkeypatch):
    """DeepWiki is a hosted endpoint; tests substitute the local stdio fixture."""
    monkeypatch.setattr(
        run.agent,
        "deepwiki_mcp",
        lambda: {
            "deepwiki": {
                "command": sys.executable,
                "args": [str(Path(server.__file__).parent / "mcp.py")],
                "trust": True,
            },
        },
    )


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


def patch_sources(scenario):
    source, api = scenario[4], scenario[2]
    (source / "selected.txt").write_text("old release\n")
    old = commit(source)
    (source / "selected.txt").write_text("selected release\n")
    target = commit(source)
    (source / "selected.txt").write_text("patched release\n")
    patch = git(source, "diff") + "\n"
    git(source, "checkout", "--", "selected.txt")
    git(source, "tag", "-f", "v0.29.0", old)
    for tag in ("v0.30.0", "v0.30.0rc1", "v0.5.0"):
        git(source, "tag", "-f", tag, target)
    for name in (*run.discovery.UPSTREAMS.values(), run.discovery.ASCEND):
        api.source_revisions.update(
            {
                (name, old): old,
                (name, target): target,
                (name, "v0.30.0"): target,
                (name, "v0.29.0"): old,
            },
        )
    api.source_revisions[(run.discovery.ASCEND, "v0.30.0rc1")] = target
    api.releases["vllm-project/vllm-omni"] = []
    api.source_revisions[("vllm-project/vllm-omni", old)] = old
    api.source_revisions[("vllm-project/vllm-omni", target)] = target
    git(source, "update-server-info")
    return old, target, patch


def add_source_patch(raw, path, revision, content, repository="vllm-project/vllm"):
    row = raw["groups"][0]["rows"][0]
    row["patches"] = [
        {
            "path": path,
            "disposition": "add",
            "reason": "Update the selected source.",
            "versions": [row["engine_version"]],
            "platforms": [row["platform"]],
            "sources": row["sources"],
            "source_repository": repository,
            "source_revision": revision,
        },
    ]
    lines = content.splitlines()
    raw["groups"][0]["patch"] += (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + line + "\n" for line in lines)
    )


@pytest.mark.parametrize(
    "component,claim",
    [
        ("vllm", "exact"),
        ("vllm", "old"),
        ("vllm", "repository"),
        ("vllm", "version"),
        ("vllm", "unknown"),
        ("vllm", "unavailable"),
        ("vllm", "remove"),
        ("vllm_ascend", "exact"),
        ("vllm_ascend", "old"),
        ("vllm_ascend", "version"),
        ("vllm_omni", "exact"),
        ("vllm_omni", "old"),
    ],
)
def test_patch_source_binds_selected_component(scenario, tmp_path, component, claim):
    old, target, patch_text = patch_sources(scenario)
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    # Revision mode can retain an existing engine or plugin combination.
    context["identity"].update(
        mode="revise",
        pr_number=1,
        command_id=1,
        command_digest="a" * 64,
    )
    context["command"] = {"id": 1, "body": ""}
    context["identity"]["command_digest"] = hashlib.sha256(b"").hexdigest()
    raw = proposal(scenario, context)
    row = raw["groups"][0]["rows"][0]
    name = "vllm-project/vllm"
    selected = row["engine_version"]
    if component == "vllm_ascend":
        row.update(backend="cann", variant="a3", plugin_version="0.30.0rc1")
        name, selected = run.discovery.ASCEND, row["plugin_version"]
        raw["groups"][0]["patch"] = raw["groups"][0]["patch"].replace(
            "pack/cuda/",
            "pack/cann/",
        )
        raw["candidates"][0].update(status="unchanged", groups=[])
        raw["candidates"][4].update(status="ready", groups=["cuda-vllm"])
    elif component == "vllm_omni":
        name = "vllm-project/vllm-omni"
        row["packages"].append(
            {
                "name": "vllm-omni",
                "version": target,
                "decision": "source",
                "reason": "Use the selected source pin.",
                "sources": row["sources"],
            },
        )
    decision = {
        "path": f"pack/{row['backend']}/patches/{component}/fix.patch",
        "disposition": "remove" if claim == "remove" else "add",
        "reason": "Update the selected source.",
        "versions": ["0.29.0" if claim == "version" else selected],
        "platforms": [row["platform"]],
        "sources": row["sources"],
        "source_repository": "sgl-project/sglang" if claim == "repository" else name,
        "source_revision": old
        if claim == "old"
        else None
        if claim == "unknown"
        else target,
    }
    row["patches"] = [decision]
    if claim == "unavailable":
        scenario[2].source_revisions[(name, "v0.30.0")] = None
    data, sources, _ = _acquire_candidate(raw, context, tmp_path / "acquisition")
    group = data["groups"][0]
    if claim in {"old", "repository", "version"}:
        assert group["status"] == "failed"
        assert not sources
        return
    assert group["status"] == "ready"
    work = tmp_path / "patched"
    path = work / decision["path"]
    path.parent.mkdir(parents=True)
    if claim != "remove":
        path.write_text(patch_text)
    outcomes = source_patch_checks(
        work,
        group,
        sources,
        tmp_path / "checks",
        _env(tmp_path / "home"),
    )
    assert outcomes[0]["status"] == (
        "unverified" if claim in {"unknown", "unavailable"} else "passed"
    )
    if claim == "exact":
        assert outcomes[0]["source_revision"] == target
        assert (
            tmp_path / "checks/source-1/selected.txt"
        ).read_text() == "patched release\n"
    assert scenario[3].requests
    assert all(method == "GET" for method, _, _ in scenario[2].requests)


def test_unavailable_selected_release_cannot_borrow_same_repository_source(
    scenario,
    tmp_path,
):
    old, _, patch_text = patch_sources(scenario)
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    raw = proposal(scenario, context)
    # Two backend groups share upstream objects but select different releases.
    context["identity"].update(
        mode="revise",
        pr_number=1,
        command_id=1,
        command_digest=hashlib.sha256(b"").hexdigest(),
    )
    context["command"] = {"id": 1, "body": ""}
    raw["identity"] = context["identity"]
    row = raw["groups"][0]["rows"][0]
    patch = {
        "path": "pack/cuda/patches/vllm/fix.patch",
        "disposition": "add",
        "reason": "Patch the selected source.",
        "versions": ["0.30.0"],
        "platforms": [row["platform"]],
        "sources": row["sources"],
        "source_repository": "vllm-project/vllm",
        "source_revision": old,
    }
    row["patches"] = [patch]
    other = copy.deepcopy(row)
    other.update(backend="rocm", engine_version="0.29.0")
    other["patches"][0].update(
        path="pack/rocm/patches/vllm/fix.patch",
        versions=["0.29.0"],
    )
    raw["groups"][0]["rows"].append(other)
    raw["candidates"][2].update(status="ready", groups=["cuda-vllm"])
    api = scenario[2]
    api.source_revisions[("vllm-project/vllm", "v0.30.0")] = None
    api.source_revisions[("vllm-project/vllm", "v0.29.0")] = old
    data, sources, _ = _acquire_candidate(raw, context, tmp_path / "acquisition")
    assert "vllm-project/vllm" in sources
    group = data["groups"][0]
    work = tmp_path / "patched"
    for entry in (patch, other["patches"][0]):
        path = work / entry["path"]
        path.parent.mkdir(parents=True)
        path.write_text(patch_text.replace("selected release", "old release"))
    outcomes = source_patch_checks(
        work,
        group,
        sources,
        tmp_path / "checks",
        _env(tmp_path / "home"),
    )
    assert [outcome["status"] for outcome in outcomes] == ["unverified", "passed"]
    assert group["rows"][0]["patches"][0]["source_revision"] is None
    assert group["rows"][1]["patches"][0]["source_revision"] == old


@pytest.mark.parametrize("claim", ["exact", "old"])
def test_validation_applies_patch_only_to_selected_release(scenario, tmp_path, claim):
    old, target, patch_text = patch_sources(scenario)
    prepared = prepare(scenario, tmp_path)
    research = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((research / "proposal.json").read_text())
    path = "pack/cuda/patches/vllm/fix.patch"
    if claim == "old":
        patch_text = patch_text.replace("selected release", "old release")
        old_work = tmp_path / "old-release"
        env = _env(tmp_path / "old-home")
        clone_source(scenario[4], old, old_work, env)
        source_git(env, old_work, "apply", "--check", "-", text=patch_text)
    add_source_patch(raw, path, target if claim == "exact" else old, patch_text)
    (research / "proposal.json").write_text(json.dumps(raw))
    checked = tmp_path / "checked"
    code = invoke(
        "validate",
        "--repo",
        scenario[0],
        "--bundle",
        research,
        "--output",
        checked,
    )
    artifact = json.loads((checked / "artifact.json").read_text())
    result = json.loads((checked / "result.json").read_text())
    if claim == "exact":
        assert code == 0
        assert result["publishable"] is True
        assert artifact["groups"][0]["validation"]["patches"][0]["status"] == "passed"
        assert (
            artifact["groups"][0]["validation"]["patches"][0]["source_revision"]
            == target
        )
    else:
        assert code == 1
        assert result["publishable"] is False
        assert artifact["patch"] == ""
        assert "selected component revision" in artifact["groups"][0]["reason"]


@pytest.mark.parametrize(
    "pin",
    ["exact", "short", "missing", "mismatch", "override", "unknown"],
)
def test_omni_patch_uses_effective_candidate_package_pin(scenario, tmp_path, pin):
    old, target, patch_text = patch_sources(scenario)
    repo, _, api, *_ = scenario
    selected = target[:7] if pin == "short" else target
    api.source_revisions[("vllm-project/vllm-omni", selected)] = target
    recipe = repo / "pack/cuda/Dockerfile.vllm"
    if pin not in {"missing", "unknown"}:
        recipe.write_text(
            recipe.read_text().replace(
                "FROM ",
                f"ARG VLLM_OMNI_COMMIT={old if pin == 'mismatch' else selected}\nFROM ",
            ),
        )
    if pin == "override":
        matrix = repo / "pack/matrix.yaml"
        matrix.write_text(
            matrix.read_text().replace(
                "args: [VLLM_VERSION=0.29.0]",
                f"args: [VLLM_VERSION=0.29.0, VLLM_OMNI_COMMIT={old}]",
            ),
        )
    if pin not in {"missing", "unknown"}:
        scenario = (repo, commit(repo), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    research = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((research / "proposal.json").read_text())
    if pin == "override":
        for engine in ("0.29.0", "0.30.0"):
            raw["groups"][0]["patch"] = raw["groups"][0]["patch"].replace(
                f"args: [VLLM_VERSION={engine}]",
                f"args: [VLLM_VERSION={engine}, VLLM_OMNI_COMMIT={old}]",
            )
    row = raw["groups"][0]["rows"][0]
    row["packages"].append(
        {
            "name": "vllm-omni",
            "version": selected,
            "decision": "source",
            "reason": "Retain the selected Omni source.",
            "sources": row["sources"],
        },
    )
    path = "pack/cuda/patches/vllm_omni/fix.patch"
    add_source_patch(
        raw,
        path,
        None if pin == "unknown" else target,
        patch_text,
        repository="vllm-project/vllm-omni",
    )
    (research / "proposal.json").write_text(json.dumps(raw))
    checked = tmp_path / "checked"
    code = invoke("validate", "--repo", repo, "--bundle", research, "--output", checked)
    artifact = json.loads((checked / "artifact.json").read_text())
    group = artifact["groups"][0]
    if pin in {"exact", "short", "unknown"}:
        assert code == 0
        assert group["validation"]["patches"][0]["status"] == (
            "unverified" if pin == "unknown" else "passed"
        )
    else:
        assert code == 1
        assert artifact["patch"] == ""
        assert group["status"] == "failed"
        assert "effective" in group["validation"]["error"]


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
    support = scenario[0] / "docs/support-records.md"
    support.write_text(support.read_text().replace("0.29.0", "0.30.0"))
    scenario = (scenario[0], commit(scenario[0]), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    bundle = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((bundle / "proposal.json").read_text())
    raw["groups"][0]["patch"] = raw["groups"][0]["patch"].split(
        "diff --git a/docs/support-records.md",
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
    support = scenario[0] / "docs/support-records.md"
    support.write_text(
        support.read_text().replace(
            "<!-- runner-support-records:end -->",
            "| cann | 8.3.0 | vllm | a3 | 0.30.0 | 0.30.0rc1 | linux/amd64 | prepared |\n"
            # A lagging variant keeps the candidate in needs_update, so the
            # rejection comes from the variant guard rather than the candidate.
            "| cann | 8.3.0 | vllm | 910b | 0.29.0 | 0.29.0rc1 | linux/amd64 | published |\n"
            "<!-- runner-support-records:end -->",
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


def test_prerelease_whitelist_reaches_the_research_prompt(
    scenario,
    tmp_path,
    monkeypatch,
):
    path = scenario[0] / "pack" / "prereleases.yaml"
    path.write_text("packages: [lmcache, vllm-omni]\n")
    scenario = (scenario[0], commit(scenario[0]), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    # The whitelist is frozen from the default checkout, never the candidate.
    assert context["prerelease_packages"] == ["lmcache", "vllm-omni"]
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, final_text("not json"), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            tmp_path / "research",
        )
        == 1
    )
    prompt = calls[0]["prompt"]
    assert "whitelisted keys in prerelease_packages" in prompt
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["prerelease_packages"] == ["lmcache", "vllm-omni"]


def test_component_source_trees_reach_the_research_prompt(
    scenario,
    tmp_path,
    monkeypatch,
):
    scenario[2].releases["LMCache/LMCache"] = []
    scenario[2].releases["vllm-project/vllm-omni"] = []
    dockerfile = scenario[0] / "pack/cuda/Dockerfile.vllm"
    dockerfile.write_text(
        dockerfile.read_text().replace(
            "FROM ${VLLM_BASE_IMAGE} AS vllm",
            "ARG VLLM_OMNI_COMMIT=\nFROM ${VLLM_BASE_IMAGE} AS vllm",
        ),
    )
    scenario = (scenario[0], commit(scenario[0]), *scenario[2:])
    prepared = prepare(scenario, tmp_path)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, final_text("not json"), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            tmp_path / "research",
        )
        == 1
    )
    payload = json.loads(calls[0]["prompt"].split("\n", 1)[1])
    supplied = payload["upstream_sources"]["LMCache/LMCache@0.5.4"]
    assert supplied["repository"] == "LMCache/LMCache"
    assert supplied["source"].startswith(
        "https://github.com/LMCache/LMCache/tree/",
    )
    # An empty recipe pin cannot resolve a tree; it is recorded, not fatal.
    assert payload["source_errors"]["vllm-project/vllm-omni@"] == (
        "recipe pin is empty"
    )


def test_policy_sentences_reach_stage_prompts(scenario, tmp_path, monkeypatch):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                final_text(json.dumps(analysis(scenario, context))),
                "",
                False,
                10,
            )
        return ProcessResult(0, final_text("not json"), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            tmp_path / "research",
        )
        == 1
    )
    analysis_prompt = calls[0]["prompt"]
    assert "Never block a group on patch state alone" in analysis_prompt
    assert "cite the introducing commit" in analysis_prompt
    proposal_prompt = calls[1]["prompt"]
    assert "proposal-owned" in proposal_prompt
    assert "Rotate variants with evidence" in proposal_prompt
    assert "whitelisted keys in prerelease_packages" in proposal_prompt


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
    support = repo / "docs/support-records.md"
    rows = []
    for backend, service, variants in run.discovery.SUBSCRIPTIONS:
        for variant in variants:
            rows.append(
                f"| {backend} | {'8.3' if backend == 'cann' else '13.0'} | {service} | {variant or '-'} | {'0.30.0' if service == 'vllm' else '0.5.0'} | {'0.30.0rc1' if (backend, service) == ('cann', 'vllm') else '-'} | linux/amd64 | prepared |\n",
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


def no_change_revision(scenario, tmp_path, status):
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
        "/auto-sync\nKeep all versions. Explain the outcome.",
    )
    root = tmp_path / "revision"
    prepared = prepare(scenario, root, event)
    research = research_bundle(scenario, root, prepared)
    raw = json.loads((research / "proposal.json").read_text())
    raw["groups"] = []
    for candidate in raw["candidates"]:
        candidate.update(
            status=status,
            groups=[],
            reason="No source changes are needed.",
        )
    (research / "proposal.json").write_text(json.dumps(raw))
    checked = root / "checked"
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
    return checked, event


def test_discovery_without_source_patch_remains_nonpublishable(scenario, tmp_path):
    prepared = prepare(scenario, tmp_path)
    research = research_bundle(scenario, tmp_path, prepared)
    raw = json.loads((research / "proposal.json").read_text())
    raw["groups"] = []
    for candidate in raw["candidates"]:
        candidate.update(status="unchanged", groups=[], reason="No source changes.")
    (research / "proposal.json").write_text(json.dumps(raw))
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
    assert json.loads((checked / "result.json").read_text())["publishable"] is False
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "result.json",
        )
        == 0
    )
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "no_changes"
    assert not scenario[2].prs
    assert all(method == "GET" for method, _, _ in scenario[2].requests)


@pytest.mark.parametrize("status", ["blocked", "unchanged"])
def test_valid_no_change_revision_reports_once_and_records_command(
    scenario,
    tmp_path,
    status,
):
    checked, event = no_change_revision(scenario, tmp_path, status)
    result = json.loads((checked / "result.json").read_text())
    assert result["status"] == status
    assert result["publishable"] is True
    api = scenario[2]
    head = api.current_pr(1)["head"]["sha"]
    before = len(api.requests)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "reply.json",
        )
        == 0
    )
    publication = json.loads((tmp_path / "reply.json").read_text())
    assert publication["status"] == "no_changes"
    assert publication["revalidation"]["patch"] == ""
    assert (
        publication["revalidation"]["identity"]
        == json.loads((checked / "artifact.json").read_text())["identity"]
    )
    assert api.current_pr(1)["head"]["sha"] == head
    replies = [c for c in api.comments if c["user"]["login"] == BOT]
    assert len(replies) == 1
    assert status in replies[0]["body"]
    marker = replies[0]["body"].splitlines()[0]
    record = json.loads(marker[len(run.publish.MARKER) : -4])
    assert record["identity"]["command_id"] == event["comment"]["id"]
    assert (
        record["identity"]["command_digest"]
        == hashlib.sha256(event["comment"]["body"].encode()).hexdigest()
    )
    assert record["commit_sha"] is None
    assert marker in api.prs[1]["body"]
    assert not any(
        method != "GET" and "/git/" in path for method, path, _ in api.requests[before:]
    )
    before = len(api.requests)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "duplicate.json",
        )
        == 0
    )
    assert (
        json.loads((tmp_path / "duplicate.json").read_text())["status"] == "duplicate"
    )
    assert all(method == "GET" for method, _, _ in api.requests[before:])
    repeated = prepare(scenario, tmp_path / "repeated", event)
    assert json.loads((repeated / "result.json").read_text())["ready"] is False
    assert len([c for c in api.comments if c["user"]["login"] == BOT]) == 1


@pytest.mark.parametrize("change", ["command", "authorization", "head"])
def test_no_change_revision_defers_changed_authority(scenario, tmp_path, change):
    checked, _ = no_change_revision(scenario, tmp_path, "blocked")
    assert json.loads((checked / "result.json").read_text())["publishable"] is True
    api = scenario[2]
    if change == "command":
        api.comments[-1]["body"] += "\nUse another combination."
    elif change == "authorization":
        api.permission = "read"
    else:
        api.human_commit("README.md", "A maintainer changed the head.\n")
    head = api.current_pr(1)["head"]["sha"]
    before = len(api.requests)
    assert (
        invoke(
            "publish",
            "--repo",
            scenario[0],
            "--bundle",
            checked,
            "--output",
            tmp_path / "deferred.json",
        )
        == 0
    )
    assert json.loads((tmp_path / "deferred.json").read_text())["status"] == "deferred"
    assert api.current_pr(1)["head"]["sha"] == head
    assert all(method == "GET" for method, _, _ in api.requests[before:])
    assert not any(c["user"]["login"] == BOT for c in api.comments)


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
    local_deepwiki(monkeypatch)
    monkeypatch.setattr(
        server,
        "FINALS",
        [
            json.dumps(analysis(scenario, context)),
            json.dumps(proposal(scenario, context)),
        ],
    )
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
    # Two bounded sessions: analysis, then a fresh proposal session.
    assert len(requests) == 4
    assert "GPUStack Runner registers accelerated backends" in json.dumps(
        requests[0]["body"],
    )
    assert "Give every affected patch a disposition" in json.dumps(requests[1]["body"])
    assert "get_file_contents" in json.dumps(requests[0]["body"]["tools"])
    assert "create_pull_request" not in json.dumps(requests[0]["body"]["tools"])
    assert "fork_repository" not in json.dumps(requests[0]["body"]["tools"])
    handed_off = json.loads((output / "analysis.json").read_text())
    assert handed_off["identity"] == context["identity"]
    # The proposal session receives the validated analysis, never chat history.
    opening = requests[2]["body"]
    assert handed_off["candidates"][0]["findings"] in json.dumps(opening)
    assert handed_off["candidates"][5]["unknowns"][0] in json.dumps(opening)
    history = opening.get("messages") or opening.get("input") or []
    assert all(
        item.get("role") not in {"assistant", "tool"}
        and item.get("type") != "function_call_output"
        for item in history
        if isinstance(item, dict)
    )
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


@pytest.mark.usefixtures("pinned_tools")
def test_real_controller_repairs_prose_analysis_before_proposal(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    local_deepwiki(monkeypatch)
    invalid = (
        "Here is the completed analysis.\n```json\n"
        + json.dumps(analysis(scenario, context))
        + "\n```"
    )
    monkeypatch.setattr(
        server,
        "FINALS",
        server.scripted(
            [invalid, json.dumps(analysis(scenario, context))],
            [json.dumps(proposal(scenario, context))],
        ),
    )
    with server.endpoint(
        "openai",
        calls={
            0: [("skill", {"skill": "runner-release-sync"})],
            1: [],
            2: [("skill", {"skill": "runner-release-sync"})],
        },
    ) as (url, requests):
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", url + "/v1")
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-model-token")
        monkeypatch.setenv("AUTO_SYNC_LLM_PROTOCOL", "openai")
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
    # analysis stage, one repair session, then the fresh proposal session.
    assert len(requests) == 5
    repair = json.dumps(requests[2]["body"])
    assert "Here is the completed analysis." in repair
    assert "invalid JSON" in repair
    assert "raw JSON object" in repair
    handed_off = json.loads((output / "analysis.json").read_text())
    assert handed_off["identity"] == context["identity"]
    raw = json.loads((output / "proposal.json").read_text())
    assert raw["identity"] == context["identity"]
    assert raw["groups"][0]["status"] == "ready"
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
        "proposal",
    ]


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
    assert json.loads((checked / "result.json").read_text())["publishable"] is True


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
    monkeypatch.setattr(
        server,
        "FINALS",
        [json.dumps(analysis(scenario, context)), json.dumps(raw)],
    )
    local_deepwiki(monkeypatch)
    # Rejected output must fail closed without repair sessions in this proof.
    monkeypatch.setenv("AUTO_SYNC_MAX_REPAIR_ROUNDS", "0")
    with server.endpoint(
        "openai",
        calls={0: [("run_shell_command", {"command": command})], 1: []},
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
    # Analysis runs the mutation; the fresh proposal session never repeats it.
    assert len(requests) == 3
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
@pytest.mark.parametrize("header", ['fake-header"value', "false"])
def test_turn_exhaustion_retains_redacted_research_diagnostics(
    scenario,
    tmp_path,
    monkeypatch,
    header,
):
    prepared = prepare(scenario, tmp_path)
    real = run.agent.run_agent

    def bounded(*args, **kwargs):
        return real(*args, **kwargs, max_turns=1)

    local_deepwiki(monkeypatch)
    monkeypatch.setattr(run.agent, "run_agent", bounded)
    command = shlex.join(["printf", "%s", f"fake-token {header}"])
    with server.endpoint(
        "openai",
        calls=[("run_shell_command", {"command": command})],
    ) as (url, requests):
        monkeypatch.setenv("AUTO_SYNC_LLM_URL", url + "/v1")
        monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
        monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
        monkeypatch.setenv("AUTO_SYNC_LLM_EXTRA_HEADERS", "X-Fixture=" + header)
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
    assert len(requests) == 1
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == ["analysis"]
    assert diagnostic["phases"][0]["returncode"] == 53
    assert not diagnostic["phases"][0]["timed_out"]
    events = diagnostic["phases"][0]["events"]
    assert any(event["type"] == "assistant" for event in events)
    assert "[REDACTED]" in json.dumps(events)
    decoded = json.dumps(events, ensure_ascii=False) + diagnostic["phases"][0]["stderr"]
    assert "fake-token" not in decoded
    assert "fake-header" not in decoded
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed"
    assert len(result["candidates"]) == 6
    assert {candidate["status"] for candidate in result["candidates"]} == {"failed"}


def test_streamed_error_is_reported_without_stderr_warning(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    event = {
        "type": "result",
        "subtype": "error_during_execution",
        "is_error": True,
        "error": {"message": "[API Error: Request timed out.]"},
    }
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    monkeypatch.setattr(
        run.agent,
        "run_agent",
        lambda *_a, **_k: ProcessResult(
            1,
            json.dumps(event) + "\n",
            "Warning: headless process",
        ),
    )
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
    assert result["status"] == "failed"
    assert not result["publishable"]
    assert "Request timed out" in result["reason"]
    assert "Warning:" not in result["reason"]


def test_research_reads_complete_release_records_on_demand(
    scenario,
    tmp_path,
    monkeypatch,
):
    marker = "RELEASE_BODY_MUST_STAY_AVAILABLE_OUTSIDE_INITIAL_PROMPT"
    selected = scenario[2].releases["vllm-project/vllm"][0]
    selected["body"] = marker
    selected["assets"] = [{"name": "wheel.whl", "url": "asset-metadata-marker"}]
    prepared = prepare(scenario, tmp_path)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")

    def observe(_config, **kwargs):
        prompt = kwargs["prompt"]
        data = json.loads(prompt.split("\n", 1)[1])
        record = data["upstream_sources"]["vllm-project/vllm@0.30.0"]
        assert marker not in prompt
        assert "asset-metadata-marker" not in prompt
        assert Path(record["release_notes_path"]).read_text() == marker
        saved = json.loads(Path(record["release_metadata_path"]).read_text())
        assert saved == selected
        assert record["release"]["tag_name"] == selected["tag_name"]
        assert git(Path(record["path"]), "status", "--porcelain") == ""
        return ProcessResult(1, "", "controlled diagnostic stop")

    monkeypatch.setattr(run.agent, "run_agent", observe)
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            tmp_path / "research",
        )
        == 1
    )


@pytest.mark.parametrize("limit", ["0", "-1", "2.5", "invalid"])
def test_invalid_session_token_limit_fails_before_agent(
    scenario,
    tmp_path,
    monkeypatch,
    limit,
):
    prepared = prepare(scenario, tmp_path)
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", limit)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def observe(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(1, "", "controlled diagnostic stop")

    monkeypatch.setattr(run.agent, "run_agent", observe)
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
    assert not calls
    assert (
        "positive integer" in json.loads((output / "result.json").read_text())["reason"]
    )


@pytest.mark.parametrize("limit,expected", [(None, 20_000_000), ("250000", 250_000)])
def test_session_token_limit_reaches_agent(
    scenario,
    tmp_path,
    monkeypatch,
    limit,
    expected,
):
    prepared = prepare(scenario, tmp_path)
    if limit is None:
        monkeypatch.delenv("AUTO_SYNC_MAX_SESSION_TOKENS", raising=False)
    else:
        monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", limit)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def observe(_config, **kwargs):
        calls.append(kwargs["max_session_tokens"])
        return ProcessResult(1, "", "controlled diagnostic stop")

    monkeypatch.setattr(run.agent, "run_agent", observe)
    assert (
        invoke(
            "research",
            "--repo",
            scenario[0],
            "--bundle",
            prepared,
            "--output",
            tmp_path / "research",
        )
        == 1
    )
    assert calls == [expected]


def test_token_stop_reason_survives_cli_interruption_error(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", "100")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    event = {"type": "result", "is_error": True, "error": {"message": "Interrupted"}}
    monkeypatch.setattr(
        run.agent,
        "run_agent",
        lambda *_a, **_k: ProcessResult(
            1,
            json.dumps(event),
            "session token budget exceeded",
            False,
            120,
        ),
    )
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
    reason = json.loads((output / "result.json").read_text())["reason"]
    assert "session token budget exceeded" in reason
    assert "120" in reason
    assert "100" in reason
    assert "Interrupted" not in reason


def test_research_phases_share_budget_and_deadline_with_fresh_sessions(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", "1000")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    # The clock advances only inside the mocked sessions; every other consumer
    # (API calls, clones, result assembly) observes a constant value.
    now = [10000.0]
    monkeypatch.setattr(run.time, "monotonic", lambda: now[0])
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            now[0] += 12
            return ProcessResult(
                0,
                agent_stream(
                    analysis(scenario, context),
                    {
                        "type": "assistant",
                        "message": {"content": "ANALYSIS_TRANSCRIPT_NOISE"},
                    },
                ),
                "",
                False,
                640,
            )
        now[0] += 8
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            300,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 2
    analysis_call, proposal_call = calls
    assert analysis_call["workspace"] != proposal_call["workspace"]
    assert analysis_call["runtime_dir"] != proposal_call["runtime_dir"]
    # The shared budget and deadline are consumed, never reset per phase.
    assert analysis_call["max_session_tokens"] == 1000
    assert proposal_call["max_session_tokens"] == 360
    assert "deadline" not in analysis_call
    assert proposal_call["deadline"] == run.agent.SESSION_DEADLINE - 12
    # The proposal session receives the validated analysis, never the transcript.
    assert "ANALYSIS_TRANSCRIPT_NOISE" not in proposal_call["prompt"]
    analysis_payload = json.loads(analysis_call["prompt"].split("\n", 1)[1])
    assert "analysis" not in analysis_payload
    proposal_payload = json.loads(proposal_call["prompt"].split("\n", 1)[1])
    saved = json.loads((output / "analysis.json").read_text())
    assert proposal_payload["analysis"] == saved
    assert saved["identity"] == context["identity"]
    assert (output / "proposal.json").is_file()
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
    ]
    assert diagnostic["reported_tokens"] == 940
    result = json.loads((output / "result.json").read_text())
    assert result["usage"] == {"analysis": 640, "proposal": 300, "reported": 940}
    assert result["durations"]["analysis_seconds"] == 12
    assert result["durations"]["proposal_seconds"] == 8


def test_analysis_stage_prose_output_exhausts_repair_rounds(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    fenced = (
        "Here is the completed analysis.\n```json\n"
        + json.dumps(analysis(scenario, context))
        + "\n```"
    )
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, final_text(fenced), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    # Two bounded default rounds re-run the analysis stage, then fail closed.
    assert len(calls) == 3
    assert calls[1]["workspace"] == calls[0]["workspace"]
    assert len({call["runtime_dir"] for call in calls}) == 3
    for call in calls[1:]:
        payload = json.loads(call["prompt"].split("\n", 1)[1])
        assert payload["failed_reply"] == fenced
        assert "invalid JSON" in payload["validation_error"]
        assert "schema" in payload
        assert "raw JSON object" in call["prompt"]
        # Only the proposal-stage repair may rewrite patch files.
        assert "do not edit any file" in call["prompt"]
        assert "upstream_sources" not in call["prompt"]
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
        "analysis-repair-2",
    ]
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed"
    assert "analysis repair rounds exhausted" in result["reason"]
    assert "invalid JSON" in result["reason"]
    assert {c["status"] for c in result["candidates"]} == {"failed"}
    assert not (output / "proposal.json").exists()
    assert not (output / "analysis.json").exists()


def test_zero_repair_rounds_fail_on_the_first_rejected_output(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_REPAIR_ROUNDS", "0")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    fenced = (
        "Here is the completed analysis.\n```json\n"
        + json.dumps(analysis(scenario, context))
        + "\n```"
    )
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, final_text(fenced), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 1
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed"
    assert "invalid JSON" in result["reason"]
    assert not (output / "proposal.json").exists()


@pytest.mark.parametrize("limit", ["2.5", "-1", "invalid"])
def test_invalid_repair_round_limit_fails_before_agent(
    scenario,
    tmp_path,
    monkeypatch,
    limit,
):
    prepared = prepare(scenario, tmp_path)
    monkeypatch.setenv("AUTO_SYNC_MAX_REPAIR_ROUNDS", limit)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def observe(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(1, "", "controlled diagnostic stop")

    monkeypatch.setattr(run.agent, "run_agent", observe)
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
    assert not calls
    assert (
        "non-negative integer"
        in json.loads((output / "result.json").read_text())["reason"]
    )


def test_analysis_prose_output_is_repaired_once_and_reaches_proposal(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", "1000")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    fenced = (
        "Here is the completed analysis.\n```json\n"
        + json.dumps(analysis(scenario, context))
        + "\n```"
    )
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(0, final_text(fenced), "", False, 10)
        if len(calls) == 2:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                20,
            )
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            30,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    assert calls[1]["workspace"] == calls[0]["workspace"]
    assert calls[1]["runtime_dir"] != calls[0]["runtime_dir"]
    assert calls[1]["max_session_tokens"] == 990
    repair_payload = json.loads(calls[1]["prompt"].split("\n", 1)[1])
    stage_payload = json.loads(calls[0]["prompt"].split("\n", 1)[1])
    assert repair_payload["schema"] == stage_payload["schema"]
    assert repair_payload["failed_reply"] == fenced
    assert "invalid JSON" in repair_payload["validation_error"]
    proposal_payload = json.loads(calls[2]["prompt"].split("\n", 1)[1])
    saved = json.loads((output / "analysis.json").read_text())
    assert proposal_payload["analysis"] == saved
    assert (output / "proposal.json").is_file()
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
        "proposal",
    ]
    assert set(diagnostic["phases"][1]) == set(diagnostic["phases"][0])
    assert diagnostic["reported_tokens"] == 60
    result = json.loads((output / "result.json").read_text())
    assert result["usage"] == {"analysis": 30, "proposal": 30, "reported": 60}
    assert result["durations"]["analysis_seconds"] >= 0
    assert result["durations"]["proposal_seconds"] >= 0


def test_repair_round_receives_validation_error_and_recovers(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    revision = git(scenario[4], "rev-parse", "HEAD")
    paired = analysis(scenario, context)
    target = next(c for c in paired["candidates"] if c["status"] == "analyzed")
    # The production failure: a combined engine and plugin revision string.
    target["source_revision"] = f"vllm {revision}; vllm-ascend {revision}"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(0, agent_stream(paired), "", False, 10)
        if len(calls) == 2:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_payload = json.loads(calls[1]["prompt"].split("\n", 1)[1])
    assert (
        repair_payload["validation_error"]
        == "analyzed candidate lacks an exact revision"
    )
    assert repair_payload["failed_reply"] == json.dumps(paired)
    assert "raw JSON object" in calls[1]["prompt"]
    assert "repair session of the analysis stage" in calls[1]["prompt"]
    assert "vllm-project/vllm@0.30.0" in repair_payload["supplied_evidence_keys"]
    assert 0 < calls[1]["deadline"] < run.agent.SESSION_DEADLINE
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
        "proposal",
    ]
    assert (output / "proposal.json").is_file()


def test_analysis_evidence_key_mismatch_is_repaired_with_supplied_keys(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    mismatched = analysis(scenario, context)
    target = next(c for c in mismatched["candidates"] if c["status"] == "analyzed")
    # A mismatch beyond whitespace stays rejected; only a repair can fix it.
    target["evidence"] = [
        "vllm-project/vllm@v0.30.0" if e == "vllm-project/vllm@0.30.0" else e
        for e in target["evidence"]
    ]
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(0, agent_stream(mismatched), "", False, 10)
        if len(calls) == 2:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_payload = json.loads(calls[1]["prompt"].split("\n", 1)[1])
    assert "outside the supplied sources" in repair_payload["validation_error"]
    assert repair_payload["supplied_evidence_keys"] == [
        "sgl-project/sglang@0.5.0",
        "vllm-project/vllm-ascend@0.30.0rc1",
        "vllm-project/vllm@0.30.0",
    ]
    assert "matching key from supplied_evidence_keys" in calls[1]["prompt"]
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
        "proposal",
    ]
    assert (output / "proposal.json").is_file()


def test_analysis_evidence_key_whitespace_is_normalized_without_repair(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    # The production failure: the model writes a space into the supplied key
    # in every session, so repair rounds could never correct it.
    spaced = analysis(scenario, context)
    target = next(c for c in spaced["candidates"] if c["status"] == "analyzed")
    target["evidence"] = [
        "vllm-project/vllm @0.30.0" if e == "vllm-project/vllm@0.30.0" else e
        for e in target["evidence"]
    ]
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(0, agent_stream(spaced), "", False, 10)
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 2
    saved = json.loads((output / "analysis.json").read_text())
    analyzed = next(c for c in saved["candidates"] if c["status"] == "analyzed")
    assert "vllm-project/vllm@0.30.0" in analyzed["evidence"]
    assert (output / "proposal.json").is_file()


def test_repair_rounds_exhaust_the_shared_token_budget(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", "100")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    fenced = "Certainly!\n```json\n{}\n```"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, final_text(fenced), "", False, 60)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    # The first repair spends the remaining budget; no further round starts.
    assert len(calls) == 2
    reason = json.loads((output / "result.json").read_text())["reason"]
    assert "session token budget exhausted" in reason
    assert "120 reported tokens reached the 100 limit" in reason


def test_repair_rounds_exhaust_the_shared_deadline_before_proposal(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    monkeypatch.setattr(run.agent, "SESSION_DEADLINE", 20)
    # The clock advances only inside the mocked sessions.
    now = [10000.0]
    monkeypatch.setattr(run.time, "monotonic", lambda: now[0])
    fenced = "Certainly!\n```json\n{}\n```"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        now[0] += 12
        return ProcessResult(0, final_text(fenced), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    # The first repair fits in the remaining deadline; the second cannot start.
    assert len(calls) == 2
    assert calls[1]["deadline"] == 8
    reason = json.loads((output / "result.json").read_text())["reason"]
    assert "research stage deadline exhausted by the analysis stage" in reason
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "analysis-repair-1",
    ]


def test_proposal_stage_prose_output_is_repaired_once(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", "1000")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    fenced = (
        "The proposal follows.\n```json\n"
        + json.dumps(proposal(scenario, context))
        + "\n```"
    )
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        if len(calls) == 2:
            return ProcessResult(0, final_text(fenced), "", False, 10)
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    assert calls[2]["workspace"] == calls[1]["workspace"]
    assert calls[2]["runtime_dir"] != calls[1]["runtime_dir"]
    assert calls[2]["max_session_tokens"] == 980
    assert calls[2]["deadline"] < run.agent.SESSION_DEADLINE
    repair_payload = json.loads(calls[2]["prompt"].split("\n", 1)[1])
    assert repair_payload["failed_reply"] == fenced
    assert "invalid JSON" in repair_payload["validation_error"]
    stage_payload = json.loads(calls[1]["prompt"].split("\n", 1)[1])
    assert repair_payload["schema"] == stage_payload["schema"]
    assert "repair session of the proposal stage" in calls[2]["prompt"]
    # Analysis evidence keys are meaningless for a proposal-stage repair.
    assert "supplied_evidence_keys" not in repair_payload
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
        "proposal-repair-1",
    ]
    result = json.loads((output / "result.json").read_text())
    assert result["usage"] == {"analysis": 10, "proposal": 20, "reported": 30}
    assert (output / "proposal.json").is_file()


def test_proposal_patch_file_is_inlined_by_the_controller(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    draft = proposal(scenario, context)
    patch = draft["groups"][0].pop("patch")
    draft["groups"][0]["patch_file"] = "patches/candidate.patch"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        target = kwargs["workspace"] / draft["groups"][0]["patch_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patch)
        return ProcessResult(0, agent_stream(draft), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 2
    assert "group.patch_file" in calls[1]["prompt"]
    saved = json.loads((output / "proposal.json").read_text())
    assert saved["groups"][0]["patch"] == patch
    assert "patch_file" not in saved["groups"][0]


def test_proposal_patch_file_outside_workspace_is_repaired(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    escaped = proposal(scenario, context)
    escaped["groups"][0].pop("patch")
    escaped["groups"][0]["patch_file"] = "../escape.patch"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        if len(calls) == 2:
            return ProcessResult(0, agent_stream(escaped), "", False, 10)
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_payload = json.loads(calls[2]["prompt"].split("\n", 1)[1])
    assert "resolves outside the base directory" in repair_payload["validation_error"]
    assert repair_payload["failed_reply"] == json.dumps(escaped)
    assert (output / "proposal.json").is_file()


def test_proposal_patch_file_in_stripped_directory_is_repaired(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    # The production failure: the patch lands in a startup configuration
    # directory that a repair session strips before it runs.
    stripped = proposal(scenario, context)
    patch = stripped["groups"][0].pop("patch")
    stripped["groups"][0]["patch_file"] = ".qwen/tmp/candidate.patch"
    truncated = json.dumps(stripped)[:100]
    relocated = proposal(scenario, context)
    relocated["groups"][0].pop("patch")
    relocated["groups"][0]["patch_file"] = "patches/candidate.patch"
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        workspace = Path(kwargs["workspace"])
        if len(calls) == 2:
            target = workspace / stripped["groups"][0]["patch_file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch)
            return ProcessResult(0, final_text(truncated), "", False, 10)
        if len(calls) == 3:
            # The repair session starts after the strip removed the patch file.
            assert not (workspace / ".qwen").exists()
            return ProcessResult(0, agent_stream(stripped), "", False, 10)
        target = workspace / relocated["groups"][0]["patch_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patch)
        return ProcessResult(0, agent_stream(relocated), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 4
    repair_payload = json.loads(calls[3]["prompt"].split("\n", 1)[1])
    assert "cannot read patch_file" in repair_payload["validation_error"]
    assert repair_payload["failed_reply"] == json.dumps(stripped)
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
        "proposal-repair-1",
        "proposal-repair-2",
    ]
    saved = json.loads((output / "proposal.json").read_text())
    assert saved["groups"][0]["patch"] == patch
    assert "patch_file" not in saved["groups"][0]


def test_proposal_non_url_source_is_repaired_with_the_offending_entry(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    # The production failure: the model mirrors the analysis stage's local and
    # repository-relative evidence paths into proposal sources lists.
    corrupted = proposal(scenario, context)
    corrupted["groups"][0]["rows"][0]["sources"].append("pack/cuda/Dockerfile.vllm")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        if len(calls) == 2:
            return ProcessResult(0, agent_stream(corrupted), "", False, 10)
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_payload = json.loads(calls[2]["prompt"].split("\n", 1)[1])
    assert (
        "invalid evidence source URL: 'pack/cuda/Dockerfile.vllm'"
        in repair_payload["validation_error"]
    )
    assert repair_payload["failed_reply"] == json.dumps(corrupted)
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
        "proposal-repair-1",
    ]
    assert (output / "proposal.json").is_file()


def broken_patch(scenario, context):
    raw = proposal(scenario, context)
    group = raw["groups"][0]
    group["patch"] = group["patch"].replace("\n@@", "\n @@")
    return raw


def whitespace_patch(scenario, context):
    # Trailing whitespace on an added line passes plain git apply but fails
    # the --whitespace=error applications in validation and publication.
    raw = proposal(scenario, context)
    group = raw["groups"][0]
    lines = group["patch"].splitlines(keepends=True)
    added = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("+") and not line.startswith("+++")
    )
    lines[added] = lines[added].rstrip("\n") + " \n"
    group["patch"] = "".join(lines)
    return raw


def test_proposal_stage_inapplicable_patch_is_repaired_once(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        if len(calls) == 2:
            return ProcessResult(
                0,
                agent_stream(broken_patch(scenario, context)),
                "",
                False,
                10,
            )
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_payload = json.loads(calls[2]["prompt"].split("\n", 1)[1])
    assert "cuda-vllm patch does not apply" in repair_payload["validation_error"]
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
        "proposal-repair-1",
    ]
    assert (output / "proposal.json").is_file()


def test_proposal_repair_rewrites_a_rejected_patch_file(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    # The production failure: a patch generated against a tree where another
    # group's patch was already applied no longer applies to the frozen head.
    # The repair session corrects it by rewriting the referenced patch file
    # in the reused workspace instead of returning an inline patch.
    draft = proposal(scenario, context)
    patch = draft["groups"][0].pop("patch")
    draft["groups"][0]["patch_file"] = "patches/candidate.patch"
    broken = patch.replace("\n@@", "\n @@")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        target = Path(kwargs["workspace"]) / draft["groups"][0]["patch_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if len(calls) == 2:
            target.write_text(broken)
        else:
            target.write_text(patch)
        return ProcessResult(0, agent_stream(draft), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    repair_prompt = calls[2]["prompt"]
    assert "rewrite the patch files referenced by patch_file entries" in repair_prompt
    repair_payload = json.loads(repair_prompt.split("\n", 1)[1])
    assert "cuda-vllm patch does not apply" in repair_payload["validation_error"]
    assert repair_payload["failed_reply"] == json.dumps(draft)
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
        "proposal-repair-1",
    ]
    saved = json.loads((output / "proposal.json").read_text())
    assert saved["groups"][0]["patch"] == patch
    assert "patch_file" not in saved["groups"][0]


@pytest.mark.parametrize("breaker", [broken_patch, whitespace_patch])
def test_inapplicable_patch_fails_research_without_repair_rounds(
    scenario,
    tmp_path,
    monkeypatch,
    breaker,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_REPAIR_ROUNDS", "0")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        return ProcessResult(
            0,
            agent_stream(breaker(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert "cuda-vllm patch does not apply" in result["reason"]
    assert [
        phase["name"]
        for phase in json.loads(
            (output / "diagnostics.json").read_text(),
        )["phases"]
    ] == ["analysis", "proposal"]


def test_repair_session_strips_model_created_startup_config(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []
    leftover = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        workspace = Path(kwargs["workspace"])
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        if len(calls) == 2:
            # A model session can leave startup configuration behind; it must
            # neither steer nor block the fresh repair session's preflight.
            (workspace / ".qwen").mkdir()
            (workspace / ".env").write_text("TOKEN=steal-me\n")
            return ProcessResult(
                0,
                agent_stream(broken_patch(scenario, context)),
                "",
                False,
                10,
            )
        leftover.append((workspace / ".qwen").exists() or (workspace / ".env").exists())
        return ProcessResult(
            0,
            agent_stream(proposal(scenario, context)),
            "",
            False,
            10,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 3
    assert leftover == [False]


def test_strip_untrusted_config_never_traverses_symlinks(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real = workspace / ".claude"
    real.mkdir()
    (real / "settings.json").write_text("{}\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "settings.json"
    protected.write_text("{}\n")
    _strip_untrusted_config(workspace)
    assert not (real / "settings.json").exists()
    assert real.is_dir()  # the trusted skills checkout shares the directory
    real.rmdir()

    # A hostile symlink must be unlinked itself, never traversed.
    (workspace / ".claude").symlink_to(outside)
    _strip_untrusted_config(workspace)
    assert not (workspace / ".claude").exists()
    assert protected.is_file()

    # A plain file cannot contain settings and must not crash the strip.
    (workspace / ".claude").write_text("junk\n")
    _strip_untrusted_config(workspace)
    assert (workspace / ".claude").is_file()


@pytest.mark.parametrize("corrupt", ["ready", "revision", "evidence"])
def test_forged_analysis_never_reaches_proposal_stage(
    scenario,
    tmp_path,
    monkeypatch,
    corrupt,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    # Validation stays strict on its own; repair recovery is tested separately.
    monkeypatch.setenv("AUTO_SYNC_MAX_REPAIR_ROUNDS", "0")
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    forged = analysis(scenario, context)
    target = next(c for c in forged["candidates"] if c["status"] == "analyzed")
    if corrupt == "ready":
        target["status"] = "ready"
    elif corrupt == "revision":
        target["source_revision"] = "e" * 40
    else:
        target["evidence"] = ["/etc/passwd"]
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        return ProcessResult(0, agent_stream(forged), "", False, 10)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 1
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed"
    assert not (output / "proposal.json").exists()


def test_proposal_stage_failure_keeps_analysis_artifact(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                10,
            )
        return ProcessResult(1, "", "proposal session exploded", False, 20)

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    assert len(calls) == 2
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert [phase["name"] for phase in diagnostic["phases"]] == [
        "analysis",
        "proposal",
    ]
    assert diagnostic["phases"][1]["returncode"] == 1
    assert diagnostic["reported_tokens"] == 30
    saved = json.loads((output / "analysis.json").read_text())
    assert saved["identity"] == context["identity"]
    assert not (output / "proposal.json").exists()


@pytest.mark.parametrize(
    "limit,analysis_tokens,proposal_tokens,proposal_fails,expected",
    [
        # Analysis alone exhausts the shared budget before the proposal starts.
        ("100", 100, None, False, "100 reported tokens reached the 100 limit"),
        # Cumulative usage across both phases is what trips the budget.
        ("100", 60, 50, True, "110 reported tokens reached the 100 limit"),
    ],
)
def test_shared_session_token_budget_spans_both_phases(
    scenario,
    tmp_path,
    monkeypatch,
    limit,
    analysis_tokens,
    proposal_tokens,
    proposal_fails,
    expected,
):
    prepared = prepare(scenario, tmp_path)
    context = json.loads((prepared / "context.json").read_text())
    monkeypatch.setenv("AUTO_SYNC_MAX_SESSION_TOKENS", limit)
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    calls = []

    def phase(_config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ProcessResult(
                0,
                agent_stream(analysis(scenario, context)),
                "",
                False,
                analysis_tokens,
            )
        return ProcessResult(
            1 if proposal_fails else 0,
            "" if proposal_fails else agent_stream(proposal(scenario, context)),
            "Interrupted",
            False,
            proposal_tokens,
        )

    monkeypatch.setattr(run.agent, "run_agent", phase)
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
    if proposal_tokens is None:
        assert len(calls) == 1
    reason = json.loads((output / "result.json").read_text())["reason"]
    assert expected in reason


def test_final_artifact_redaction_preserves_nested_proposal(
    scenario,
    tmp_path,
    monkeypatch,
):
    prepared = prepare(scenario, tmp_path)
    nested = {"identity": {"pr_number": None}, "echo": "null"}
    event = {"type": "result", "result": json.dumps(nested)}
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    monkeypatch.setenv("AUTO_SYNC_LLM_EXTRA_HEADERS", "X-Fixture=null")
    monkeypatch.setattr(
        run.agent,
        "run_agent",
        lambda *_a, **_k: ProcessResult(53, json.dumps(event) + "\n", "failed"),
    )
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
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert json.loads(diagnostic["phases"][0]["events"][0]["result"]) == {
        "identity": {"pr_number": None},
        "echo": "[REDACTED]",
    }


def test_diagnostics_keep_one_event_per_protocol_frame(scenario, tmp_path, monkeypatch):
    prepared = prepare(scenario, tmp_path)
    stdout = json.dumps(
        {"type": "assistant", "message": {"content": "a\u2028b\u2029c\u0085d"}},
        ensure_ascii=False,
    )
    monkeypatch.setenv("AUTO_SYNC_LLM_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AUTO_SYNC_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("AUTO_SYNC_LLM_AUTH_TOKEN", "fake-token")
    monkeypatch.setattr(
        run.agent,
        "run_agent",
        lambda *_a, **_k: ProcessResult(
            53,
            stdout + "\nnot json\n",
            "stale",
        ),
    )
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
    diagnostic = json.loads((output / "diagnostics.json").read_text())
    assert diagnostic["phases"][0]["returncode"] == 53
    assert diagnostic["phases"][0]["events"] == [
        {"type": "assistant", "message": {"content": "a\u2028b\u2029c\u0085d"}},
        {"type": "unparsed", "text": "not json"},
    ]


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

    local_deepwiki(monkeypatch)
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
    support = (scenario[0] / "docs/support-records.md").read_text()
    assert "0.30.0 | - | linux/amd64 | prepared" in support
    job = {
        "backend": "cuda",
        "backend_version": "13.0",
        "original_backend_version": "13.0.1",
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
