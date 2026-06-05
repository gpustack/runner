ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.5
ARG CANN_ARCHS=910b
ARG VLLM_VERSION=0.18.0

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-vllm${VLLM_VERSION} AS vllm
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

    # cann uses vllm-ascend: vllm is an editable checkout and the cann build
    # patches it via `pushd /vllm-workspace/vllm && patch -p1`, so the live file
    # is /vllm-workspace/vllm/vllm/utils/network_utils.py (NOT pip show Location).
    # Prefer that exact path, then fall back to Python import / find.
    F=/vllm-workspace/vllm/vllm/utils/network_utils.py
    [ -f "${F}" ] || F="$(python -c 'import vllm.utils.network_utils as n; print(n.__file__)' 2>/dev/null || true)"
    [ -f "${F}" ] || F="$(find /vllm-workspace -path '*/vllm/utils/network_utils.py' 2>/dev/null | head -1)"
    [ -f "${F}" ] || { echo "network_utils.py not found" >&2; exit 1; }
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

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
