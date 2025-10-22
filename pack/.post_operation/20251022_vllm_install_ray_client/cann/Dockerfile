ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.2
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.9.1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Ray Client

RUN <<EOF
    # Ray Client

    # Install Ray Client
    RAY_VERSION=$(pip show ray | grep Version: | cut -d' ' -f 2)
    uv pip install "ray[client]==${RAY_VERSION}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_ASCEND_RT_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
