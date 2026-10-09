"""Checks use frozen trusted code and never execute candidate configuration."""

import copy
import difflib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.auto_sync.checks import report_digest, validate_candidate, verify_artifact
from tools.auto_sync.discovery import promote_support
from tools.auto_sync.proposal import ProposalError

FIXTURE = Path(__file__).parent / "fixtures/proposals/ready.json"
SUPPORT = "docs/support-records.md"
SUPPORT_START = "<!-- runner-support-records:start -->\n| Backend | Runtime | Service | Variant | Engine | Plugin | Platforms | Status |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n"
SUPPORT_END = "<!-- runner-support-records:end -->\n"


def support_row(engine="0.30.0", platforms="linux/amd64"):
    return f"| cuda | 13.0 | vllm | - | {engine} | - | {platforms} | prepared |\n"


def git(repo, *args):
    return subprocess.run(  # noqa: S603 - local fixture repositories only.
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],  # noqa: S607 - local fixture repositories only.
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "pack/cuda").mkdir(parents=True)
    (repo / "pack/cuda/Dockerfile.vllm").write_text(
        "ARG VLLM_VERSION=0.29.0\nARG CUDA_VERSION=13.0.1\nARG VLLM_BASE_IMAGE=vllm/vllm-openai:v${VLLM_VERSION}\nARG PYTHON_VERSION=3.12\nARG VLLM_LMCACHE_VERSION=0.5.4\nFROM ${VLLM_BASE_IMAGE} AS vllm\n",
    )
    (repo / "pack/matrix.yaml").write_text(
        "rules:\n  - backend: cuda\n    services: [vllm]\n    platforms: [linux/amd64]\n    args: [VLLM_VERSION=0.29.0]\n",
    )
    (repo / "README.md").write_text(
        "# Runner\n[Supported runners](docs/supported-runners.md)\n",
    )
    (repo / "docs").mkdir()
    (repo / SUPPORT).write_text(SUPPORT_START + support_row("0.29.0") + SUPPORT_END)
    (repo / "gpustack_runner").mkdir()
    (repo / "gpustack_runner/runner.py.json").write_text("[]\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    proposal = json.loads(FIXTURE.read_text())
    sha = git(repo, "rev-parse", "HEAD")
    proposal["identity"].update(default_sha=sha, head_sha=sha)
    return repo, proposal


def diff(path, old, new):
    return f"diff --git a/{path} b/{path}\n" + "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="a/" + path,
            tofile="b/" + path,
        ),
    )


def validate(candidate, **kwargs):
    repo, proposal = candidate
    return validate_candidate(repo, proposal, proposal["identity"], **kwargs)


def test_clean_validation_binds_patch_report_and_leaves_input_untouched(candidate):
    repo, proposal = candidate
    before = copy.deepcopy(proposal)
    result = validate(candidate)
    assert result["groups"][0]["status"] == "ready"
    assert result["patch"] == proposal["groups"][0]["patch"]
    assert len(result["patch_digest"]) == 64
    assert len(result["report_digest"]) == 64
    assert result["identity"] == proposal["identity"]
    assert proposal == before
    assert git(repo, "status", "--porcelain") == ""
    assert "0.29.0" in (repo / "pack/cuda/Dockerfile.vllm").read_text()


