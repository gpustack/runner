#!/usr/bin/env bash

set -eo pipefail

INPUT_NAMESPACE="${INPUT_NAMESPACE:-"gpustack"}"
INPUT_REPOSITORY="${INPUT_REPOSITORY:-"runner"}"
INPUT_BUILD_JOBS="${INPUT_BUILD_JOBS:-"[]"}"
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"

OUTPUT_FILE="${INPUT_WORKSPACE}/../runner/runner.json"

# Construct new runners from the input build jobs.
NEW_RUNNERS="$(echo "${INPUT_BUILD_JOBS}" | jq -cr \
    --arg namespace "${INPUT_NAMESPACE}" \
    --arg repository "${INPUT_REPOSITORY}" \
    '.[] | {
        backend: .backend,
        backend_version: .backend_version,
        backend_variant: .backend_variant,
        service: .service,
        service_version: .service_version,
        platform: .platform,
        docker_image: ($namespace + "/" + $repository + ":" + .tag),
    }' | jq -cs .)"

# Load existing runners if exists.
ORIGINAL_RUNNERS="[]"
if [ -f "${OUTPUT_FILE}" ]; then
    ORIGINAL_RUNNERS="$(jq -cr '.' "${OUTPUT_FILE}")"
fi

# Merge new runners with original runners, and distinct by docker_image.
MERGED_RUNNERS="$(echo "${ORIGINAL_RUNNERS}" "${NEW_RUNNERS}" | jq -cs 'add | unique_by(.docker_image)')"

# Review the merged runners.
echo "[INFO] Merged Runners:"
echo "${MERGED_RUNNERS}" | jq -r '.'

# Write the merged runners to the output file.
mkdir -p "$(dirname "${OUTPUT_FILE}")"
echo "${MERGED_RUNNERS}" | jq -r '.' > "${OUTPUT_FILE}" || true
