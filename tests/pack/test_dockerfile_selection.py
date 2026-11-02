"""Exercise the shared selector and real matrix expansion without building images."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "pack"
RESOLVER = PACK_DIR / "resolve_dockerfile.sh"
EXPAND_MATRIX = PACK_DIR / "expand_matrix.sh"
ACTIVE_SERVICES = {
    "cuda": ["vllm", "sglang", "voxbox"],
    "rocm": ["vllm", "sglang"],
    "cann": ["vllm", "sglang", "mindie"],
    "corex": ["vllm"],
    "dtk": ["vllm", "sglang"],
    "hggc": ["vllm", "sglang"],
    "maca": ["vllm", "sglang"],
    "musa": ["vllm", "sglang"],
}


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


@pytest.mark.parametrize("backend", ACTIVE_SERVICES)
def test_active_selection_rejects_combined_recipe(tmp_path, backend):
    _dockerfile(tmp_path, f"{backend}/Dockerfile")

    result = _resolve(tmp_path, backend=backend)

    assert result.returncode != 0
    assert not result.stdout
    assert "Dockerfile not found" in result.stderr
    assert str(tmp_path / backend / "Dockerfile.vllm") in result.stderr


@pytest.mark.parametrize(
    "backend, service",
    [
        (backend, service)
        for backend, services in ACTIVE_SERVICES.items()
        for service in services
    ],
)
def test_repository_active_recipes_are_service_specific(backend, service):
    result = _resolve(PACK_DIR, backend=backend, service=service)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(PACK_DIR / backend / f"Dockerfile.{service}")
    assert not (PACK_DIR / backend / "Dockerfile").exists()


def test_combined_recipe_remains_available_for_explicit_historical_operation(tmp_path):
    operation = "repair"
    context = tmp_path / ".post_operation" / operation
    expected = _dockerfile(context, "cuda/Dockerfile")
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
@pytest.mark.parametrize("combined_recipe", [False, True])
def test_matrix_rejects_a_supported_pair_without_service_recipe(
    tmp_path,
    backend,
    combined_recipe,
):
    pack = tmp_path / "pack"
    _matrix(pack, [{"backend": "cuda", "services": ["vllm"]}])
    if combined_recipe:
        _dockerfile(
            pack,
            "cuda/Dockerfile",
            "ARG CUDA_VERSION=13.0.1\nARG VLLM_VERSION=0.29.0\n",
        )

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


@pytest.mark.parametrize(
    "backend,service",
    [("musa", "vllm"), ("musa", "sglang"), ("cuda", "voxbox"), ("cann", "mindie")],
)
def test_service_matrix_matches_the_existing_runtime(tmp_path, backend, service):
    catalog = json.loads((REPO_ROOT / "gpustack_runner/runner.py.json").read_text())
    recipe = (PACK_DIR / backend / f"Dockerfile.{service}").read_text()
    selected_version = next(
        line.split("=", 1)[1]
        for line in recipe.splitlines()
        if line.startswith(f"ARG {service.upper()}_VERSION=")
    )
    supported = [
        row
        for row in catalog
        if row["backend"] == backend
        and row["service"] == service
        and row["service_version"] == selected_version
        and not row["deprecated"]
    ]
    assert supported
    result, output = _expand(PACK_DIR, tmp_path, service=service, backend=backend)
    assert result.returncode == 0, result.stdout + result.stderr
    jobs = output["build_jobs"]
    assert jobs
    assert {
        (job["original_backend_version"], job["service_version"], job["platform"])
        for job in jobs
    } == {
        (row["original_backend_version"], row["service_version"], row["platform"])
        for row in supported
    }


@pytest.mark.parametrize("service", ["vllm", "sglang", "voxbox", "mindie"])
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
    if expected and (operation or recipe == "Dockerfile.vllm"):
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"docker_file={expected}\n" in exported
        assert f"docker_context={expected.parent}\n" in exported
    else:
        assert result.returncode != 0
        assert "Dockerfile not found" in result.stderr
        assert "docker_file=" not in exported


@pytest.fixture
def ascend_mooncake_lookup(tmp_path):
    if shutil.which("patch") is None:
        pytest.skip("patch utility is required for this test")
    # Freeze the upstream port lookup so the packaging patch runs without NPU imports.
    # vllm-ascend 8fde6d4e335fe300e2b949aab0e31659cce0811d.
    source = """class MooncakeConnectorWorker:
    def _get_remote_host_info_by_port(
        self,
        base_port: int,
        remote_handshake_port: int,
        remote_host: str,
        remote_engine_id: str,
        remote_multi_nodes_meta_mapping: dict,
    ):
        if remote_multi_nodes_meta_mapping is None:
            return remote_host, remote_engine_id

        kv_port = self.vllm_config.kv_transfer_config.kv_port
        rank = str(remote_handshake_port - kv_port)
        info = remote_multi_nodes_meta_mapping.get(rank)
        if info is None:
            rank = str(remote_handshake_port - base_port)
            info = remote_multi_nodes_meta_mapping.get(rank)
        if info is None:
            return remote_host, remote_engine_id
        return info.get("host", remote_host), info.get("engine_id", remote_engine_id)