def test_support_promotes_using_the_actual_pack_runtime_line(candidate, tmp_path):
    repo, _ = candidate
    checked = validate(candidate)
    assert checked["patch"]
    subprocess.run(  # noqa: S603 - validated patch in a disposable fixture.
        ["git", "-C", str(repo), "apply", "-"],  # noqa: S607
        input=checked["patch"],
        text=True,
        check=True,
        capture_output=True,
    )
    output = tmp_path / "expanded"
    subprocess.run(  # noqa: S603 - trusted Pack expansion with fixed fixture data.
        ["bash", str(Path(__file__).resolve().parents[2] / "pack/expand_matrix.sh")],  # noqa: S607
        env={
            **os.environ,
            "INPUT_BACKEND": "cuda",
            "INPUT_TARGET": "vllm",
            "INPUT_FOR_RELEASE": "true",
            "INPUT_ARGS": "",
            "INPUT_POST_OPERATION": "",
            "INPUT_WORKSPACE": str(repo / "pack"),
            "INPUT_TEMPDIR": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    expanded = dict(line.split("=", 1) for line in output.read_text().splitlines())
    jobs = json.loads(expanded["build_jobs"])
    assert jobs[0]["backend_version"] == "13.0"
    assert jobs[0]["original_backend_version"] == "13.0.1"
    support = (repo / SUPPORT).read_text()
    measured = {jobs[0]["platform_tag"]: {"vllm": "0.30.0"}}
    assert "0.30.0 | - | linux/amd64 | published" in promote_support(
        support,
        jobs,
        measured,
    )
    assert promote_support(support, jobs, {}) == support


def test_new_support_record_rejects_a_full_runtime_patch_version(candidate):
    group = candidate[1]["groups"][0]
    group["patch"] = group["patch"].replace(
        "+| cuda | 13.0 |",
        "+| cuda | 13.0.1 |",
    )
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert "runtime line" in result["groups"][0]["validation"]["error"]


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/pack.yml",
        "AGENTS.md",
        ".qwen/settings.json",
        ".env",
        "tools/auto_sync/checks.py",
        "gpustack_runner/runner.py.json",
        "pack/dependencies.json",
        "pack/dtk/Dockerfile.vllm",
        "pack/cuda/Dockerfile.sglang",
        "../escape",
        "/absolute/escape",
    ],
)
def test_policy_generated_metadata_and_unselected_paths_rejected(candidate, path):
    candidate[1]["groups"][0]["patch"] = diff(path, "old\n", "new\n")
    with pytest.raises(ProposalError, match="path"):
        validate(candidate)


@pytest.mark.parametrize("mode", ["120000", "100755"])
def test_candidate_symlink_and_executable_modes_rejected(candidate, mode):
    group = candidate[1]["groups"][0]
    group["patch"] = (
        f"diff --git a/README.md b/README.md\nold mode 100644\nnew mode {mode}\n"
    )
    with pytest.raises(ProposalError, match="mode"):
        validate(candidate)


def test_base_symlink_escape_is_rejected_without_touching_target(candidate, tmp_path):
    repo, proposal = candidate
    target = tmp_path / "outside"
    target.write_text("protected\n")
    recipe = repo / "pack/cuda/Dockerfile.vllm"
    recipe.unlink()
    recipe.symlink_to(target)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "symlink")
    sha = git(repo, "rev-parse", "HEAD")
    proposal["identity"].update(default_sha=sha, head_sha=sha)
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert "symlink" in result["groups"][0]["validation"]["error"]
    assert result["patch"] == ""
    assert target.read_text() == "protected\n"


@pytest.mark.parametrize(
    "argument",
    [
        "VLLM_VERSION=$(touch SENTINEL)",
        "VLLM_VERSION=0.30.0;touch SENTINEL",
        "VLLM_VERSION=`touch SENTINEL`",
        "VLLM_VERSION=${TOKEN}",
        "VLLM_VERSION=0.30.0\nexport X=1",
    ],
)
def test_matrix_injection_fails_without_execution(candidate, argument):
    repo, proposal = candidate
    old = (repo / "pack/matrix.yaml").read_text()
    new = (
        json.dumps(
            {"rules": [{"backend": "cuda", "services": ["vllm"], "args": [argument]}]},
        )
        + "\n"
    )
    proposal["groups"][0]["patch"] = diff("pack/matrix.yaml", old, new)
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert result["patch"] == ""
    assert "matrix" in result["groups"][0]["validation"]["error"]
    assert not (repo / "SENTINEL").exists()


