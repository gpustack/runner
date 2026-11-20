"""Resolve the recipe's Ray extras offline, without GPU wheels or image builds."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _wheel(directory: Path, name: str, version: str, metadata: str = "") -> None:
    stem = name.replace("-", "_")
    info = f"{stem}-{version}.dist-info"
    with ZipFile(directory / f"{stem}-{version}-py3-none-any.whl", "w") as wheel:
        wheel.writestr(
            f"{info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{metadata}",
        )
        wheel.writestr(
            f"{info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr(f"{info}/RECORD", "")


def _extract_ray_requirements(recipe: str) -> tuple[str, str]:
    block = recipe.split("## Install Ray\n", 1)[1]
    next_section = re.search(r"\n## ", block)
    if next_section is not None:
        block = block[: next_section.start()]
    requirements = block.split("cat <<EOT >/tmp/requirements.txt\n", 1)[1].split(
        "\nEOT",
        1,
    )[0]
    match = re.search(r"RAY_VERSION=([^\s]+)", block) or re.search(
        r"^ARG\s+RAY_VERSION=([^\s]+)",
        recipe,
        re.MULTILINE,
    )
    if match is not None:
        version = match.group(1).strip('"')
        requirements = requirements.replace("${RAY_VERSION}", version).replace(
            "$RAY_VERSION",
            version,
        )
        return version, requirements
    pinned = re.search(r"^ray\[[^\]]+\]==([^\s,;]+)", requirements, re.MULTILINE)
    if pinned is not None:
        return pinned.group(1), requirements
    bounded = re.search(r"^ray\[[^\]]+\]>?=([^\s,;]+)", requirements, re.MULTILINE)
    return (bounded.group(1) if bounded is not None else "2.54.0"), requirements


@pytest.mark.parametrize("add_cuda_extra", [False, True])
def test_rocm_ray_resolution_preserves_hip_cupy(tmp_path, add_cuda_extra):
    recipe = (ROOT / "pack/rocm/Dockerfile.vllm").read_text(encoding="utf-8")
    version, requirements = _extract_ray_requirements(recipe)

    # Reduced Ray extras matching the pinned version: cgraph's sole dependency is CUDA CuPy.
    # https://github.com/ray-project/ray/blob/48bd1f8fa43d0e8222b0f57357b99b48c7437ed3/python/setup.py
    _wheel(
        tmp_path,
        "ray",
        version,
        "Provides-Extra: cgraph\nProvides-Extra: client\nProvides-Extra: default\n"
        'Requires-Dist: cupy-cuda12x; sys_platform != "darwin" and extra == "cgraph"\n'
        'Requires-Dist: grpcio; extra == "client"\n'
        'Requires-Dist: colorful; extra == "default"\n',
    )
    _wheel(tmp_path, "cupy-cuda12x", "14.2.0")
    _wheel(tmp_path, "cupy-rocm-7-0", "14.2.0")
    _wheel(tmp_path, "grpcio", "1.78.0")
    _wheel(tmp_path, "colorful", "0.6.0")

    requirements += "\ncupy-rocm-7-0==14.2.0\n"
    if add_cuda_extra:
        requirements += f"ray[cgraph]=={version}\n"

    result = subprocess.run(  # noqa: S603 - resolve local fixture wheels only.
        [  # noqa: S607 - uv is the repository's pinned package manager.
            "uv",
            "pip",
            "compile",
            "--offline",
            "--no-index",
            "--no-config",
            "--find-links",
            str(tmp_path),
            "--python-platform",
            "x86_64-unknown-linux-gnu",
            "--python-version",
            "3.12",
            "-",
        ],
        input=requirements,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    resolved = set(re.findall(r"^([^\s=]+)==[^\s]+", result.stdout, re.MULTILINE))
    assert {"ray", "grpcio", "colorful", "cupy-rocm-7-0"} <= resolved
    assert ("cupy-cuda12x" in resolved) is add_cuda_extra
