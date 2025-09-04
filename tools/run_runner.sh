#!/bin/bash

# Alias: run_runner

set -eo pipefail

# Utils

usage() {
    name=$(basename "$0")
    echo ""
    echo "# Usage"
    echo "  [envs...] ${name} <image/image-tag> <volume> [args...]"
    echo "    - envs            : Environment variables to pass into the container (e.g. VLLM_LOGGING_LEVEL=DEBUG)"
    echo "    - image/image-tag : Docker image or image tag to run (default: 'gpustack/runner:cuda12.4-vllm0.10.0')"
    echo "    - volume          : Host directory to mount into the container"
    echo "    - args            : Additional arguments to pass to the Docker container"
    echo "  * This script is intended to run on Linux with Docker installed."
    echo "# Example"
    echo "    - VLLM_LOGGING_LEVEL=DEBUG ${name} cuda12.4-vllm0.10.0 /path/to/data vllm serve --port 8080 --model /path/to/model ..."
    echo -e "    - \033[33mDRUN=true\033[0m VLLM_LOGGING_LEVEL=DEBUG ${name} cuda12.4-vllm0.10.0 /path/to/data vllm serve --port 8080 --model /path/to/model ..."
    echo "# Images"
    docker images --format "{{.Repository}}:{{.Tag}}" | grep -v '<none>' | grep '^gpustack/runner:' | sort -u | sed 's/^/    - /'
    echo ""
}

info() {
    echo "[INFO]  $*" >&2
}

error() {
    echo "[ERROR] $*" >&2
}

warn() {
    echo "[WARN]  $*" >&2
}

fatal() {
    echo "[FATAL] $*" >&2
    usage
    exit 1
}

# Parse/Validate/Default