def test_candidate_hook_settings_and_tests_are_never_run(candidate, tmp_path):
    repo, _ = candidate
    sentinel = tmp_path / "executed"
    hook = repo / ".git/hooks/post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
    hook.chmod(0o755)
    (repo / ".qwen").mkdir()
    (repo / ".qwen/settings.json").write_text(
        '{"hooks":{"PreToolUse":"touch executed"}}',
    )
    (repo / "tests").mkdir()
    (repo / "tests/conftest.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "candidate settings")
    sha = git(repo, "rev-parse", "HEAD")
    candidate[1]["identity"].update(default_sha=sha, head_sha=sha)
    assert validate(candidate)["groups"][0]["status"] == "ready"
    assert not sentinel.exists()


def test_check_processes_do_not_receive_credentials(candidate, monkeypatch):
    monkeypatch.setenv("AUTO_SYNC_MODEL_TOKEN", "fake-model-secret")
    monkeypatch.setenv("GH_TOKEN", "fake-write-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-write-secret")
    original = subprocess.run
    environments = []

    def observe(*args, **kwargs):
        environments.append(kwargs["env"])
        assert kwargs.get("shell", False) is False
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", observe)
    validate(candidate)
    assert environments
    assert all("fake-" not in json.dumps(env) for env in environments)


def test_wrong_source_sha_fails_before_changes(candidate):
    candidate[1]["identity"]["head_sha"] = "d" * 40
    with pytest.raises(ProposalError, match="revision"):
        validate(candidate)


def test_failed_group_keeps_report_independent_ready_group_survives(candidate):
    _, proposal = candidate
    blocked = copy.deepcopy(proposal["groups"][0])
    blocked.update(
        id="blocked",
        status="blocked",
        reason="Missing upstream compatibility",
        report="Keep this blocker visible.",
        patch="",
    )
    proposal["groups"].append(blocked)
    proposal["candidates"][0]["groups"].append("blocked")
    result = validate(candidate)
    assert [g["status"] for g in result["groups"]] == ["ready", "blocked"]
    assert result["groups"][1]["report"] == "Keep this blocker visible."
    assert result["patch"] == proposal["groups"][0]["patch"]


def test_patch_context_failure_is_reported_not_published(candidate):
    candidate[1]["groups"][0]["patch"] = candidate[1]["groups"][0]["patch"].replace(
        "0.29.0",
        "9.99.0",
    )
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert result["patch"] == ""
    assert result["candidates"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("engine_version", "0.31.0"),
        ("runtime", "12.9.1"),
        ("base_image", "vllm/vllm-openai:invented"),
        ("platform", "linux/arm64"),
        ("python", "3.11"),
    ],
)
def test_ready_report_must_match_proposed_matrix_and_recipe(candidate, field, value):
    row = candidate[1]["groups"][0]["rows"][0]
    row[field] = value
    if field == "platform":
        row["manifest"].update(platform=value, config_platform=value)
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert result["patch"] == ""


def test_matrix_override_cannot_hide_an_old_engine_pin(candidate):
    group = candidate[1]["groups"][0]
    group["patch"] = group["patch"].split("diff --git a/pack/matrix.yaml")[0]
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"


def test_additional_package_pin_must_match_recipe(candidate):
    candidate[1]["groups"][0]["rows"][0]["packages"][0]["version"] = "0.9.9"
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"


def test_two_ready_groups_are_applied_and_reported(candidate):
    repo, proposal = candidate
    second = copy.deepcopy(proposal["groups"][0])
    second.update(
        id="docs",
        patch=diff(
            "README.md",
            (repo / "README.md").read_text(),
            (repo / "README.md").read_text() + "Prepared update.\n",
        ),
    )
    proposal["groups"].append(second)
    proposal["candidates"][0]["groups"].append("docs")
    result = validate(candidate)
    assert [g["status"] for g in result["groups"]] == ["ready", "ready"]
    assert "Prepared update." in result["patch"]


def test_rejected_dependency_keeps_dependent_patch_out(candidate):
    _, proposal = candidate
    prerequisite = copy.deepcopy(proposal["groups"][0])
    prerequisite.update(
        id="prerequisite",
        status="blocked",
        patch="",
        report="Missing upstream source.",
    )
    proposal["groups"].insert(0, prerequisite)
    proposal["groups"][1]["depends_on"] = ["prerequisite"]
    proposal["candidates"][0]["groups"].append("prerequisite")
    result = validate(candidate)
    assert [g["status"] for g in result["groups"]] == ["blocked", "blocked"]
    assert result["patch"] == ""


