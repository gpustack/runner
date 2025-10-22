ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.3
ARG VLLM_VERSION=0.10.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
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

ENV RAY_EXPERIMENTAL_NOSET_HIP_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
