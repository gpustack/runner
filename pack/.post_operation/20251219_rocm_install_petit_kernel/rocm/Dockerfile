ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG VLLM_VERSION=0.12.0
ARG SGLANG_VERSION=0.5.6.post2

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Petit Kernel

RUN <<EOF
    # Petit Kernel

    # Install
    uv pip install petit-kernel

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]


FROM gpustack/runner:rocm${ROCM_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Petit Kernel

RUN <<EOF
    # Petit Kernel

    # Install
    uv pip install petit-kernel

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
