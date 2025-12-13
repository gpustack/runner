ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG MINDIE_VERSION=2.2.rc1

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-mindie${MINDIE_VERSION} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch MiniCPM Qwen2 V2

ADD --chmod=550 https://modelscope.cn/models/OpenBMB/MiniCPM-V-2_6/resolve/master/resampler.py /usr/local/Ascend/atb-models/atb_llm/models/minicpm_qwen2_v2/
RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    unzip /workspace/patches.zip -d /workspace
    pushd /usr/local/Ascend/atb-models \
        && patch -p1 < /workspace/patches/*.patch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
