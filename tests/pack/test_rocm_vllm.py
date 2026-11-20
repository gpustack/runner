"""Exercise ROCm vLLM compiler target selection without building images."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _active_rocm_vllm_runtimes() -> list[str]:
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text(encoding="utf-8")
    default_match = re.search(r"^ARG\s+ROCM_VERSION=([^\s]+)", recipe, re.MULTILINE)
    default_runtime = default_match.group(1).strip('"') if default_match else ""
    rules = yaml.safe_load((ROOT / "pack/matrix.yaml").read_text(encoding="utf-8"))[
        "rules"
    ]
    runtimes: list[str] = []
    for rule in rules:
        if rule.get("backend") != "rocm" or "vllm" not in (rule.get("services") or []):
            continue
        args = dict(arg.split("=", 1) for arg in rule.get("args") or [])
        runtime = args.get("ROCM_VERSION") or default_runtime
        if runtime and runtime not in runtimes:
            runtimes.append(runtime)
    assert runtimes, "expected at least one rocm/vllm runtime in pack/matrix.yaml"
    return runtimes


def _is_therock_runtime(runtime: str) -> bool:
    return int(runtime.split(".", 1)[0]) >= 10


def _extract_target_selection_snippet(recipe: str, prefix: str) -> str:
    start = recipe.index(f'    {prefix}_ROCM_ARCHS="')
    end = recipe.index(
        f'    export PYTORCH_ROCM_ARCH="${{{prefix}_ROCM_ARCHS}}"',
        start,
    )
    end = recipe.index("\n", end)
    if prefix == "LC":
        end = recipe.index("    export TORCH_DONT_CHECK_COMPILER_ABI", end)
    return recipe[start:end]


def _run_selection(
    snippet: str,
    runtime: str,
    override: str,
    base: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - execute only the recipe's environment selection.
        [  # noqa: S607 - Bash is required by the repository and recipe.
            "bash",
            "-eu",
            "-c",
            snippet
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


@pytest.mark.parametrize("prefix", ["LC", "VL"])
@pytest.mark.parametrize("runtime", _active_rocm_vllm_runtimes())
@pytest.mark.parametrize(
    "override,base,expected_mode",
    [
        ("", "gfx942;gfx950", "inherit_or_default"),
        ("gfx1100", "gfx942;gfx950", "override"),
        ("", "", "empty_base"),
    ],
)
def test_build_stages_select_gpu_targets(
    prefix,
    runtime,
    override,
    base,
    expected_mode,
):
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text(encoding="utf-8")
    snippet = _extract_target_selection_snippet(recipe, prefix)
    result = _run_selection(snippet, runtime, override, base)
    therock = _is_therock_runtime(runtime)

    if expected_mode == "empty_base" and therock:
        assert result.returncode != 0
        assert not result.stdout
        return

    assert result.returncode == 0, result.stderr
    targets, flags = result.stdout.split("\n", 1)
    if expected_mode == "override":
        assert targets == override
    elif expected_mode == "inherit_or_default":
        if therock:
            assert targets == base
        else:
            assert targets
    else:
        assert targets

    expected_flags = (
        " ".join(f"--offload-arch={arch}" for arch in targets.split(";"))
        if therock and prefix == "LC"
        else ""
    )
    assert flags.strip() == expected_flags


@pytest.mark.parametrize("prefix", ["LC", "VL"])
def test_build_stages_respect_override_for_legacy_runtime(prefix):
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text(encoding="utf-8")
    snippet = _extract_target_selection_snippet(recipe, prefix)
    result = _run_selection(snippet, "7.2.3", "gfx942", "gfx950")
    assert result.returncode == 0, result.stderr
    targets, flags = result.stdout.split("\n", 1)
    assert targets == "gfx942"
    hipcc_gated = "ROCM_VERSION" in snippet.split("export PYTORCH_ROCM_ARCH", 1)[-1]
    if prefix == "LC" and not hipcc_gated:
        assert flags.strip() == "--offload-arch=gfx942"
    else:
        assert flags.strip() == ""
