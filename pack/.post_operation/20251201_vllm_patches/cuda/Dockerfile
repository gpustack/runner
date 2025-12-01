ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG VLLM_VERSION=0.11.2

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    pushd $(pip show vllm | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
