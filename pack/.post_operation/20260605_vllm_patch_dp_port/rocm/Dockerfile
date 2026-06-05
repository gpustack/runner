ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.2
ARG VLLM_VERSION=0.21.0

FROM gpustack/runner:rocm${ROCM_VERSION}-vllm${VLLM_VERSION} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Patch
#
# Fix the wrong_dp_ray patch shipped in this released image:
#   _next_port = port   ->   _next_port = port + 1
# so get_open_port() advances and never hands out duplicate ports
# (the cause of Ray "address already in use" in distributed serving).
#
# Idempotent & self-verifying: skip if already fixed, fail loudly if the
# expected assignment is absent (so we never produce a silently-unfixed image).

RUN <<EOF
    # Patch

    F="$(pip show vllm | grep Location: | cut -d" " -f 2)/vllm/utils/network_utils.py"
    echo "Target: ${F}"
    grep -n "_next_port" "${F}" || true
    if grep -qE '^[[:space:]]*_next_port = port \+ 1[[:space:]]*$' "${F}"; then
        echo "Already fixed (_next_port = port + 1), skipping."
    elif grep -qE '^[[:space:]]*_next_port = port[[:space:]]*$' "${F}"; then
        sed -i -E 's/^([[:space:]]*)_next_port = port[[:space:]]*$/\1_next_port = port + 1/' "${F}"
        echo "Patched: _next_port = port -> _next_port = port + 1"
    else
        echo "ERROR: expected '_next_port = port' assignment not found in ${F}" >&2
        exit 1
    fi
    grep -n "_next_port" "${F}"
EOF

## Pin Ray
# Downgrade Ray to 2.54.0: ray 2.55 (ray-project/ray#61029) breaks distributed
# ray.init when the driver has no co-located raylet (gpustack runs vllm and
# ray-head in separate containers). vLLM only needs ray>=2.x.

RUN <<EOF
    # Pin Ray
    pip install --no-cache-dir ray==2.54.0
    pip show ray | grep -i '^Version:' || true
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
