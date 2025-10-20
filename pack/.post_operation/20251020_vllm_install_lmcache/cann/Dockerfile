ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.2
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.9.1
ARG VLLM_LMCACHE_VERSION=0.3.3

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
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

    # Ref https://github.com/LMCache/LMCache-Ascend/blob/aa9cec2fc23ff318d0c94ab907f599419042ba4c/README.md?plain=1#L112-L128.

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export NO_CUDA_EXT=1
    export TORCH_DONT_CHECK_COMPILER_ABI=1
    source ${CANN_HOME}/ascend-toolkit/set_env.sh
    source ${CANN_HOME}/nnal/atb/set_env.sh
    export SOC_VERSION="ASCEND910B3"
    if [[ "${CANN_ARCHS}" == "310p" ]]; then
        export SOC_VERSION="ASCEND310P3"
    fi
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/Ascend/ascend-toolkit/latest/$(uname -i)-linux/devlib"

    # Install LMCache
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    fi
    pip install -v /tmp/lmcache

    # Install LMCache Ascend
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache-Ascend.git lmcache-ascend
    VLLM_ASCEND_LIB_PREFIX=$(pip show vllm-ascend | grep Location: | cut -d' ' -f 2)
    cd "${VLLM_ASCEND_LIB_PREFIX}" \
        && git apply -p1 /tmp/lmcache-ascend/docker/kv-connector-v1.diff
    # - Workaround: change /bin/sh to bash for lmcache-ascend build script
    mv /bin/sh /bin/sh.bak \
        && ln -s /bin/bash /bin/sh \
        && pip install -v --no-build-isolation /tmp/lmcache-ascend \
        && mv /bin/sh.bak /bin/sh

    # Review
    uv pip tree \
        --package vllm \
        --package vllm-ascend \
        --package torch \
        --package torch-npu \
        --package lmcache \
        --package lmcache-ascend

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
