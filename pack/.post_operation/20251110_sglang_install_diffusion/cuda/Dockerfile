ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG SGLANG_VERSION=0.5.5

FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Diffusion Extension

ARG CMAKE_MAX_JOBS

ENV SGLANG_VERSION=${SGLANG_VERSION}

RUN <<EOF
    # SGLang

    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping SGLang diffusion extension for ${TARGETARCH}..."
        exit 0
    fi

    # Install dependencies
    apt update -y && apt install -y --no-install-recommends \
         ffmpeg

    # Install SGLang
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang-${SGLANG_VERSION}
    pushd /tmp/sglang-${SGLANG_VERSION}/python \
        && uv pip install --verbose .[diffusion]

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
        --package opencv-python

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
