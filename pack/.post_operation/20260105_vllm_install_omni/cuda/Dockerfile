ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.12.0
ARG VLLM_OMNI_COMMIT=75cdf1c

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm-build-omni
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build Omni

ARG CMAKE_MAX_JOBS
ARG VLLM_OMNI_COMMIT

ENV VLLM_OMNI_COMMIT=${VLLM_OMNI_COMMIT}

RUN <<EOF
    # Omni

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    VL_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${VL_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            VL_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0+PTX 12.0+PTX"
        else
            VL_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0 10.3 12.0 12.1+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${VL_CUDA_ARCHS}"
    export NVCC_THREADS=1
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

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
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
