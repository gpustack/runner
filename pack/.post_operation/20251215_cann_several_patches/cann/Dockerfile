ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.11.0
ARG SGLANG_VERSION=0.5.6.post2

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Triton Ascend

RUN <<EOF
    # Triton Ascend

    # Install
    uv pip install triton-ascend

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Environment variables

ENV PATH="/usr/local/Ascend/ascend-toolkit/latest/bisheng_toolkit/bishengir/bin:${PATH}"

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Environment variables

ENV PATH="/usr/local/Ascend/ascend-toolkit/latest/bisheng_toolkit/bishengir/bin:${PATH}"

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
