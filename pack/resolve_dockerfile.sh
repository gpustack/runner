#!/usr/bin/env bash

set -eo pipefail

# Usage: resolve_dockerfile.sh <pack directory> <backend> <service> [post operation]
WORKSPACE="${1:?Pack directory is required}"
BACKEND="${2:?Backend is required}"
SERVICE="${3:?Service is required}"
POST_OPERATION="${4:-}"

if [[ -n "${POST_OPERATION}" ]]; then
    WORKSPACE="${WORKSPACE}/.post_operation/${POST_OPERATION}"
fi

DOCKERFILE="${WORKSPACE}/${BACKEND}/Dockerfile.${SERVICE}"
if [[ -f "${DOCKERFILE}" ]]; then
    printf '%s\n' "${DOCKERFILE}"
elif [[ -f "${WORKSPACE}/${BACKEND}/Dockerfile" ]]; then
    # Keep active combined recipes until all service files have been migrated.
    # Explicit historical operations also retain their combined filenames.
    printf '%s\n' "${WORKSPACE}/${BACKEND}/Dockerfile"
else
    echo "[ERROR]: Dockerfile not found for backend '${BACKEND}', service '${SERVICE}': ${DOCKERFILE} or ${WORKSPACE}/${BACKEND}/Dockerfile" >&2
    exit 1
fi
