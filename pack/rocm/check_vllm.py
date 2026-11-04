"""
Reject a mixed ROCm stack before publishing a TheRock-based vLLM image.

These checks need no GPU. They verify package identity and native library
loading; inference and transfers still need the target hardware.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import os
import shutil
from importlib import metadata
from pathlib import Path

from packaging.version import Version


def check_versions(expected: dict[str, str], runtime: str) -> None:
    for package, version in expected.items():
        actual = metadata.version(package)
        if Version(actual).public != Version(version).public:
            msg = f"{package}: expected {version}, installed {actual}"
            raise ValueError(msg)
    torch = importlib.import_module("torch")
    if not torch.version.hip or torch.version.cuda:
        msg = "TheRock image requires ROCm PyTorch"
        raise ValueError(msg)
    local = Version(metadata.version("torch")).local or ""
    if local != f"rocm{runtime}":
        msg = f"PyTorch does not match the ROCm {runtime} base: {local}"
        raise ValueError(msg)


def check_sdk() -> None:
    root = Path(os.environ["ROCM_PATH"]).resolve(strict=True)
    for name in ("ROCM_HOME", "HIP_PATH"):
        if Path(os.environ[name]).resolve(strict=True) != root:
            msg = f"{name} differs from the base image's ROCM_PATH"
            raise ValueError(msg)
    # TheRock ships hipcc in core; devel/bin may link to that executable.
    core = Path(
        metadata.distribution("rocm-sdk-core").locate_file("_rocm_sdk_core"),
    ).resolve(strict=True)
    compiler = shutil.which("hipcc")
    if not compiler or not any(
        Path(compiler).resolve(strict=True).is_relative_to(path)
        for path in (root, core)
    ):
        msg = "hipcc does not belong to the base image's ROCm SDK"
        raise ValueError(msg)


def load_extensions(package: str, paths: list[str]) -> None:
    distribution = metadata.distribution(package)
    for name in paths:
        path = Path(distribution.locate_file(name))
        if not path.is_file():
            msg = f"{package}: required native library is missing: {name}"
            raise ValueError(msg)
        ctypes.CDLL(str(path), mode=os.RTLD_NOW)


def check_native() -> None:
    importlib.import_module("vllm._C")
    cupy = importlib.import_module("cupy")
    if not cupy.cuda.runtime.is_hip:
        msg = "CuPy was built for CUDA instead of HIP"
        raise ValueError(msg)
    files = metadata.distribution("lmcache").files or []
    extensions = [
        str(path)
        for path in files
        if str(path).startswith("lmcache/") and str(path).endswith(".so")
    ]
    if not extensions:
        msg = "LMCache has no native extensions"
        raise ValueError(msg)
    load_extensions("lmcache", extensions)
    # Provider enumeration alone does not load the provider's shared library.
    load_extensions(
        "onnxruntime-rocm",
        ["onnxruntime/capi/libonnxruntime_providers_rocm.so"],
    )
    onnxruntime = importlib.import_module("onnxruntime")
    if "ROCMExecutionProvider" not in onnxruntime.get_available_providers():
        msg = "ONNX Runtime lacks ROCMExecutionProvider"
        raise ValueError(msg)
    load_extensions(
        "mooncake-transfer-engine-rocm",
        ["mooncake/engine.so", "mooncake/store.so"],
    )
    importlib.import_module("mooncake.engine")
    importlib.import_module("vllm_omni")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--vllm", required=True)
    parser.add_argument("--torch", required=True)
    parser.add_argument("--lmcache", required=True)
    parser.add_argument("--mooncake", required=True)
    args = parser.parse_args()
    check_sdk()
    check_versions(
        {
            "rocm-sdk-core": args.runtime,
            "vllm": args.vllm,
            "torch": args.torch,
            "lmcache": args.lmcache,
            "mooncake-transfer-engine-rocm": args.mooncake,
        },
        args.runtime,
    )
    check_native()
    print("ROCm package and native-library checks passed; GPU execution is unverified.")


if __name__ == "__main__":
    main()
