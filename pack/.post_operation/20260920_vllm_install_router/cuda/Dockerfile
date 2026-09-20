ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.9
ARG VLLM_VERSION=0.27.1
ARG VLLM_ROUTER_VERSION=0.1.15

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install vLLM Router
##
## `pack/cuda/Dockerfile.vllm` only gained the router after 0.27.1 was cut, so the released 0.27.1
## images carry none of it: a disaggregated group deployed on them has no router to run, and either
## falls back to an engine example script (no metrics, no circuit breaker, no health check) or does
## not start at all. 0.29.0 already ships it, which is why 0.27.1 is the only CUDA runner here.
##
## Pinned to the same 0.1.15 the recipe installs, so that a 0.27.1 image and a 0.29.0 image render
## the same router. The wheel is prebuilt for both aarch64 and x86_64, and it depends on nothing
## but pure-Python web packages (fastapi, uvicorn, aiohttp, orjson, requests, setproctitle) -- it
## does not depend on vLLM, so this install cannot move the torch/vLLM stack already in the image.

ARG VLLM_ROUTER_VERSION

RUN <<EOF
    # vLLM Router

    uv pip install \
        vllm-router==${VLLM_ROUTER_VERSION}

    # Fail the build rather than ship an image whose router is missing: the
    # alternative surfaces as a container that exits at deploy time, one
    # layer away from anything that explains it.
    command -v vllm-router >/dev/null

    # Review
    uv pip tree

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Probe Dependencies

ARG DEPENDENCY_PACKAGES=""
RUN --mount=type=bind,from=shared,source=probe_dependencies.sh,target=/tmp/probe_dependencies.sh \
    DEPENDENCY_PACKAGES="${DEPENDENCY_PACKAGES}" bash /tmp/probe_dependencies.sh

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

## Export Dependencies

FROM scratch AS vllm-deps

COPY --from=vllm /etc/gpustack-runner/dependencies.json /