def test_support_cannot_claim_a_prepared_image_is_published(candidate):
    repo, proposal = candidate
    text = (repo / SUPPORT).read_text()
    new = text.replace(
        "<!-- runner-support-records:end -->",
        "| cuda | 13.0 | vllm | - | 0.30.0 | - | linux/amd64 | published |\n<!-- runner-support-records:end -->",
    )
    proposal["groups"][0]["patch"] = proposal["groups"][0]["patch"].split(
        "diff --git a/docs/",
    )[0] + diff(SUPPORT, text, new)
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert "published" in result["groups"][0]["validation"]["error"]


def test_source_patch_application_uses_exact_revision(candidate, tmp_path):
    repo, proposal = candidate
    source = tmp_path / "upstream"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "engine.py").write_text("value = 1\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "source")
    revision = git(source, "rev-parse", "HEAD")
    patch_path = "pack/cuda/patches/vllm/fix.patch"
    patch_text = diff("engine.py", "value = 1\n", "value = 2\n")
    target = repo / patch_path
    target.parent.mkdir(parents=True)
    target.write_text(patch_text)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "patch")
    sha = git(repo, "rev-parse", "HEAD")
    proposal["identity"].update(default_sha=sha, head_sha=sha)
    proposal["groups"][0]["rows"][0]["patches"] = [
        {
            "path": patch_path,
            "disposition": "retain",
            "reason": "Existing fix",
            "versions": ["0.30.0"],
            "platforms": ["linux/amd64"],
            "sources": ["https://github.com/vllm-project/vllm/issues/1"],
            "source_repository": "vllm-project/vllm",
            "source_revision": revision,
        },
    ]
    result = validate(candidate, sources={"vllm-project/vllm": source})
    assert result["groups"][0]["validation"]["patches"][0]["status"] == "passed"
    # Available HEAD differs; the declared revision must still govern the check.
    (source / "engine.py").write_text("value = 100\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "new source")
    assert (
        validate(candidate, sources={"vllm-project/vllm": source})["groups"][0][
            "status"
        ]
        == "ready"
    )
    target.write_text(patch_text.replace("value = 1", "value = 77"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "bad patch")
    sha = git(repo, "rev-parse", "HEAD")
    proposal["identity"].update(default_sha=sha, head_sha=sha)
    assert (
        validate(candidate, sources={"vllm-project/vllm": source})["groups"][0][
            "status"
        ]
        == "failed"
    )
    assert "value = 100" in (source / "engine.py").read_text()
    result = validate(candidate)
    assert result["groups"][0]["validation"]["patches"][0]["status"] == "unverified"


def test_verified_artifact_can_be_rechecked_on_a_clean_publication_runner(candidate):
    result = validate(candidate)
    raw = verify_artifact(result, candidate[1]["identity"])
    assert raw == candidate[1]
    rechecked = validate_candidate(candidate[0], raw, raw["identity"])
    assert rechecked == result


@pytest.mark.parametrize(
    "change",
    ["patch", "report", "status", "identity", "digest", "rehashed_extra_patch"],
)
def test_publication_rejects_tampered_artifact(candidate, change):
    result = validate(candidate)
    if change == "patch":
        result["patch"] += "fabricated"
    elif change == "report":
        result["groups"][0]["report"] += "fabricated"
    elif change == "status":
        result["groups"][0]["status"] = "unchanged"
    elif change == "identity":
        result["identity"]["head_sha"] = "d" * 40
    elif change == "digest":
        result["patch_digest"] = "d" * 64
    else:
        result["patch"] += diff("AGENTS.md", "old\n", "new\n")
        result["patch_digest"] = hashlib.sha256(result["patch"].encode()).hexdigest()
        result["report_digest"] = report_digest(result)
    with pytest.raises(ProposalError):
        verify_artifact(result, candidate[1]["identity"])


def test_each_selected_platform_requires_distinct_manifest_evidence(candidate):
    repo, proposal = candidate
    old = (repo / "pack/matrix.yaml").read_text()
    new = old.replace("0.29.0", "0.30.0").replace(
        "[linux/amd64]",
        "[linux/amd64, linux/arm64]",
    )
    group = proposal["groups"][0]
    group["patch"] = group["patch"].split("diff --git a/pack/matrix.yaml")[0] + diff(
        "pack/matrix.yaml",
        old,
        new,
    )
    assert validate(candidate)["groups"][0]["status"] == "failed"
    arm64 = copy.deepcopy(group["rows"][0])
    arm64.update(platform="linux/arm64", old_engine_version=None)
    arm64["manifest"].update(
        platform="linux/arm64",
        config_platform="linux/arm64",
        platform_digest="sha256:" + "d" * 64,
    )
    group["rows"].append(arm64)
    group["patch"] += diff(
        SUPPORT,
        (repo / SUPPORT).read_text(),
        SUPPORT_START
        + support_row("0.29.0")
        + support_row(platforms="linux/amd64, linux/arm64")
        + SUPPORT_END,
    )
    result = validate(candidate)
    assert result["groups"][0]["status"] == "ready"
    assert len(result["groups"][0]["rows"]) == 2
    assert (
        verify_artifact(result, proposal["identity"])["groups"][0]["rows"]
        == group["rows"]
    )


def test_dependency_order_is_preserved_in_publication_patch(candidate):
    repo, proposal = candidate
    prerequisite = copy.deepcopy(proposal["groups"][0])
    prerequisite.update(
        id="docs",
        patch=diff(
            "README.md",
            (repo / "README.md").read_text(),
            (repo / "README.md").read_text() + "Evidence.\n",
        ),
    )
    prerequisite["rows"][0].update(
        engine_version="0.29.0",
        base_image="vllm/vllm-openai:v0.29.0",
    )
    proposal["groups"][0]["depends_on"] = ["docs"]
    proposal["groups"].append(prerequisite)
    proposal["candidates"][0]["groups"].append("docs")
    result = validate(candidate)
    assert all(g["status"] == "ready" for g in result["groups"])
    raw = verify_artifact(result, proposal["identity"])
    assert validate_candidate(repo, raw, raw["identity"])["patch"] == result["patch"]


def replace_patch(group, path, old, new):
    blocks = [
        "diff --git " + block for block in group["patch"].split("diff --git ")[1:]
    ]
    group["patch"] = "".join(
        block for block in blocks if not block.startswith(f"diff --git a/{path} ")
    )
    if old != new:
        group["patch"] += diff(path, old, new)


def freeze(candidate):
    repo, proposal = candidate
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture configuration")
    sha = git(repo, "rev-parse", "HEAD")
    proposal["identity"].update(default_sha=sha, head_sha=sha)


def test_all_changed_runtimes_need_reported_evidence(candidate):
    repo, proposal = candidate
    matrix = repo / "pack/matrix.yaml"
    old = (
        matrix.read_text()
        + "  - backend: cuda\n    services: [vllm]\n    platforms: [linux/amd64]\n    args: [VLLM_VERSION=0.29.0, CUDA_VERSION=12.9.1]\n"
    )
    matrix.write_text(old)
    freeze(candidate)
    group = proposal["groups"][0]
    replace_patch(group, "pack/matrix.yaml", old, old.replace("0.29.0", "0.30.0"))
    assert validate(candidate)["groups"][0]["status"] == "failed"
    other = copy.deepcopy(group["rows"][0])
    other["runtime"] = "12.9.1"
    group["rows"].append(other)
    before = (repo / SUPPORT).read_text()
    after = before.replace(
        SUPPORT_END,
        support_row() + support_row().replace("13.0", "12.9") + SUPPORT_END,
    )
    replace_patch(group, SUPPORT, before, after)
    assert validate(candidate)["groups"][0]["status"] == "ready"


@pytest.mark.parametrize("change", ["from", "old_engine", "old_engine_new_runtime"])
def test_report_must_match_actual_image_and_baseline(candidate, change):
    repo, proposal = candidate
    group = proposal["groups"][0]
    if change == "from":
        path = "pack/cuda/Dockerfile.vllm"
        old = (repo / path).read_text()
        new = old.replace("VLLM_VERSION=0.29.0", "VLLM_VERSION=0.30.0").replace(
            "FROM ${VLLM_BASE_IMAGE}",
            "FROM example.invalid/wrong:1",
        )
        replace_patch(group, path, old, new)
    else:
        group["rows"][0]["old_engine_version"] = "8.88.0"
        if change == "old_engine_new_runtime":
            group["rows"][0]["runtime"] = "14.0.0"
            old = (repo / "pack/matrix.yaml").read_text()
            new = old.replace(
                "VLLM_VERSION=0.29.0]",
                "VLLM_VERSION=0.30.0, CUDA_VERSION=14.0.0]",
            )
            replace_patch(group, "pack/matrix.yaml", old, new)
            old = (repo / SUPPORT).read_text()
            replace_patch(
                group,
                SUPPORT,
                old,
                old.replace(
                    SUPPORT_END,
                    support_row().replace("13.0.1", "14.0.0") + SUPPORT_END,
                ),
            )
    assert validate(candidate)["groups"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "change",
    ["missing", "unrelated", "platform", "link", "remove_history"],
)
def test_prepared_records_match_the_proposed_configuration(candidate, change):
    repo, proposal = candidate
    group = proposal["groups"][0]
    old = (repo / SUPPORT).read_text()
    if change == "missing":
        replace_patch(group, SUPPORT, old, old)
    elif change == "link":
        before = (repo / "README.md").read_text()
        group["patch"] += diff("README.md", before, "# Runner\n")
    else:
        row = (
            support_row("9.99.0")
            if change == "unrelated"
            else support_row(platforms="linux/amd64, linux/arm64")
            if change == "platform"
            else support_row()
        )
        new = (
            SUPPORT_START
            + ("" if change == "remove_history" else support_row("0.29.0"))
            + row
            + SUPPORT_END
        )
        replace_patch(group, SUPPORT, old, new)
    assert validate(candidate)["groups"][0]["status"] == "failed"


def test_matrix_overrides_cannot_break_lmcache_protocol_alignment(candidate):
    repo, proposal = candidate
    for backend, service in [("cuda", "sglang"), ("rocm", "vllm"), ("rocm", "sglang")]:
        path = repo / f"pack/{backend}/Dockerfile.{service}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"ARG {service.upper()}_LMCACHE_VERSION=0.5.4\nFROM fixture AS {service}\n",
        )
    freeze(candidate)
    old = (repo / "pack/matrix.yaml").read_text()
    new = old.replace(
        "VLLM_VERSION=0.29.0]",
        "VLLM_VERSION=0.30.0, VLLM_LMCACHE_VERSION=0.5.5]",
    )
    group = proposal["groups"][0]
    replace_patch(group, "pack/matrix.yaml", old, new)
    group["rows"][0]["packages"][0].update(version="0.5.5", decision="update")
    result = validate(candidate)
    assert result["groups"][0]["status"] == "failed"
    assert "LMCache" in result["groups"][0]["validation"]["error"]


@pytest.mark.parametrize("dependent", [False, True])
def test_source_patches_are_checked_in_recipe_order(candidate, tmp_path, dependent):
    repo, proposal = candidate
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "engine.py").write_text("value = 1\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "source")
    revision = git(source, "rev-parse", "HEAD")
    patches = []
    for name, before, after in [
        ("001_first", 1, 2),
        ("002_second", 2 if dependent else 1, 3),
    ]:
        path = f"pack/cuda/patches/vllm/{name}.patch"
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            diff("engine.py", f"value = {before}\n", f"value = {after}\n"),
        )
        patches.append(
            {
                "path": path,
                "disposition": "retain",
                "reason": "Check the installed patch sequence.",
                "versions": ["0.30.0"],
                "platforms": ["linux/amd64"],
                "sources": ["https://github.com/vllm-project/vllm"],
                "source_repository": "vllm-project/vllm",
                "source_revision": revision,
            },
        )
    freeze(candidate)
    # Report order must not override the recipe's lexical patch order.
    proposal["groups"][0]["rows"][0]["patches"] = list(reversed(patches))
    result = validate(candidate, sources={"vllm-project/vllm": source})
    assert result["groups"][0]["status"] == ("ready" if dependent else "failed")
    assert (source / "engine.py").read_text() == "value = 1\n"