if [[ $# -eq 0 || "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
elif [[ $# -lt 2 ]]; then
    fatal "Insufficient arguments provided."
fi

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="${ARCH:-$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')}"
if [[ "${OS}" != "linux" ]]; then
    fatal "This script is only supported on Linux."
fi

IMAGE="${1}"
VOLUME="${2}"
shift 2
ARGS=("$@")

if [[ -z "${IMAGE}" ]]; then
    warn "Image name is blank, using 'gpustack/runner:cuda12.8-vllm0.10.0' as default."
    IMAGE="gpustack/runner:cuda12.8-vllm0.10.0"
elif [[ ! "${IMAGE}" =~ ^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+.*$ ]]; then
    warn "Image name '${IMAGE}' does not look like a valid Docker image, using 'gpustack/runner:${IMAGE}' as default."
    IMAGE="gpustack/runner:${IMAGE}"
fi

DRUN="${DRUN:-"false"}"
SERVICE="${SERVICE:-}"
RUNTIME="${RUNTIME:-}"

if [[ -z "${SERVICE}" ]]; then
    if grep -q "vllm" <<<"${IMAGE}" || grep -q "vllm" <<<"${ARGS[*]}"; then
        SERVICE="vllm"
    elif grep -q "sglang" <<<"${IMAGE}" || grep -q "sglang" <<<"${ARGS[*]}"; then
        SERVICE="sglang"
    elif grep -q "mindie" <<<"${IMAGE}" || grep -q "mindie" <<<"${ARGS[*]}"; then
        SERVICE="mindie"
    else
        SERVICE="other"
    fi
fi
if [[ -z "${RUNTIME}" ]]; then
    # shellcheck disable=SC2207
    RUNTIMES=($(docker info --format json | jq -rc '.Runtimes | keys | map (select(. == "nvidia" or . == "amd" or . == "ascend")) | .[]'))
    if [[ "${#RUNTIMES[@]}" -eq 0 ]]; then
        fatal "GPU runtimes(e.g. nvidia) not available. Please ensure you have the appropriate runtime installed."
    fi
    RUNTIME="${RUNTIMES[0]}"
fi

CONTAINER_NAME="gpustack-runner-${RUNTIME}-$(date +%s)"
CACHE_NAME="gpustack-runner-${RUNTIME}-${OS}-${ARCH}-$(md5sum <<<"${IMAGE}" | cut -c1-10)"

if [[ -n "${_OLD_ENV_FILE_HASH:-}" ]] && [[ -n "${_OLD_ENV_FILE:-}" ]] && [[ -f "${_OLD_ENV_FILE}" ]]; then
    _ENV_FILE_HASH="$(sha256sum "${_OLD_ENV_FILE}" | awk '{print $1}')"
    if [[ "${_ENV_FILE_HASH}" != "${_OLD_ENV_FILE_HASH}" ]] ; then
        _ENV_FILE_HASH=""
    fi
fi
ENV_FILE="$(mktemp)"
if [[ -z "${_ENV_FILE_HASH}" ]]; then
    env | grep -v -E '^(PATH|HOME|LANG|PWD|SHELL|LOG|XDG|SSH|LC|LS|_|USER|TERM|LESS|SHLVL|DBUS|OLDPWD|MOTD|LD|LIB|DRUN)' >"${ENV_FILE}" || true
else
    diff <(sort < "${_OLD_ENV_FILE}") <(env | grep -v -E '^(_OLD|DRUN)' | sort) | grep '^>' | sed 's/^> //' >"${ENV_FILE}" || true
fi
if ! grep -q "$(tr '[:lower:]' '[:upper:]' <<<"${RUNTIME}")_VISIBLE_DEVICES=" "${ENV_FILE}"; then
    echo "$(tr '[:lower:]' '[:upper:]' <<<"${RUNTIME}")_VISIBLE_DEVICES=all" >>"${ENV_FILE}"
fi
if [[ "${RUNTIME}" == "nvidia" ]]; then
    if ! grep -q "NVIDIA_DISABLE_REQUIRE=" "${ENV_FILE}"; then
        echo "NVIDIA_DISABLE_REQUIRE=true" >>"${ENV_FILE}"
    fi
fi
if ! grep -q "_SOCKET_IFNAME=" "${ENV_FILE}"; then
    SOCKET_IFNAME="$(ip route | awk '/default/ {print $5}' | head -1)"
    echo "NCCL_SOCKET_IFNAME=${SOCKET_IFNAME}" >>"${ENV_FILE}"
    echo "GLOO_SOCKET_IFNAME=${SOCKET_IFNAME}" >>"${ENV_FILE}"
fi

RUN_ARGS=()
if [[ "${DRUN}" == "true" ]]; then
    RUN_ARGS+=(
        "--detach"
        "--restart" "on-failure:3"
    )
    info "Running in detached mode"
    info "To entry the container, use 'docker exec -it ${CONTAINER_NAME} /bin/bash'"
    info "To view the container logs, use 'docker logs -f ${CONTAINER_NAME}'"
else
    RUN_ARGS+=(
        "--rm"
        "--interactive"
        "--tty"
    )
fi
if ! grep -q "NCCL_IB_" "${ENV_FILE}"; then
    RUN_ARGS+=(
        "--cap-add" "CAP_IPC_LOCK"
        "--cap-add" "CAP_SYS_ADMIN"
        "--cap-add" "CAP_SYS_PTRACE"
    )
else
    RUN_ARGS+=(
        "--privileged"
    )
fi
if [[ -f "${ENV_FILE}" ]]; then
    while IFS= read -r line; do
        RUN_ARGS+=("--env" "${line}")
    done <"${ENV_FILE}"
fi
RUN_ARGS+=(
    "--runtime" "${RUNTIME}"
    "--name" "${CONTAINER_NAME}"
    "--network" "host"
    "--shm-size" "16g"
    "--volume" "/dev/shm:/dev/shm"
    "--volume" "${CACHE_NAME}:/root/.cache"
    "--volume" "${VOLUME}:${VOLUME}"
    "--platform" "${OS}/${ARCH}"
    "--workdir" "/"
)

info "Running Docker container:"
info "  - platform: '${OS}/${ARCH}'"
info "  - runtime:  '${RUNTIME}'"
info "  - volume:   '${VOLUME}'"
info "  - image :   '${IMAGE}'"
info "  - envs  :   '$(tr <"${ENV_FILE}" '\n' ' ' | sed 's/ $//g')'"
info "  - args  :   '${ARGS[*]}'"

# Prepare

postprocess() {
    set +x
    rm -f "${ENV_FILE}"
    if [[ "${DRUN}" == "true" ]]; then
        echo ""
        info "To stop the container, use 'docker stop ${CONTAINER_NAME}'"
        info "To remove the container, use 'docker rm -f ${CONTAINER_NAME}'"
    fi
}
trap postprocess EXIT

# Start

set -x
docker run "${RUN_ARGS[@]}" "${IMAGE}" "${ARGS[@]}"
set +x

# shellcheck disable=SC2181
if [[ "${DRUN}" == "true" ]]; then
    docker logs -f "${CONTAINER_NAME}" || true
fi
