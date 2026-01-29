ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG VLLM_VERSION=0.13.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    tree -hs /workspace/patches
    pushd $(pip show vllm | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/vllm_*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
