ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG SGLANG_VERSION=0.5.5
ARG SGLANG_FLASHATTN_VERSION=2.8.3

FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install FlashAttention

ARG CMAKE_MAX_JOBS
ARG SGLANG_FLASHATTN_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_FLASHATTN_VERSION=${SGLANG_FLASHATTN_VERSION}

RUN <<EOF
    # SGLang

    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping SGLang FlashAttention for ${TARGETARCH}..."
        exit 0
    fi

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"
    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r PYTHON_MAJOR PYTHON_MINOR <<< "${PYTHON_VERSION}"

    # Install
    uv pip install --verbose \
        https://github.com/Dao-AILab/flash-attention/releases/download/v${SGLANG_FLASHATTN_VERSION}/flash_attn-${SGLANG_FLASHATTN_VERSION}+cu${CUDA_MAJOR}torch${TORCH_MAJOR}.${TORCH_MINOR}cxx11abiFALSE-cp${PYTHON_MAJOR}${PYTHON_MINOR}-cp${PYTHON_MAJOR}${PYTHON_MINOR}-linux_$(uname -m).whl

    # Review
    uv pip tree \
        --package sglang \
        --package sglang-router \
        --package sgl-kernel \
        --package flashinfer-python \
        --package triton \
        --package vllm \
        --package torch \
        --package deep-ep \
        --package diffusers \
        --package opencv-python \
        --package flash-attn

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
