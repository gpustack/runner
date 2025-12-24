ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG MINDIE_VERSION=2.2.rc1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-mindie${MINDIE_VERSION} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch ATB Config

RUN <<EOF
    # Patch ATB Config

    sed -i "s/\"ep_level\": 2/\"ep_level\": 1/g" ${CANN_HOME}/atb-models/atb_llm/conf/config.json

EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
