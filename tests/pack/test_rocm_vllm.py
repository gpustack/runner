"""Exercise the TheRock build gate with fake packages and SDK paths, without GPUs."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_vllm",
    ROOT / "pack/rocm/check_vllm.py",
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

EXPECTED = {
    "rocm-sdk-core": "10.0.0",
    "torch": "2.13.0",
    "vllm": "0.33.0",
    "lmcache": "0.5.6",
    "mooncake-transfer-engine-rocm": "0.3.13.post1",
}


@pytest.fixture(name="packages")
def _packages(monkeypatch):
    versions = {**EXPECTED, "torch": "2.13.0+rocm10.0.0", "vllm": "0.33.0+rocm100"}
    modules = {
        "torch": SimpleNamespace(version=SimpleNamespace(hip="7.15.0", cuda=None)),
        "vllm._C": SimpleNamespace(),
        "cupy": SimpleNamespace(
            cuda=SimpleNamespace(runtime=SimpleNamespace(is_hip=True)),
        ),
        "onnxruntime": SimpleNamespace(
            get_available_providers=lambda: ["ROCMExecutionProvider"],
        ),
        "mooncake.engine": SimpleNamespace(),
        "vllm_omni": SimpleNamespace(),
    }
    monkeypatch.setattr(check.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(check.importlib, "import_module", modules.__getitem__)
    return versions, modules


@pytest.mark.usefixtures("packages")
def test_stack_accepts_local_rocm_versions_without_equating_hip_and_sdk():
    check.check_versions(EXPECTED, "10.0.0")


@pytest.mark.parametrize(
    "package,version",
    [
        ("rocm-sdk-core", "10.1.0"),
        ("torch", "2.14.0+rocm10.0.0"),
        ("torch", "2.13.0+rocm7.2"),
        ("torch", "2.13.0+rocm10.0"),
        ("vllm", "0.32.0+rocm100"),
        ("lmcache", "0.5.7"),
        ("mooncake-transfer-engine-rocm", "0.3.13"),
    ],
)
def test_stack_rejects_replaced_core_packages(packages, package, version):
    versions, _ = packages
    versions[package] = version
    with pytest.raises(ValueError, match=r"expected|does not match"):
        check.check_versions(EXPECTED, "10.0.0")


def test_stack_rejects_cuda_torch_even_with_matching_metadata(packages):
    _, modules = packages
    modules["torch"].version.hip = None
    modules["torch"].version.cuda = "13.0"
    with pytest.raises(ValueError, match="requires ROCm PyTorch"):
        check.check_versions(EXPECTED, "10.0.0")


@pytest.fixture(name="sdk")
def _sdk(tmp_path, monkeypatch):
    root = tmp_path / "site-packages/_rocm_sdk_devel"
    (root / "bin").mkdir(parents=True)
    compiler = root / "bin/hipcc"
    compiler.write_text("#!/bin/sh\nexit 0\n")
    compiler.chmod(0o755)
    (root.parent / "_rocm_sdk_core").mkdir()
    monkeypatch.setattr(
        check.metadata,
        "distribution",
        lambda _: SimpleNamespace(locate_file=lambda name: root.parent / name),
    )
    for name in ["ROCM_PATH", "ROCM_HOME", "HIP_PATH"]:
        monkeypatch.setenv(name, str(root))
    monkeypatch.setenv("PATH", str(compiler.parent) + os.pathsep + os.environ["PATH"])
    return root


@pytest.mark.usefixtures("sdk")
def test_sdk_accepts_inherited_paths():
    check.check_sdk()


def test_sdk_accepts_devel_compiler_symlink_to_core(sdk):
    compiler = sdk / "bin/hipcc"
    core = sdk.parent / "_rocm_sdk_core/bin"
    core.mkdir(parents=True, exist_ok=True)
    (core / "hipcc").write_text("#!/bin/sh\nexit 0\n")
    (core / "hipcc").chmod(0o755)
    compiler.unlink()
    compiler.symlink_to(core / "hipcc")
    check.check_sdk()


@pytest.mark.parametrize("name", ["ROCM_PATH", "ROCM_HOME", "HIP_PATH"])
@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.usefixtures("sdk")
def test_sdk_rejects_missing_or_empty_environment(monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=f"{name} is not set"):
        check.check_sdk()


@pytest.mark.usefixtures("sdk")
def test_empty_sdk_paths_cannot_adopt_current_directory(tmp_path, monkeypatch):
    compiler = tmp_path / "unrelated/hipcc"
    compiler.parent.mkdir()
    compiler.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check.shutil, "which", lambda _: str(compiler))
    for name in ("ROCM_PATH", "ROCM_HOME", "HIP_PATH"):
        monkeypatch.setenv(name, "")
    with pytest.raises(ValueError, match="ROCM_PATH is not set"):
        check.check_sdk()


def test_sdk_environment_must_reference_directories(sdk, tmp_path, monkeypatch):
    compiler = sdk.parent / "_rocm_sdk_core/hipcc"
    compiler.touch()
    not_directory = tmp_path / "not-a-directory"
    not_directory.touch()
    monkeypatch.setattr(check.shutil, "which", lambda _: str(compiler))
    for name in ("ROCM_PATH", "ROCM_HOME", "HIP_PATH"):
        monkeypatch.setenv(name, str(not_directory))
    with pytest.raises(ValueError, match="ROCM_PATH is not a directory"):
        check.check_sdk()


@pytest.mark.parametrize("name", ["ROCM_HOME", "HIP_PATH"])
@pytest.mark.usefixtures("sdk")
def test_sdk_rejects_overwritten_paths(tmp_path, monkeypatch, name):
    legacy = tmp_path / "opt/rocm"
    legacy.mkdir(parents=True)
    monkeypatch.setenv(name, str(legacy))
    with pytest.raises(ValueError, match="differs"):
        check.check_sdk()


@pytest.mark.usefixtures("sdk")
def test_sdk_rejects_compiler_from_another_install(tmp_path, monkeypatch):
    monkeypatch.setattr(check.shutil, "which", lambda _: str(tmp_path))
    with pytest.raises(ValueError, match="hipcc"):
        check.check_sdk()


@pytest.fixture(name="native_packages")
def _native_packages(packages, tmp_path, monkeypatch):
    paths = {
        "lmcache": ["lmcache/cuda_ops.so"],
        "onnxruntime-rocm": ["onnxruntime/capi/libonnxruntime_providers_rocm.so"],
        "mooncake-transfer-engine-rocm": ["mooncake/engine.so", "mooncake/store.so"],
    }
    for files in paths.values():
        for name in files:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    monkeypatch.setattr(
        check.metadata,
        "distribution",
        lambda package: SimpleNamespace(
            files=paths[package],
            locate_file=lambda name: tmp_path / name,
        ),
    )
    loaded = []
    monkeypatch.setattr(
        check.ctypes,
        "CDLL",
        lambda path, **_: loaded.append(Path(path).relative_to(tmp_path)),
    )
    return paths, loaded, packages[1]


def test_native_gate_loads_required_extensions(native_packages):
    paths, loaded, _ = native_packages
    check.check_native()
    assert set(loaded) == {Path(name) for files in paths.values() for name in files}


def test_native_gate_rejects_cuda_cupy(native_packages):
    _, _, modules = native_packages
    modules["cupy"].cuda.runtime.is_hip = False
    with pytest.raises(ValueError, match="CuPy"):
        check.check_native()


def test_native_gate_rejects_missing_lmcache_extension(native_packages):
    paths, _, _ = native_packages
    paths["lmcache"].clear()
    with pytest.raises(ValueError, match="LMCache has no native extensions"):
        check.check_native()


def test_native_gate_rejects_missing_onnx_provider(native_packages):
    _, _, modules = native_packages
    modules["onnxruntime"].get_available_providers = lambda: ["CPUExecutionProvider"]
    with pytest.raises(ValueError, match="ROCMExecutionProvider"):
        check.check_native()


@pytest.mark.usefixtures("native_packages")
def test_native_gate_rejects_missing_library(tmp_path):
    (tmp_path / "mooncake/engine.so").unlink()
    with pytest.raises(ValueError, match="required native library is missing"):
        check.check_native()


@pytest.mark.usefixtures("native_packages")
def test_native_gate_propagates_unresolved_symbols(monkeypatch):
    def unresolved(*_args, **_kwargs):
        msg = "undefined symbol: hipMemcpy"
        raise OSError(msg)

    monkeypatch.setattr(check.ctypes, "CDLL", unresolved)
    with pytest.raises(OSError, match="undefined symbol"):
        check.check_native()


@pytest.mark.parametrize("prefix", ["LC", "VL"])
@pytest.mark.parametrize(
    "runtime,override,base,expected",
    [
        ("10.0.0", "", "gfx942;gfx950", "gfx942;gfx950"),
        ("10.0.0", "gfx1100", "gfx942;gfx950", "gfx1100"),
        ("7.2.3", "gfx942", "gfx950", "gfx942"),
        ("10.0.0", "", "", None),
    ],
)
def test_build_stages_select_gpu_targets(prefix, runtime, override, base, expected):
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text()
    start = recipe.index(f'    {prefix}_ROCM_ARCHS="')
    end = recipe.index(
        f'    export PYTORCH_ROCM_ARCH="${{{prefix}_ROCM_ARCHS}}"',
        start,
    )
    end = recipe.index("\n", end)
    if prefix == "LC":
        end = recipe.index("    export TORCH_DONT_CHECK_COMPILER_ABI", end)
    result = subprocess.run(  # noqa: S603 - execute only the recipe's environment selection.
        [  # noqa: S607 - Bash is required by the repository and recipe.
            "bash",
            "-eu",
            "-c",
            recipe[start:end]
            + '\nprintf "%s\\n%s" "$PYTORCH_ROCM_ARCH" "${HIPCC_COMPILE_FLAGS_APPEND:-}"',
        ],
        env={
            **os.environ,
            "ROCM_VERSION": runtime,
            "ROCM_ARCHS": override,
            "PYTORCH_ROCM_ARCH": base,
            "CMAKE_MAX_JOBS": "4",
            "HIPCC_COMPILE_FLAGS_APPEND": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if expected is None:
        assert result.returncode != 0
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        targets, flags = result.stdout.split("\n", 1)
        assert targets == expected
        expected_flags = (
            " ".join(f"--offload-arch={arch}" for arch in expected.split(";"))
            if runtime == "10.0.0" and prefix == "LC"
            else ""
        )
        assert flags.strip() == expected_flags


@pytest.mark.parametrize(
    "runtime,exit_code",
    [("7.2.3", 0), ("10.0.0", 0), ("10.0.0", 42)],
)
def test_final_image_gate_runs_for_therock_and_propagates_failure(
    tmp_path,
    runtime,
    exit_code,
):
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text()
    start = recipe.index("RUN --mount=type=bind,source=check_vllm.py")
    block = recipe[start:].split("<<EOF\n", 1)[1].split("\nEOF", 1)[0]
    command = tmp_path / "python"
    command.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$CHECK_ARGS"\nexit "$CHECK_EXIT"\n',
    )
    command.chmod(0o755)
    arguments = tmp_path / "arguments"
    result = subprocess.run(  # noqa: S603 - fake Python records the recipe's invocation.
        ["bash", "-eo", "pipefail", "-c", block],  # noqa: S607
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "ROCM_VERSION": runtime,
            "VLLM_VERSION": "0.33.0",
            "VLLM_TORCH_VERSION": "2.13.0",
            "VLLM_LMCACHE_VERSION": "0.5.6",
            "VLLM_MOONCAKE_VERSION": "0.3.13.post1",
            "CHECK_ARGS": str(arguments),
            "CHECK_EXIT": str(exit_code),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code, result.stderr
    if runtime == "7.2.3":
        assert not arguments.exists()
    else:
        assert arguments.read_text().splitlines() == [
            "/tmp/check_vllm.py",  # noqa: S108 - the Docker mount path, never written by this fixture.
            "--runtime",
            "10.0.0",
            "--vllm",
            "0.33.0",
            "--torch",
            "2.13.0",
            "--lmcache",
            "0.5.6",
            "--mooncake",
            "0.3.13.post1",
        ]
