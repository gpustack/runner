ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.10.0
ARG VLLM_LMCACHE_VERSION=0.3.3

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install LMCache

ARG CMAKE_MAX_JOBS
ARG VLLM_LMCACHE_VERSION

ENV VLLM_LMCACHE_VERSION=${VLLM_LMCACHE_VERSION}

RUN <<EOF
    # Rebuild LMCache

    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L67-L129.

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Support ARM64 only for CUDA 12.8 and above
    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping LMCache rebuilding for ${TARGETARCH}..."
        exit 0
    fi

    # Install LMCache
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    LC_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${LC_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
            LC_CUDA_ARCHS="7.5 8.0+PTX 8.9"
        elif (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
            LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX"
        else
            LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX 10.0+PTX 12.0+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${LC_CUDA_ARCHS}"

    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    pip install -v --no-build-isolation /tmp/lmcache

    # Review
    uv pip tree \
        --package vllm \
        --package lmcache \
        --package torch

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
