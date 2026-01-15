#!/usr/bin/env bash

set -eo pipefail

INPUT_SRC_IMAGE="${INPUT_SRC_IMAGE:-""}"
INPUT_DST_IMAGE="${INPUT_DST_IMAGE:-""}"
INPUT_PLATFORM="${INPUT_PLATFORM:-"linux/amd64"}"

if [[ -z "${INPUT_SRC_IMAGE}" || -z "${INPUT_DST_IMAGE}" ]]; then
    echo "[ERROR] Missing required inputs: INPUT_SRC_IMAGE or INPUT_DST_IMAGE."
    exit 1
fi

echo "[INFO] Squashing image: ${INPUT_SRC_IMAGE} -> ${INPUT_DST_IMAGE} for platform: ${INPUT_PLATFORM}"

# Pull the source image for the specified platform.
echo "[INFO] Pulling source image: ${INPUT_SRC_IMAGE}"
docker pull --platform "${INPUT_PLATFORM}" "${INPUT_SRC_IMAGE}"
docker images "${INPUT_SRC_IMAGE}" && docker image inspect "${INPUT_SRC_IMAGE}"

# Extract the original config from the source image.
CONFIG="$(docker image inspect "${INPUT_SRC_IMAGE}" --format='{{json .Config}}')"

# Create a temporary directory for building the squashed image.
BUILD_DIR=$(mktemp -d)

# Prepare a Dockerfile to create a squashed image.
DOCKERFILE="${BUILD_DIR}/Dockerfile"
cat <<EOF > "${DOCKERFILE}"
FROM scratch
COPY --from=${INPUT_SRC_IMAGE} / /
EOF

# Append original config to the Dockerfile.
LABELS="$(echo "${CONFIG}" | jq -cr '.Labels')"
if [[ -n "${LABELS}" && "${LABELS}" != "null" && "${LABELS}" != "{}" ]]; then
    # Remove useless labels that may cause issues.
    LABELS="$(echo "${LABELS}" | jq 'del(.maintainer) | del(."org.opencontainers.image.created") | del(."org.opencontainers.image.url") | del(."org.opencontainers.image.source")')"
    # Add labels to Dockerfile.
    echo "LABEL $(echo "${LABELS}" | jq -r 'to_entries | map("\(.key)=\"\(.value)\"") | join(" ")')" >> "${DOCKERFILE}"
fi

# Append original environment variables to the Dockerfile.
ENV_VARS="$(echo "${CONFIG}" | jq -cr '.Env')"
if [[ -n "${ENV_VARS}" && "${ENV_VARS}" != "null" && "${ENV_VARS}" != "[]" ]]; then
    while IFS= read -r ENV_VAR; do
        # Quote the ENV value to handle spaces.
        KEY="${ENV_VAR%%=*}"
        VALUE="${ENV_VAR#*=}"
        ENV_VAR="${KEY}=\"${VALUE}\""
        echo "ENV ${ENV_VAR}" >> "${DOCKERFILE}"
    done < <(echo "${ENV_VARS}" | jq -r '.[]')
fi

# Append user information to the Dockerfile.
USER_INFO="$(echo "${CONFIG}" | jq -cr '.User')"
if [[ -n "${USER_INFO}" && "${USER_INFO}" != "null" ]]; then
    echo "USER ${USER_INFO}" >> "${DOCKERFILE}"
fi

# Append working directory to the Dockerfile.
WORKDIR="$(echo "${CONFIG}" | jq -cr '.WorkingDir')"
if [[ -n "${WORKDIR}" && "${WORKDIR}" != "null" ]]; then
    echo "WORKDIR ${WORKDIR}" >> "${DOCKERFILE}"
fi

# Append volumes to the Dockerfile.
VOLUMES="$(echo "${CONFIG}" | jq -cr '.Volumes')"
if [[ -n "${VOLUMES}" &&  "${VOLUMES}" != "null" && "${VOLUMES}" != "{}" ]]; then
    while IFS= read -r VOLUME; do
        echo "VOLUME ${VOLUME}" >> "${DOCKERFILE}"
    done < <(echo "${VOLUMES}" | jq -r 'keys[]')
fi

# Append original entrypoint and command to the Dockerfile.
ENTRYPOINT="$(echo "${CONFIG}" | jq -cr '.Entrypoint')"
if [[ -n "${ENTRYPOINT}" && "${ENTRYPOINT}" != "null" && "${ENTRYPOINT}" != "[]" ]]; then
    echo "ENTRYPOINT ${ENTRYPOINT}" >> "${DOCKERFILE}"
    CMD="$(echo "${CONFIG}" | jq -cr '.Cmd')"
    if [[ "${CMD}" != "null" && "${CMD}" != "[]" ]]; then
        echo "CMD ${CMD}" >> "${DOCKERFILE}"
    fi
fi

# Echo the generated Dockerfile for review.
echo "[INFO] Generated Dockerfile for squashed image:"
cat "${DOCKERFILE}"

## Build the squashed image.
echo "[INFO] Building squashed image: ${INPUT_DST_IMAGE}"
set -x
docker build \
    --platform "${INPUT_PLATFORM}" \
    --tag "${INPUT_DST_IMAGE}" \
    --file "${DOCKERFILE}" \
    --push \
    --attest "type=provenance,disabled=true" \
    --attest "type=sbom,disabled=true" \
    --ulimit nofile=65536:65536 \
    --shm-size 16G \
    --progress plain \
    "${BUILD_DIR}"
docker images "${INPUT_DST_IMAGE}" && docker image inspect "${INPUT_DST_IMAGE}"
