ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.12.0
ARG SGLANG_VERSION=0.5.6.post2

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## NVSHMEM

RUN <<EOF
    # NVSHMEM

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    uv pip install nvshmem4py-cu${CUDA_MAJOR}

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Environment variables

ENV PATH="/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/cuda/nvvm/bin:${PATH}" \
    LD_LIBRARY_PATH="/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda/lib64:${LD_LIBRARY_PATH}"

RUN <<EOF
    # Environment variables

    # Review
    env
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]


FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## NVSHMEM

RUN <<EOF
    # NVSHMEM

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    uv pip install nvshmem4py-cu${CUDA_MAJOR}

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Environment variables

ENV PATH="/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/cuda/nvvm/bin:${PATH}" \
    LD_LIBRARY_PATH="/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda/lib64:${LD_LIBRARY_PATH}"

RUN <<EOF
    # Environment variables

    # Review
    env
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
