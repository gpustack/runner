ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.12.0
ARG VLLM_OMNI_COMMIT=f9b8bfd

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm-build-omni
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

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${CANN_HOME}/ascend-toolkit/latest/$(uname -i)-linux/devlib"
    export VLLM_TARGET_DEVICE="empty"
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

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
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