@pytest.mark.parametrize(
    "plugin,tagged,expected",
    [
        ("0.30.0rc1", True, "ready"),
        ("9.99.0rc1", True, "failed"),
        ("0.30.0rc1", False, "ready"),
    ],
)
def test_ascend_plugin_uses_sourced_pairing_not_image_tag_spelling(
    candidate,
    plugin,
    tagged,
    expected,
):
    repo, proposal = candidate
    (repo / "pack/cuda").rename(repo / "pack/cann")
    path = "pack/cann/Dockerfile.vllm"
    before = (
        (repo / path)
        .read_text()
        .replace("CUDA_VERSION=13.0.1", "CANN_VERSION=9.1.0\nARG CANN_ARCHS=910b")
        .replace("VLLM_BASE_IMAGE", "CANN_BASE_IMAGE")
        .replace(
            "vllm/vllm-openai:v${VLLM_VERSION}",
            "quay.io/ascend/vllm-ascend:v0.29.0rc1",
        )
    )
    (repo / path).write_text(before)
    old_matrix = (
        (repo / "pack/matrix.yaml")
        .read_text()
        .replace("backend: cuda", "backend: cann")
    )
    (repo / "pack/matrix.yaml").write_text(old_matrix)
    old_support = (
        SUPPORT_START
        + "| cann | 9.1 | vllm | 910b | 0.29.0 | 0.29.0rc1 | linux/amd64 | prepared |\n"
        + SUPPORT_END
    )
    (repo / SUPPORT).write_text(old_support)
    freeze(candidate)
    image = (
        "quay.io/ascend/vllm-ascend:" + "v0.30.0"
        if tagged
        else "quay.io/ascend/vllm-ascend@sha256:" + "b" * 64
    )
    after = before.replace("VLLM_VERSION=0.29.0", "VLLM_VERSION=0.30.0").replace(
        "quay.io/ascend/vllm-ascend:v0.29.0rc1",
        image,
    )
    group = proposal["groups"][0]
    group["rows"][0].update(
        backend="cann",
        variant="910b",
        runtime="9.1.0",
        plugin_version=plugin,
        base_image=image,
    )
    new_support = old_support.replace(
        SUPPORT_END,
        f"| cann | 9.1 | vllm | 910b | 0.30.0 | {plugin} | linux/amd64 | prepared |\n"
        + SUPPORT_END,
    )
    group["patch"] = (
        diff(path, before, after)
        + diff("pack/matrix.yaml", old_matrix, old_matrix.replace("0.29.0", "0.30.0"))
        + diff(SUPPORT, old_support, new_support)
    )
    for entry in proposal["candidates"]:
        entry.update(
            status="ready" if entry["subscription"] == "cann/vllm" else "unchanged",
            groups=[group["id"]] if entry["subscription"] == "cann/vllm" else [],
        )
    pairs = {
        "0.30.0rc1": {
            "engine_version": "0.30.0",
            "source": "https://github.com/vllm-project/vllm-ascend/releases/tag/v0.30.0rc1",
        },
    }
    result = validate(candidate, ascend_pairs=pairs)
    assert result["groups"][0]["status"] == expected
    assert validate(candidate)["groups"][0]["status"] == "failed"
    if expected == "ready":
        raw = verify_artifact(result, proposal["identity"])
        assert (
            validate_candidate(repo, raw, raw["identity"], ascend_pairs=pairs)["patch"]
            == result["patch"]
        )
        pairs["0.30.0rc1"]["engine_version"] = "0.29.0"
        assert (
            validate(candidate, ascend_pairs=pairs)["groups"][0]["status"] == "failed"
        )


def test_prerelease_checks_and_transport_require_same_trusted_permission(candidate):
    repo, raw = candidate
    raw = json.loads(json.dumps(raw).replace("0.30.0", "0.30.0rc1"))
    raw["identity"].update(
        mode="revise",
        pr_number=1,
        command_id=7,
        command_digest="b" * 64,
    )
    permission = {("cuda", "vllm", "0.30.0rc1")}
    checked = validate_candidate(
        repo,
        raw,
        raw["identity"],
        engine_prereleases=permission,
    )
    assert checked["patch"]
    assert checked["groups"][0]["validation"]["status"] == "passed"
    with pytest.raises(ProposalError, match="stable"):
        verify_artifact(checked, raw["identity"])
    assert (
        verify_artifact(checked, raw["identity"], engine_prereleases=permission)[
            "groups"
        ][0]["status"]
        == "ready"
    )
