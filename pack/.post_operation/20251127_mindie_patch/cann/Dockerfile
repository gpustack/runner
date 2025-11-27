ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG MINDIE_VERSION=2.2.rc1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-mindie${MINDIE_VERSION} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch

ADD --chown=root:root patches.tar.gz /workspace/patches/
RUN <<EOF
    # Patch

    pushd $(pip show mindie_llm | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
