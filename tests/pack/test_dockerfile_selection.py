"""Exercise the shared selector and real matrix expansion without building images."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "pack"
RESOLVER = PACK_DIR / "resolve_dockerfile.sh"
EXPAND_MATRIX = PACK_DIR / "expand_matrix.sh"


def _resolve(pack: Path, backend="cuda", service="vllm", operation=""):
    return subprocess.run(  # noqa: S603
        ["bash", str(RESOLVER), str(pack), backend, service, operation],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def _dockerfile(pack: Path, name: str, defaults: str = "") -> Path:
    path = pack / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(defaults, encoding="utf-8")
    return path


@pytest.mark.parametrize("operation", ["", "repair"])
def test_split_recipe_wins_over_combined_recipe(tmp_path, operation):
    context = tmp_path / ".post_operation" / operation if operation else tmp_path
    expected = _dockerfile(context, "cuda/Dockerfile.vllm")
    _dockerfile(context, "cuda/Dockerfile")

    result = _resolve(tmp_path, operation=operation)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize("operation", ["", "repair"])
def test_combined_recipe_remains_available_during_migration(tmp_path, operation):
    context = tmp_path / ".post_operation" / operation if operation else tmp_path
    expected = _dockerfile(context, "cuda/Dockerfile")
    if operation:
        _dockerfile(tmp_path, "cuda/Dockerfile.vllm")

    result = _resolve(tmp_path, operation=operation)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize("operation", ["", "repair"])
def test_missing_selected_recipe_fails_without_using_another_context(
    tmp_path,
    operation,
):
    other_context = tmp_path if operation else tmp_path / ".post_operation" / "repair"
    _dockerfile(other_context, "cuda/Dockerfile.vllm")

    result = _resolve(tmp_path, operation=operation)

    assert result.returncode != 0
    assert not result.stdout
    assert "Dockerfile" in result.stderr
    assert "cuda" in result.stderr
    assert "vllm" in result.stderr


def _expand(pack: Path, tmp_path: Path, service="vllm", backend="all", operation=""):
    output = tmp_path / "output"
    result = subprocess.run(  # noqa: S603
        ["bash", str(EXPAND_MATRIX)],  # noqa: S607
        env={
            **os.environ,
            "INPUT_WORKSPACE": str(pack),
            "INPUT_TEMPDIR": str(tmp_path),
            "INPUT_TARGET": service,
            "INPUT_BACKEND": backend,
            "INPUT_POST_OPERATION": operation,
            "INPUT_ARGS": "",
            "INPUT_TAG": "",
            "INPUT_FOR_RELEASE": "true",
            "INPUT_RUNNER_PROFILE": "normal",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    values = {}
    if output.exists():
        values = {
            key: json.loads(value)
            for key, value in (
                line.split("=", 1) for line in output.read_text().splitlines()
            )
        }
    return result, values


def _matrix(pack: Path, rules: list[dict]):
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "matrix.yaml").write_text(json.dumps({"rules": rules}), encoding="utf-8")


def test_broad_expansion_filters_unsupported_pairs_before_reading_defaults(tmp_path):
    pack = tmp_path / "pack"
    _matrix(
        pack,
        [
            {"backend": "corex", "services": ["vllm"]},
            {"backend": "cuda", "services": ["sglang"]},
        ],
    )
    _dockerfile(
        pack,
        "cuda/Dockerfile.sglang",
        "ARG CUDA_VERSION=13.0.1\nARG SGLANG_VERSION=0.5.18\n",
    )

    result, output = _expand(pack, tmp_path, service="sglang")

    assert result.returncode == 0, result.stdout + result.stderr
    jobs = output["build_jobs"]
    assert len(jobs) == 2
    assert {(job["backend"], job["service"]) for job in jobs} == {("cuda", "sglang")}
    assert {job["platform"] for job in jobs} == {"linux/amd64", "linux/arm64"}
    assert {job["service_version"] for job in jobs} == {"0.5.18"}


@pytest.mark.parametrize("backend", ["all", "corex"])
def test_selection_with_no_supported_pair_returns_empty_jobs(tmp_path, backend):
    pack = tmp_path / "pack"
    _matrix(pack, [{"backend": "corex", "services": ["vllm"]}])

    result, output = _expand(pack, tmp_path, service="sglang", backend=backend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output == {"build_jobs": [], "manifest_jobs": {}}


@pytest.mark.parametrize("backend", ["all", "cuda"])
def test_matrix_rejects_a_supported_pair_with_no_recipe(tmp_path, backend):
    pack = tmp_path / "pack"
    _matrix(pack, [{"backend": "cuda", "services": ["vllm"]}])

    result, output = _expand(pack, tmp_path, backend=backend)

    assert result.returncode != 0
    assert "Dockerfile" in result.stdout + result.stderr
    assert not output


def test_explicit_historical_operation_uses_its_matrix_and_defaults(tmp_path):
    pack = tmp_path / "pack"
    operation = pack / ".post_operation" / "repair"
    _matrix(pack, [{"backend": "corex", "services": ["vllm"]}])
    _matrix(operation, [{"backend": "cuda", "services": ["vllm"]}])
    _dockerfile(pack, "cuda/Dockerfile.vllm", "ARG VLLM_VERSION=0.29.0\n")
    _dockerfile(
        operation,
        "cuda/Dockerfile",
        "ARG CUDA_VERSION=12.6.3\nARG VLLM_VERSION=0.10.0\n",
    )

    result, output = _expand(pack, tmp_path, operation="repair")

    assert result.returncode == 0, result.stdout + result.stderr
    jobs = output["build_jobs"]
    assert len(jobs) == 2
    assert {job["tag"] for job in jobs} == {"cuda12.6-vllm0.10.0"}
    assert output["manifest_jobs"] == {
        "cuda12.6-vllm0.10.0": [
            "cuda12.6-vllm0.10.0-linux-amd64",
            "cuda12.6-vllm0.10.0-linux-arm64",
        ],
    }


@pytest.mark.parametrize("service", ["vllm", "sglang"])
def test_repository_matrix_expands_every_supported_pair(tmp_path, service):
    matrix = subprocess.run(  # noqa: S603
        ["yq", "--output-format", "json", ".rules", str(PACK_DIR / "matrix.yaml")],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    expected = {
        (rule["backend"], service)
        for rule in json.loads(matrix.stdout)
        if service in rule["services"]
    }
    assert expected

    result, output = _expand(PACK_DIR, tmp_path, service=service)

    assert result.returncode == 0, result.stdout + result.stderr
    assert {
        (job["backend"], job["service"]) for job in output["build_jobs"]
    } == expected


@pytest.mark.parametrize(
    "path",
    ["Makefile", "pack/expand_matrix.sh", ".github/workflows/pack.yml"],
)
def test_build_entry_point_calls_shared_resolver(path):
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert "resolve_dockerfile.sh" in content


@pytest.mark.parametrize("entry_point", ["make", "workflow"])
@pytest.mark.parametrize("operation", ["", "repair"])
@pytest.mark.parametrize("recipe", ["Dockerfile.vllm", "Dockerfile", None])
def test_build_entry_point_selection(tmp_path, entry_point, operation, recipe):
    """Run the caller's selection code only; no build or Pack job is invoked."""
    pack = tmp_path / "pack"
    context = pack / ".post_operation" / operation if operation else pack
    pack.mkdir()
    shutil.copy(RESOLVER, pack / RESOLVER.name)
    shutil.copy(PACK_DIR / "dependencies.json", pack / "dependencies.json")
    expected = _dockerfile(context, f"cuda/{recipe}") if recipe else None
    output = tmp_path / "output"
    env = {
        **os.environ,
        "INPUT_POST_OPERATION": operation,
        "INPUT_WITH_CACHE": "false",
        "INPUT_ARGS": "",
        "GITHUB_OUTPUT": str(output),
        "JOB_BACKEND": "cuda",
        "JOB_TARGET": "vllm",
    }
    if entry_point == "make":
        lines = (REPO_ROOT / "Makefile").read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if "JOB_DOCKERFILE=" in line)
        end = next(i for i in range(start, len(lines)) if "JOB_LOCATION=" in lines[i])
        selection = "\n".join(lines[start : end + 1])
        makefile = tmp_path / "Makefile"
        makefile.write_text(
            f"SHELL := /bin/bash\nSRCDIR := {tmp_path}\n"
            f"PACKAGE_POST_OPERATION := {operation}\n.SILENT:\nselect:\n"
            "\tset -e; \\\n"
            f"{selection}\n"
            '\techo "docker_file=$${JOB_DOCKERFILE}" >> "$${GITHUB_OUTPUT}"; \\\n'
            '\techo "docker_context=$${JOB_LOCATION}" >> "$${GITHUB_OUTPUT}"\n',
        )
        command = ["make", "-f", str(makefile), "select"]
    else:
        metadata = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "yq",
                "-r",
                '.jobs.build.steps[] | select(.id == "metadata") | .run',
                str(REPO_ROOT / ".github/workflows/pack.yml"),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        metadata = metadata.replace("${{ github.workspace }}", str(tmp_path))
        metadata = metadata.replace("${{ matrix.backend }}", "cuda")
        metadata = metadata.replace("${{ matrix.service }}", "vllm")
        assert "${{" not in metadata
        command = ["bash", "-c", metadata]

    result = subprocess.run(  # noqa: S603
        command,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    exported = output.read_text() if output.exists() else ""
    if expected:
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"docker_file={expected}\n" in exported
        assert f"docker_context={expected.parent}\n" in exported
    else:
        assert result.returncode != 0
        assert "Dockerfile not found" in result.stderr
        assert "docker_file=" not in exported