"""
    path = tmp_path / "vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py"
    path.parent.mkdir(parents=True)
    path.write_text(source)
    patch = PACK_DIR / "cann/patches/vllm_ascend/001_remote_host_port.patch"
    result = subprocess.run(  # noqa: S603
        ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)],  # noqa: S607
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    namespace = {}
    exec(compile(ast.parse(path.read_text()), str(path), "exec"), namespace)  # noqa: S102
    worker = namespace["MooncakeConnectorWorker"]()
    worker.vllm_config = SimpleNamespace(
        kv_transfer_config=SimpleNamespace(kv_port=44000),
    )
    return worker._get_remote_host_info_by_port  # noqa: SLF001


@pytest.mark.parametrize("dp_rank", [0, 1])
@pytest.mark.parametrize("tp_rank", range(4))
def test_ascend_mooncake_resolves_remote_worker_by_absolute_port(
    ascend_mooncake_lookup,
    dp_rank,
    tp_rank,
):
    # The sender's offsets include DP, while the receiver owns a different port band.
    offset = dp_rank * 4
    mapping = {
        str(offset + tp): {
            "host": "head" if tp < 2 else "headless",
            "engine_id": f"p{dp_rank}",
            "handshake_port": 43000 + offset + tp,
        }
        for tp in range(4)
    }
    assert ascend_mooncake_lookup(
        43000 + offset,
        43000 + offset + tp_rank,
        "head",
        "fallback",
        mapping,
    ) == ("head" if tp_rank < 2 else "headless", f"p{dp_rank}")


@pytest.mark.parametrize(
    "mapping,base,port,expected",
    [
        (None, 43000, 43002, ("head", "fallback")),
        ({}, 43000, 43002, ("head", "fallback")),
        ({"2": {"host": "legacy", "engine_id": "p0"}}, 43000, 43002, ("legacy", "p0")),
        (
            {"2": {"host": "legacy-local", "engine_id": "p1"}},
            43000,
            44002,
            ("legacy-local", "p1"),
        ),
        (
            {
                "6": {"handshake_port": 43006, "host": "explicit", "engine_id": "p1"},
                "2": {"host": "wrong", "engine_id": "wrong"},
            },
            43004,
            43006,
            ("explicit", "p1"),
        ),
        ({"6": {"handshake_port": 43006}}, 43004, 43006, ("head", "fallback")),
        (
            {
                "6": {"handshake_port": 43006, "host": "ambiguous"},
                "7": {"handshake_port": 43006, "host": "ambiguous2"},
            },
            43004,
            43006,
            ("head", "fallback"),
        ),
    ],
)
def test_ascend_mooncake_preserves_legacy_port_lookup(
    ascend_mooncake_lookup,
    mapping,
    base,
    port,
    expected,
):
    assert ascend_mooncake_lookup(base, port, "head", "fallback", mapping) == expected


def test_ascend_hixl_channel_ids_survive_server_restart(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None or shutil.which("patch") is None:
        pytest.skip("C++ compiler and patch utility are required for this test")
    # HIXL v9.2.0, 60dbe9d1d7d9a7eef04bc3dbf84edbad2188230a.
    source = tmp_path / "src/hixl/cs/hixl_cs_server.cc"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n" * 11
        + "#include <atomic>\n#include <cinttypes>\n#include <iostream>\n"
        + "\n" * 26
        + "std::atomic<uint64_t> g_next_server_channel_index{0UL};\n\n"
        "int main() {\n"
        '  std::cout << g_next_server_channel_index.fetch_add(1U) << " "\n'
        "            << g_next_server_channel_index.fetch_add(1U);\n"
        "}\n",
        encoding="utf-8",
    )
    executable = tmp_path / "channels"

    def run_processes():
        subprocess.run(  # noqa: S603
            [compiler, "-std=c++17", str(source), "-o", str(executable)],
            check=True,
            capture_output=True,
        )
        return [
            tuple(
                map(
                    int,
                    subprocess.check_output([str(executable)], text=True).split(),  # noqa: S603
                ),
            )
            for _ in range(2)
        ]

    assert run_processes() == [(0, 1), (0, 1)]
    patch = PACK_DIR / "cann/patches/hixl/001_channel_generation.patch"
    subprocess.run(  # noqa: S603
        ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)],  # noqa: S607
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    generations = run_processes()
    assert all(first > 0 and second == first + 1 for first, second in generations)
    assert len({value for pair in generations for value in pair}) == 4


@pytest.mark.parametrize("architecture,skipped", [("310p", True), ("910b", False)])
def test_hixl_host_build_skips_architecture_without_mooncake(
    tmp_path,
    architecture,
    skipped,
):
    dockerfile = (PACK_DIR / "cann/Dockerfile.vllm").read_text()
    stage = dockerfile.split("FROM vllm-build AS vllm-build-hixl\n", 1)[1]
    script = stage.split("<<EOF\n", 1)[1].split("\nEOF", 1)[0]
    output = tmp_path / "output"
    script = script.replace("/output", str(output)).replace(
        "/tmp/hixl",  # noqa: S108 -- replace the Docker build path for isolation
        str(tmp_path / "hixl"),
    )
    # No source download or CANN installation is allowed in this recipe check.
    script = "source() { :; }; curl() { return 87; };\n" + script
    result = subprocess.run(  # noqa: S603
        ["bash", "-eo", "pipefail", "-c", script],  # noqa: S607
        env={**os.environ, "CANN_ARCHS": architecture},
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is skipped
    assert output.is_dir()
    assert not list(output.iterdir())
