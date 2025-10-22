ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG VLLM_VERSION=0.10.0

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Ray Default

RUN <<EOF
    # Ray Default

    # Install Ray Default
    RAY_VERSION=$(pip show ray | grep Version: | cut -d' ' -f 2)
    uv pip install "ray[default]==${RAY_VERSION}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
