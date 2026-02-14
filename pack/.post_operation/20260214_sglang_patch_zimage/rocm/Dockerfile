ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG SGLANG_VERSION=0.5.8.post1

FROM gpustack/runner:rocm${ROCM_VERSION}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    tree -hs /workspace/patches
    pushd $(pip show sglang | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/sglang/*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
