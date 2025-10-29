ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.2
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.9.1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Reinstall Ray

RUN <<EOF
    # Ray

    # Reinstall Ray
    cat <<EOT >/tmp/requirements.txt
ray[client]>=2.47.1,<=2.48.0
ray[default]>=2.47.1,<=2.48.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
