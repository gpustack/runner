ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG MINDIE_VERSION=2.2.rc1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-mindie${MINDIE_VERSION} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install AV

RUN <<EOF
    # AV

    # Install
    uv pip install \
        av==16.0.1

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
