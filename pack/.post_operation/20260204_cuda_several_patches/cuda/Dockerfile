ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.14.1
ARG SGLANG_VERSION=0.5.8

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Update CuDNN and NCCL packages

RUN <<EOF
    # Update CuDNN and NCCL packages

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    cat <<EOT >/tmp/requirements.txt
nvidia-cudnn-cu${CUDA_MAJOR}>=9.16.0.29
nvidia-cudnn-frontend>=1.17.0
nvidia-nccl-cu${CUDA_MAJOR}>=2.28.3
EOT
    uv pip install \
        -r /tmp/requirements.txt

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

## Update CuDNN and NCCL packages

RUN <<EOF
    # Update CuDNN and NCCL packages

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    cat <<EOT >/tmp/requirements.txt
nvidia-cudnn-cu${CUDA_MAJOR}>=9.16.0.29
nvidia-cudnn-frontend>=1.17.0
nvidia-nccl-cu${CUDA_MAJOR}>=2.28.3
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

ENV SGLANG_DISABLE_CUDNN_CHECK=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
