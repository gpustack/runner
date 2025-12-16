ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.12.0
ARG SGLANG_VERSION=0.5.6.post2

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Environment variables

ENV RUNAI_STREAMER_MEMORY_LIMIT=0 \
    RUNAI_STREAMER_LOG_TO_STDERR=1 \
    RUNAI_STREAMER_LOG_LEVEL=INFO

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]


FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Uninstall Run:AI Model Streamer

RUN <<EOF
    # Uninstall Run:AI Model Streamer

    # Uninstall
    uv pip uninstall \
        runai-model-streamer || true

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Environment variables

ENV RUNAI_STREAMER_MEMORY_LIMIT=0 \
    RUNAI_STREAMER_LOG_TO_STDERR=1 \
    RUNAI_STREAMER_LOG_LEVEL=INFO

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
