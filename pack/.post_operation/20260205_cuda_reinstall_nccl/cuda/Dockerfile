ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.14.1
ARG SGLANG_VERSION=0.5.8

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Reinstall NCCL packages

RUN <<EOF
    # Reinstall NCCL packages

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    uv pip install nvidia-nccl-cu${CUDA_MAJOR}==2.27.5

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]


FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Reinstall NCCL packages

RUN <<EOF
    # Reinstall NCCL packages

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    uv pip install nvidia-nccl-cu${CUDA_MAJOR}==2.27.5

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
