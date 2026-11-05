"""Exercise image inspection with real host/provider libraries and fake packages."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _compile_library(path: Path, source: str) -> None:
    compiler = shutil.which("cc")
    assert compiler, "native loading tests require a C compiler"
    path.parent.mkdir(parents=True, exist_ok=True)
    source_file = path.with_suffix(".c")
    source_file.write_text(source, encoding="utf-8")
    flags = (
        ["-dynamiclib", "-undefined", "dynamic_lookup"]
        if sys.platform == "darwin"
        else ["-shared", "-fPIC"]
    )
    subprocess.run(  # noqa: S603 - compile only the local fixture source.
        [compiler, *flags, str(source_file), "-o", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "missing_symbol",
    [None, "RunnerMissingHIPSymbol", "missing_host"],
)
def test_native_gate_resolves_provider_host_and_rejects_other_missing_symbols(
    tmp_path,
    missing_symbol,
):
    _compile_library(
        tmp_path / "onnxruntime/capi/libonnxruntime_providers_shared.so",
        "static int host;\nvoid Provider_SetHost(void) { host = 42; }\n"
        "int Provider_GetHost(void) { return host; }\n",
    )
    symbol = (
        "RunnerMissingHIPSymbol"
        if missing_symbol == "RunnerMissingHIPSymbol"
        else "Provider_GetHost"
    )
    _compile_library(
        tmp_path / "onnxruntime/capi/libonnxruntime_providers_rocm.so",
        f"extern int {symbol}(void);\nstatic int host;\n"
        f"__attribute__((constructor)) static void init(void) {{ host = {symbol}(); }}\n"
        "int probe(void) { return host; }\n",
    )
    for name in ["lmcache/cuda_ops.so", "mooncake/engine.so", "mooncake/store.so"]:
        _compile_library(tmp_path / name, "int probe(void) { return 0; }\n")

    # Model ORT 1.22.2's import-time InitProvidersSharedLibrary call with a real
    # native host library. Its provider bridge needs these global symbols.
    (tmp_path / "onnxruntime/__init__.py").write_text(
        "import ctypes, os\nfrom pathlib import Path\n"
        "host = ctypes.CDLL(str(Path(__file__).parent / 'capi/libonnxruntime_providers_shared.so'), "
        "mode=os.RTLD_NOW | os.RTLD_GLOBAL)\n"
        "host.Provider_SetHost()\n"
        "def get_available_providers(): return ['ROCMExecutionProvider']\n",
        encoding="utf-8",
    )
    if missing_symbol == "missing_host":
        (tmp_path / "onnxruntime/capi/libonnxruntime_providers_shared.so").unlink()

    # Isolate RTLD_GLOBAL symbols between cases. Only the package discovery and
    # Python imports are faked; the production checker uses the real dynamic loader.
    script = """
import ctypes
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("check_vllm", sys.argv[1])
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
root = Path(sys.argv[2])
sys.path.insert(0, str(root))
check.metadata.distribution = lambda _: SimpleNamespace(
    files=["lmcache/cuda_ops.so"], locate_file=lambda name: root / name,
)
sys.modules.update({
    "vllm._C": SimpleNamespace(),
    "cupy": SimpleNamespace(cuda=SimpleNamespace(runtime=SimpleNamespace(is_hip=True))),
    "mooncake.engine": SimpleNamespace(),
    "vllm_omni": SimpleNamespace(),
})
check.check_native()
provider = ctypes.CDLL(str(root / "onnxruntime/capi/libonnxruntime_providers_rocm.so"), mode=os.RTLD_NOW)
assert provider.probe() == 42
"""
    result = subprocess.run(  # noqa: S603 - run image inspection on fixture libraries.
        [
            sys.executable,
            "-c",
            script,
            str(ROOT / "pack/rocm/check_vllm.py"),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if missing_symbol == "missing_host":
        assert result.returncode != 0
        assert "libonnxruntime_providers_shared.so" in result.stderr
    elif missing_symbol:
        assert result.returncode != 0
        assert missing_symbol in result.stderr
    else:
        assert result.returncode == 0, result.stderr
