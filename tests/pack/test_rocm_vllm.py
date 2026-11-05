"""Exercise ROCm vLLM compiler target selection without building images."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


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
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text(encoding="utf-8")
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
