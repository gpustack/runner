ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.8
ARG SGLANG_VERSION=0.5.6.post2

FROM gpustack/runner:cuda${CUDA_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    tree -hs /workspace/patches
    pushd $(pip show sglang | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
