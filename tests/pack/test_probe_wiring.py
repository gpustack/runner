"""Check service recipe selection and collection from final Package digests.

Only explicit historical operations receive the legacy shared build context.
Active recipes need no dependency instrumentation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "pack"

MATRIX_YAML = PACK_DIR / "matrix.yaml"

_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s*\"?([A-Za-z0-9][A-Za-z0-9_.-]*)\"?\s*$")
_YAML_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+):\s*$")
_RULE_BACKEND_RE = re.compile(r"^\s*-\s+backend:\s*\"?([A-Za-z0-9_-]+)\"?\s*$")


def _yaml_list_items(lines: list[str], start: int) -> list[str]:
    """Collect the `- item` entries of the YAML block sequence starting at `start`."""
    items: list[str] = []
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _YAML_LIST_ITEM_RE.match(line)
        if not m:
            break
        items.append(m.group(1))
    return items


def _matrix_build_pairs() -> set[tuple[str, str]]:
    """Every (backend, service) pair pack/matrix.yaml expands into.

    matrix.yaml is where a service actually enters the build -- expand_matrix.sh
    derives `matrix.backend` and `matrix.service` from `rules[]` -- so a target
    absent from here is one no build can ever reach.
    """
    lines = MATRIX_YAML.read_text(encoding="utf-8").splitlines()
    pairs: set[tuple[str, str]] = set()
    backend: str | None = None
    for i, line in enumerate(lines):
        m = _RULE_BACKEND_RE.match(line)
        if m:
            backend = m.group(1)
            continue
        km = _YAML_KEY_RE.match(line)
        if backend and km and km.group(2) == "services":
            pairs.update((backend, s) for s in _yaml_list_items(lines, i + 1))
    if not pairs:
        errmsg = (
            f"no (backend, service) pairs found in {MATRIX_YAML} -- the matrix "
            f"layout changed, and every test in this file would otherwise "
            f"silently cover nothing"
        )
        raise RuntimeError(errmsg)
    return pairs


def _resolve_dockerfile(backend: str, service: str) -> Path:
    """Ask the build selector which Dockerfile supplies this target."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "bash",
            str(PACK_DIR / "resolve_dockerfile.sh"),
            str(PACK_DIR),
            backend,
            service,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


