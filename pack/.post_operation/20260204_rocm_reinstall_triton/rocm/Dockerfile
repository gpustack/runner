ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG VLLM_VERSION=0.14.1
ARG SGLANG_VERSION=0.5.8

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Reinstall Triton

RUN <<EOF
    # Reinstall Triton

    # Install
    uv pip install triton==3.5.1

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

## Reinstall Triton

RUN <<EOF
    # Reinstall Triton

    # Install
    uv pip install triton==3.5.1

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
