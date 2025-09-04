#!/bin/bash

# Alias: run_runner_cluster

set -eo pipefail

# Utils

usage() {
    name=$(basename "$0")
    echo ""
    echo "# Usage"
    echo "  [envs...] ${name} <hosts> <image/image-tag> <volume> [args...]"
    echo "    - envs            : Environment variables to pass into the container (e.g. VLLM_LOGGING_LEVEL=DEBUG)"
    echo "    - hosts           : Passwordless SSH hosts (comma-separated) to run the container on, the first host is the master, others are workers"
    echo "    - image/image-tag : Docker image or image tag to run (default: 'gpustack/runner:cuda12.4-vllm0.10.0')"
    echo "    - volume          : Host directory to mount into the container"
    echo "    - args            : Additional arguments to pass to the Docker container"
    echo "  * This script is intended to run on Linux with Docker installed."
    echo "# Example"
    echo "    - VLLM_LOGGING_LEVEL=DEBUG ${name} 192.168.50.12,192.168.50.13,... cuda12.4-vllm0.10.0 /path/to/data vllm serve --port 8080 --model /path/to/model ..."
    echo -e "    - \033[33mDRUN=true\033[0m VLLM_LOGGING_LEVEL=DEBUG ${name} 192.168.50.12,192.168.50.13,... cuda12.4-vllm0.10.0 /path/to/data vllm serve --port 8080 --model /path/to/model ..."
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

scp_to() {
    local file="$1"
    shift
    local hosts=("$@")
    for host in "${hosts[@]}"; do
        info "Copying '${file}' to '${host}'"
        scp -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${file}" "${USER}@${host}:${file}" 2>/dev/null
    done
}

ssh_exec() {
    local host="$1"
    shift
    local cmd="$*"
    info "Executing on '${host}': ${cmd}"
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${USER}@${host}" "${cmd}"
}

wait_jobs() {
    local fail=0
    local job
    for job in $(jobs -p); do
        wait "${job}" || fail=$((fail + 1))
    done
    return ${fail}
}

# Parse/Validate/Default

if [[ $# -lt 0 || "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
elif [[ $# -lt 3 ]]; then
    fatal "Insufficient arguments provided."
fi

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="${ARCH:-$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')}"
if [[ "${OS}" != "linux" ]]; then
    fatal "This script is only supported on Linux."
fi

# shellcheck disable=SC2207
HOSTS=($(echo "$1" | tr ',' ' '))
IMAGE="${2}"
VOLUME="${3}"
shift 3
ARGS=("$@")

if [[ ${#HOSTS[@]} -lt 2 ]]; then
    fatal "No enough hosts provided."
else
    if ! hostname -I | grep -wq "${HOSTS[0]}"; then
        fatal "The first host '${HOSTS[0]}' is not the current host."
    fi
fi
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
    env | grep -v -E '^(PATH|HOME|LANG|PWD|SHELL|LOG|XDG|SSH|LC|LS|_|USER|TERM|LESS|SHLVL|DBUS|OLDPWD|MOTD|LD|LIB|_OLD|DRUN)' >"${ENV_FILE}" || true
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
    SOCKET_IFNAME="$(ip addr show | awk -v ip="${HOSTS[0]}" '$1 == "inet" && index($2, ip) == 1 {print $NF}')"
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
    info "To entry the container, use 'docker exec -it ${CONTAINER_NAME} /bin/bash' on each host"
    info "To view the container logs, use 'docker logs -f ${CONTAINER_NAME}' on each host"
else
    RUN_ARGS+=(
        "--rm"
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

info "Running Docker container cluster:"
info "  - master :  '${HOSTS[0]}'"
info "  - workers:  '${HOSTS[*]:1}'"
info "  - platform: '${OS}/${ARCH}'"
info "  - runtime:  '${RUNTIME}'"
info "  - volume:   '${VOLUME}'"
info "  - image :   '${IMAGE}'"
info "  - envs  :   '$(tr <"${ENV_FILE}" '\n' ' ' | sed 's/ $//g')'"
info "  - args  :   '${ARGS[*]}'"

# Prepare

postprocess() {
    set +x
    for job in $(jobs -p); do
        kill -9 "$job" >/dev/null 2>&1 || true
    done
    rm -f "${ENV_FILE}"
    if [[ "${DRUN}" == "true" ]]; then
        echo ""
        info "To stop the container, use 'docker stop ${CONTAINER_NAME}' on each host"
        info "To remove the container, use 'docker rm -f ${CONTAINER_NAME}' on each host"
    else
        for host in "${HOSTS[@]:1}"; do
            ssh_exec "${host}" "docker rm -f ${CONTAINER_NAME} >/dev/null 2>&1" 2>/dev/null || true
        done
    fi
}
trap postprocess EXIT

# Start

if [[ "${SERVICE}" == "vllm" ]]; then
    for host in "${HOSTS[@]:1}"; do
        SOCKET_IFNAME="$(ssh_exec "${host}" "ip addr show | awk -v ip=\"${host}\" '\$1 == \"inet\" && index(\$2, ip) == 1 {print \$NF}'" 2>/dev/null)"
        EXTEND_RUN_ARGS=(
            "--env" "NCCL_SOCKET_IFNAME=${SOCKET_IFNAME}"
            "--env" "GLOO_SOCKET_IFNAME=${SOCKET_IFNAME}"
        )
        ssh_exec "${host}" "docker run ${RUN_ARGS[*]} ${EXTEND_RUN_ARGS[*]} ${IMAGE} ray start --block --address=${HOSTS[0]}:6379 --disable-usage-stats --verbose >/dev/null 2>&1" &
    done
    set -x
    docker run "${RUN_ARGS[@]}" "${IMAGE}" bash -c "ray start --head --disable-usage-stats >/dev/null && ${ARGS[*]}"
    set +x
else
    for host in "${HOSTS[@]:1}"; do
        ssh_exec "${host}" "docker run ${RUN_ARGS[*]} ${IMAGE} ${ARGS[*]}" &
    done
    set -x
    docker run "${RUN_ARGS[@]}" "${IMAGE}" "${ARGS[@]}"
    set +x
fi

if [[ "${DRUN}" == "true" ]]; then
    (
        docker logs -f "${CONTAINER_NAME}" || true
    ) &
fi

wait_jobs
