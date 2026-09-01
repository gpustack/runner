ARG DTK_VERSION=26.04
ARG VLLM_VERSION=0.18.1

FROM gpustack/runner:dtk${DTK_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Restore NumPy 1.x ABI compatibility

# The DTK base image currently ships a Torch build compiled against the NumPy
# 1.x ABI. NumPy 2.x cannot initialize in that Torch build, which causes
# distributed initialization to fail when it calls Tensor.numpy().
#
# Install without dependencies to avoid changing the prebuilt DTK Python
# environment beyond the NumPy compatibility pin.
RUN <<EOF
    uv pip install --no-deps "numpy==1.26.4"

    python - <<'PYEOF'
import numpy

assert numpy.__version__ == "1.26.4", \
    f"expected numpy 1.26.4, got {numpy.__version__}"
PYEOF
EOF

## Remove CUDA-only NIXL EP packages

# The prebuilt DTK vLLM base image can inherit NIXL Expert Parallel packages
# from its Python environment. NIXL EP provides NVIDIA CUDA backends which
# require libcuda.so.1 and cannot run on Hygon DCU systems.
#
# vLLM detects NIXL EP through importlib.util.find_spec("nixl_ep"). Remove
# the distributions entirely, rather than leaving an ImportError stub, so
# vLLM selects its non-NIXL path. Use uv to resolve the active Python
# environment and package paths instead of relying on a fixed site-packages
# location.
RUN <<EOF
    # The NIXL EP modules are owned by the nixl, nixl-cu12, and nixl-cu13
    # distributions in the DTK base image. Do not fail if a future base image
    # no longer includes one of them; the import check below remains required.
    uv pip uninstall nixl nixl-cu12 nixl-cu13 || true

    python - <<'PYEOF'
import importlib.util

for module_name in ("nixl_ep", "nixl_ep_cu12", "nixl_ep_cu13"):
    assert importlib.util.find_spec(module_name) is None, \
        f"{module_name} is still discoverable after DTK image cleanup"
PYEOF
EOF

RUN <<EOF
    # Review
    uv pip tree \
        --package numpy \
        --package torch \
        --package vllm
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
