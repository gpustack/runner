ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG MINDIE_VERSION=2.2.rc1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-mindie${MINDIE_VERSION} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Posix IPC

RUN <<EOF
    # Posix IPC

    # Install
    uv pip install \
        posix_ipc==1.2.0

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
