ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG VLLM_VERSION=0.12.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm-build-omni
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build Omni

ARG CMAKE_MAX_JOBS
ARG VLLM_OMNI_COMMIT

ENV VLLM_OMNI_COMMIT=${VLLM_OMNI_COMMIT}

RUN <<EOF
    # Omni

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r VL_MAJOR VL_MINOR VL_PATCH <<< "${VLLM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    VL_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${VL_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
            if (( $(echo "${VL_MAJOR}.${VL_MINOR} == 0.13" | bc -l) )); then
                # TODO(thxCode): Temporarily remove gfx1030 for vLLM ROCm build due to build error in ROCm 6.4.4.
                # #15 134.9 /tmp/vllm/build/temp.linux-x86_64-cpython-312/csrc/sampler.hip:564:63: error: local memory (66032) exceeds limit (65536) in 'void vllm::topKPerRowDecode<1024, true, false, true>(float const*, int const*, int*, int, int, int, int, float*, int, int const*)'
                # ##15 134.9   564 | static __global__ __launch_bounds__(kNumThreadsPerBlock) void topKPerRowDecode(
                # ##15 134.9       |                                                               ^
                # ##15 134.9 16 warnings and 1 error generated when compiling for gfx1030.
                VL_ROCM_ARCHS="gfx908;gfx90a;gfx942"
            fi
        else
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export PYTORCH_ROCM_ARCH="${VL_ROCM_ARCHS}"
    echo "Building vLLM Omni with the following environment variables:"
    env

    # Build
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/vllm-project/vllm-omni vllm_omni \
        && pushd /tmp/vllm_omni \
        && git checkout ${VLLM_OMNI_COMMIT} \
        && git submodule update --init --recursive
    pushd /tmp/vllm_omni \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/vllm_omni/dist \
        && mv /tmp/vllm_omni/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Omni

RUN --mount=type=bind,from=vllm-build-omni,source=/,target=/omni,rw <<EOF
    # Omni

    # Install
    uv pip install --no-build-isolation \
        /omni/workspace/*.whl

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
