#!/bin/bash

set -eo pipefail

# Utils

usage() {
    echo ""
    echo "# Usage"
    echo "  $(basename "$0") <image/image-tag> <volume> [args...]"
    echo "    - image/image-tag: Docker image or image tag to run (default: 'gpustack/runner:cuda12.8-vllm0.10.0')"
    echo "    - volume:          Host directory to mount into the container"
    echo "    - args:            Additional arguments to pass to the Docker container"
    echo "  * This script is intended to run on Linux with Docker installed."
    echo "# Example"
    echo "  $0 gpustack/runner:cuda12.8-vllm0.10.0 /path/to/data --arg1 value1 --arg2 value2"
    echo "# Images"
    docker images --format "{{.Repository}}:{{.Tag}}" | grep -v '<none>' | grep '^gpustack/runner:' | sort -u | sed 's/^/    - /'
    echo ""
}

info() {
    echo "[INFO]  $*"
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
if [[ -f "${VOLUME}" ]]; then
    fatal "Volume path '${VOLUME}' is a file, expected a directory."
elif [[ ! -d "${VOLUME}" ]]; then
    warn "Volume path '${VOLUME}' does not exist, creating."
    if ! mkdir -p "${VOLUME}" >/dev/null 2>&1; then
        fatal "Failed to create volume directory '${VOLUME}'."
    fi
fi

RUNTIMES=($(docker info --format json | jq -rc '.Runtimes | keys | map (select(. == "nvidia" or . == "amd")) | .[]'))
if [[ "${#RUNTIMES[@]}" -eq 0 ]]; then
    fatal "NVIDIA or AMD runtimes not available. Please ensure you have the appropriate runtime installed."
fi
RUNTIME="${RUNTIMES[0]}"

ENV_FILE="$(mktemp)"
echo "$(tr '[:lower:]' '[:upper:]' <<< "${RUNTIME}")_VISIBLE_DEVICES=all" >"${ENV_FILE}"
env | grep -v -E '^(PATH|HOME|LANG|PWD|SHELL|LOG|XDG|SSH|LC|LS|_|USER|TERM|LESS|SHLVL|DBUS|OLDPWD|MOTD|LD|LIB)' >>"${ENV_FILE}" || true

info "Running Docker container:"
info "  - platform: '${OS}/${ARCH}'"
info "  - runtime:  '${RUNTIME}'"
info "  - volume:   '${VOLUME}'"
info "  - image :   '${IMAGE}'"
info "  - envs  :   '$(cat "${ENV_FILE}" | tr '\n' ', ' | sed 's/, $//')'"
info "  - args  :   '${ARGS[*]}'"

# Prepare

cleanup() {
    rm -f "${ENV_FILE}"
}
trap cleanup EXIT

# Start

set -x

docker run --rm -it \
    --privileged \
    --network host \
    --ipc host \
    --shm-size 2g \
    --runtime "${RUNTIME}" \
    --volume "${VOLUME}:${VOLUME}" \
    --platform "${OS}/${ARCH}" \
    --env-file "${ENV_FILE}" \
    --workdir "/" \
    "${IMAGE}" \
    "${ARGS[@]}"