BUILD_TARGETS = sorted(
    (_resolve_dockerfile(backend, service), service)
    for backend, service in _matrix_build_pairs()
)
ACTIVE_DOCKERFILES = sorted(PACK_DIR.glob("*/Dockerfile.*"))
HISTORICAL_PROBE_RECIPES = sorted(
    path
    for path in (PACK_DIR / ".post_operation").rglob("Dockerfile*")
    if "probe_dependencies.sh" in path.read_text(encoding="utf-8")
)
FROM_RE = re.compile(r"^FROM\s+(\S+)\s+AS\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _assert_runtime_recipe(text: str, service: str):
    instructions = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    for token in (
        "DEPENDENCY_PACKAGES",
        "probe_dependencies.sh",
        "/etc/gpustack-runner/dependencies.json",
        "from=shared",
    ):
        assert token not in instructions, f"active recipe contains {token}"
    stages = list(FROM_RE.finditer(instructions))
    assert stages, "recipe has no named stages"
    assert all(not stage[2].endswith("-deps") for stage in stages), (
        "dependency export stage"
    )
    assert stages[-1][2] == service, "default output is not the service target"
    assert stages[-1][1].lower() != "scratch", "service target is an empty export"
    entrypoint = re.search(
        r"^ENTRYPOINT\s",
        instructions[stages[-1].end() :],
        re.MULTILINE,
    )
    assert entrypoint, "service entrypoint is missing"


def test_discovery_found_build_targets():
    assert BUILD_TARGETS, f"no build targets resolved from {MATRIX_YAML}"
    assert ACTIVE_DOCKERFILES, "no active service recipes found"
    assert HISTORICAL_PROBE_RECIPES, "no historical probe callers found"
    for path, service in BUILD_TARGETS:
        assert path in ACTIVE_DOCKERFILES
        assert path.name == f"Dockerfile.{service}"


@pytest.mark.parametrize("path", ACTIVE_DOCKERFILES, ids=_rel)
def test_active_recipe_outputs_service_without_instrumentation(path):
    _assert_runtime_recipe(path.read_text(encoding="utf-8"), path.suffix[1:])


@pytest.mark.parametrize(
    "extra",
    [
        'ARG DEPENDENCY_PACKAGES=""',
        "RUN --mount=type=bind,from=shared,source=probe_dependencies.sh echo probe",
        "COPY dependencies.json /etc/gpustack-runner/dependencies.json",
        "FROM scratch AS vllm-deps",
    ],
)
def test_recipe_check_rejects_instrumentation(extra):
    recipe = 'FROM runtime AS vllm\nENTRYPOINT ["tini", "--"]\n'
    _assert_runtime_recipe(recipe, "vllm")
    with pytest.raises(AssertionError):
        _assert_runtime_recipe(recipe + extra + "\n", "vllm")


@pytest.fixture
def pack_workflow():
    result = subprocess.run(  # noqa: S603
        ["yq", "-o=json", ".", str(REPO_ROOT / ".github/workflows/pack.yml")],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "path",
    [PACK_DIR / "cuda/Dockerfile.vllm", *HISTORICAL_PROBE_RECIPES],
    ids=_rel,
)
def test_workflow_shared_context_is_only_for_historical_operations(
    tmp_path,
    pack_workflow,
    path,
):
    steps = {step["name"]: step for step in pack_workflow["jobs"]["build"]["steps"]}
    historical = ".post_operation" in path.parts
    operation = path.parent.parent.name if historical else ""
    script = steps["Get Metadata"]["run"]
    for expression, value in (
        ("github.workspace", str(REPO_ROOT)),
        ("matrix.backend", path.parent.name),
        ("matrix.service", "vllm"),
    ):
        script = script.replace("${{ " + expression + " }}", value)
    assert "${{" not in script
    output = tmp_path / "output"
    result = subprocess.run(  # noqa: S603 - Runs the workflow with controlled inputs.
        ["bash", "-c", script],  # noqa: S607
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(output),
            "INPUT_NAMESPACE": "gpustack",
            "INPUT_REPOSITORY": "runner",
            "INPUT_CACHE_REPOSITORY": "runner-cache",
            "INPUT_POST_OPERATION": operation,
            "INPUT_WITH_CACHE": "false",
            "INPUT_PLATFORM_TAG": "fixture-linux-amd64",
            "INPUT_PLATFORM_TAG_CACHE": "",
            "INPUT_ARGS": "VLLM_VERSION=0.29.0",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    exported = output.read_text()
    assert f"docker_file={path}\n" in exported
    assert "build_args<<EOF\nVLLM_VERSION=0.29.0\nEOF\n" in exported
    context = f"shared={PACK_DIR / 'shared'}\n" if historical else ""
    assert f"build_contexts<<EOF\n{context}EOF\n" in exported
    assert steps["Package"]["with"]["build-contexts"] == (
        "${{ steps.metadata.outputs.build_contexts }}"
    )
    assert steps["Package"]["with"]["target"] == "${{ matrix.service }}"
    if historical:
        helper = PACK_DIR / "shared/probe_dependencies.sh"
        assert helper.is_file()
        legacy_output = tmp_path / "legacy.json"
        result = subprocess.run(  # noqa: S603
            ["bash", str(helper), str(legacy_output)],  # noqa: S607
            env={**os.environ, "DEPENDENCY_PACKAGES": ""},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert not legacy_output.exists()


def test_workflow_collects_final_package_digest_on_native_build_job(pack_workflow):
    build = pack_workflow["jobs"]["build"]
    steps = {step["name"]: step for step in build["steps"]}
    assert build["runs-on"] == "${{ matrix.runner }}"
    assert steps["Package"]["id"] == "package"
    assert (
        steps["Record Package Output"]["env"]["PACKAGE_DIGEST"]
        == "${{ steps.package.outputs.digest }}"
    )
    assert (
        steps["Record Package Output"]["env"]["BUILD_ATTEMPT"]
        == "${{ github.run_attempt }}"
    )
    assert "collect-record" in steps["Collect Dependencies"]["run"]
    assert (
        steps["Collect Dependencies"]["if"]
        == "${{ github.event.inputs.dry_run == 'false' }}"
    )
    assert "Export Dependencies" not in steps
    names = list(steps)
    assert (
        names.index("Package")
        < names.index("Record Package Output")
        < names.index("Upload Package Output")
        < names.index("Collect Dependencies")
        < names.index("Upload Dependencies")
    )


def test_workflow_reruns_replace_only_the_selected_job_artifacts(pack_workflow):
    steps = {step["name"]: step for step in pack_workflow["jobs"]["build"]["steps"]}
    for name, prefix in (
        ("Upload Package Output", "builds"),
        ("Upload Dependencies", "dependencies"),
    ):
        upload = steps[name]
        assert upload["with"]["name"] == prefix + "-${{ matrix.platform_tag }}"
        assert upload["with"]["overwrite"] is True
        assert upload["with"]["if-no-files-found"] == "error"
    assert "always()" in steps["Upload Dependencies"]["if"]
    assert "invocation" not in steps["Upload Dependencies"]["with"]["name"]
    outputs = pack_workflow["jobs"]["expand-matrix"]["outputs"]
    assert outputs["context"] == "${{ steps.freeze.outputs.context }}"


def test_workflow_serializes_and_verifies_manifest_before_catalog(pack_workflow):
    assert pack_workflow["concurrency"]["cancel-in-progress"] is False
    manifest = pack_workflow["jobs"]["manifest"]
    steps = {step["name"]: step for step in manifest["steps"]}
    assert "build" in manifest["needs"]
    assert " publish " in steps["Manifest"]["run"]
    assert (
        steps["Manifest"]["env"]["INPUT_CONTEXT"]
        == "${{ needs.expand-matrix.outputs.context }}"
    )
    merge = pack_workflow["jobs"]["merge-runner"]
    assert "manifest" in merge["needs"]
    steps = {step["name"]: step for step in merge["steps"]}
    env = steps["Merge Runner"]["env"]
    assert env["INPUT_CONTEXT"] == "${{ needs.expand-matrix.outputs.context }}"
    assert env["INPUT_MANIFESTS_FILE"].endswith("/manifests/manifests.json")
    assert {step.get("with", {}).get("pattern") for step in merge["steps"]} >= {
        "builds-*",
        "dependencies-*",
    }


def test_merge_workflow_uses_locked_runtime_dependencies(tmp_path, pack_workflow):
    steps = {
        step["name"]: step for step in pack_workflow["jobs"]["merge-runner"]["steps"]
    }
    setup = steps["Setup UV"]
    assert setup["uses"] == "astral-sh/setup-uv@v7"
    assert setup["with"]["version"] == "0.8.24"
    assert setup["with"]["enable-cache"] is True
    assert setup["with"]["python-version"] in {"3.10", "3.11", "3.12"}
    assert not setup.get("continue-on-error", False)
    install = steps["Install Runtime Dependencies"]
    assert install["run"] == "uv sync --locked --no-dev --no-install-project"
    assert not install.get("continue-on-error", False)
    names = list(steps)
    assert names.index("Setup UV") < names.index("Install Runtime Dependencies")
    assert names.index("Install Runtime Dependencies") < names.index("Merge Runner")

    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(REPO_ROOT / name, tmp_path / name)
    script = tmp_path / "pack/merge_runner.sh"
    script.parent.mkdir()
    script.write_text(
        "python3 - <<'PY'\n"
        "import importlib.util, json, sys\n"
        "from packaging.version import Version\n"
        "assert Version('1.0rc1') < Version('1.0')\n"
        "assert importlib.util.find_spec('pytest') is None\n"
        "assert importlib.util.find_spec('gpustack_runner') is None\n"
        "print(json.dumps({'prefix': sys.prefix}))\n"
        "PY\n",
    )
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / ".venv"),
        # Exercise each CI Python without downloading another interpreter.
        "UV_PYTHON": sys.executable,
        "UV_OFFLINE": "1",
    }
    env.pop("VIRTUAL_ENV", None)
    for command in (
        install["run"],
        steps["Merge Runner"]["run"].replace("${{ github.workspace }}", str(tmp_path)),
    ):
        result = subprocess.run(  # noqa: S603 - Runs workflow setup in a temporary project.
            ["bash", "-c", command],  # noqa: S607
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["prefix"] == str(tmp_path / ".venv")
    assert not (tmp_path / "gpustack_runner").exists()


def test_workflow_freeze_and_record_commands_execute(tmp_path, pack_workflow):
    job = {
        "backend": "cuda",
        "service": "vllm",
        "platform": "linux/amd64",
        "platform_tag": "cuda-vllm-linux-amd64",
        "tag": "cuda-vllm",
    }
    steps = {
        step["name"]: step for step in pack_workflow["jobs"]["expand-matrix"]["steps"]
    }
    env = {
        **os.environ,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "b" * 40,
        "INPUT_NAMESPACE": "gpustack",
        "INPUT_REPOSITORY": "runner",
        "BUILD_JOBS": json.dumps([job]),
        "MANIFEST_JOBS": json.dumps({job["tag"]: [job["platform_tag"]]}),
    }
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", steps["Freeze Invocation"]["run"]],  # noqa: S607
        env=env,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    context = json.loads((tmp_path / "output").read_text().removeprefix("context="))
    assert context["matrix"]["build_jobs"] == [job]
    assert context["invocation"]["source_revision"] == env["GITHUB_SHA"]
    assert context["invocation"]["workflow_run"] == env["GITHUB_RUN_ID"]
    steps = {step["name"]: step for step in pack_workflow["jobs"]["build"]["steps"]}
    env.update(
        INPUT_CONTEXT=json.dumps(context),
        PACKAGE_DIGEST="sha256:" + "a" * 64,
        BUILD_JOB=job["platform_tag"],
        BUILD_ATTEMPT="2",
    )
    command = ["bash", "-c", steps["Record Package Output"]["run"]]
    result = subprocess.run(  # noqa: S603 - Executes the repository workflow against fake inputs.
        command,
        env=env,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    record_path = tmp_path / "build.json"
    record = json.loads(record_path.read_text())
    assert record["invocation"] == context["invocation"]
    assert record["build"]["image_digest"] == env["PACKAGE_DIGEST"]
    assert record["build"]["attempt"] == 2
    assert record["build"]["platform"] == job["platform"]
    before = record_path.read_bytes()
    env["PACKAGE_DIGEST"] = ""
    result = subprocess.run(  # noqa: S603 - Executes the repository workflow against fake inputs.
        command,
        env=env,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "invalid build image_digest" in result.stderr
    assert record_path.read_bytes() == before


def test_workflow_keeps_first_invocation_immutable(pack_workflow):
    steps = {
        step["name"]: step for step in pack_workflow["jobs"]["expand-matrix"]["steps"]
    }
    assert steps["Download Frozen Invocation"]["if"] == "${{ github.run_attempt > 1 }}"
    upload = steps["Upload Frozen Invocation"]
    assert upload["if"] == "${{ github.run_attempt == 1 }}"
    assert upload["with"]["name"] == "pack-context"
    assert upload["with"].get("overwrite", False) is False
    assert (
        '--previous "$RUNNER_TEMP/invocation/context.json"'
        in steps["Freeze Invocation"]["run"]
    )
