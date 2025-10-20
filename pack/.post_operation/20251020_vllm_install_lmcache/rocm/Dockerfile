ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.3
ARG VLLM_VERSION=0.10.0
ARG VLLM_LMCACHE_VERSION=0.3.3

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install LMCache

ARG CMAKE_MAX_JOBS
ARG VLLM_LMCACHE_VERSION

ENV VLLM_LMCACHE_VERSION=${VLLM_LMCACHE_VERSION}

RUN <<EOF
    # LMCache

    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L184-L237.

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    LC_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${LC_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} <= 6.2" | bc -l) )); then
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101"
        else
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${ROCM_ARCHS}"
    export TORCH_DONT_CHECK_COMPILER_ABI=1
    export CXX=hipcc
    export BUILD_WITH_HIP=1

    # Install LMCache
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    fi
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
