ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=6.4
ARG VLLM_VERSION=0.12.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Audio Extras

RUN <<EOF
    # Audio Extras

    # Install
    cat <<EOT >/tmp/requirements.txt
# audio extras
librosa
soundfile
mistral_common[audio]
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
