#!/usr/bin/env bash

set -eo pipefail

INPUT_NAMESPACE="${INPUT_NAMESPACE:-"gpustack"}"
INPUT_REPOSITORY="${INPUT_REPOSITORY:-"runner"}"
INPUT_BUILD_JOBS="${INPUT_BUILD_JOBS:-"[]"}"
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"

#
# Merge new runners with existing runners.
#

OUTPUT_DIR="${INPUT_WORKSPACE}/../gpustack_runner"
mkdir -p "${OUTPUT_DIR}"

OUTPUT_FILE="${OUTPUT_DIR}/runner.py.json"

# Construct new runners from the input build jobs.
NEW_RUNNERS="$(echo "${INPUT_BUILD_JOBS}" | jq -cr \
    --arg namespace "${INPUT_NAMESPACE}" \
    --arg repository "${INPUT_REPOSITORY}" \
    '.[] | {
        backend: .backend,
        backend_version: .backend_version,
        original_backend_version: .original_backend_version,
        backend_variant: .backend_variant,
        service: .service,
        service_version: .service_version,
        platform: .platform,
        docker_image: ($namespace + "/" + $repository + ":" + .tag),
        deprecated: (.deprecated // false),
    }' | jq -cs .)"

# Load existing runners if exists.
ORIGINAL_RUNNERS="[]"
if [[ -f "${OUTPUT_FILE}" ]]; then
    ORIGINAL_RUNNERS="$(jq -cr '.' "${OUTPUT_FILE}")"
fi

# Merge new runners with original runners, and distinct by docker_image.
MERGED_RUNNERS="$(echo "${NEW_RUNNERS}" "${ORIGINAL_RUNNERS}" | jq -cs 'add | unique_by(.platform + .docker_image)')"

# Normalize the merged runners by sorting them.
MERGED_RUNNERS="$(echo "${MERGED_RUNNERS}" | jq -cr 'sort_by([.backend, (.backend_variant | explode | map(-.)), (.backend_version | explode | map(-.)), .service, (.service_version | split(".") | map(tonumber?) | map(-.))])')"

# Review the merged runners.
echo "[INFO] Merged Runners:"
jq -r '.' <<<"${MERGED_RUNNERS}" | tee "${OUTPUT_FILE}" || true

#
# Create fixtures for the merged runners.
#

OUTPUT_FIXTURES_DIR="${INPUT_WORKSPACE}/../tests/gpustack_runner/fixtures"
mkdir -p "${OUTPUT_FIXTURES_DIR}"

RULES="$(yq '.[]' \
    --output-format json \
    --indent 0 \
    "${INPUT_WORKSPACE}/matrix.yaml")"
BACKENDS="$(echo "${RULES}" | jq -r '.[] | .backend' | sort -u | jq -R . | jq -cs .)"

OUTPUT_FIXTURES_FILE="${OUTPUT_FIXTURES_DIR}/test_list_runners_by_backend.json"
OUTPUT_FIXTURES="[]"

for backend in $(echo "${BACKENDS}" | jq -r '.[]'); do
    KWARGS="{\"backend\": \"${backend}\"}"
    EXPECTED="$(echo "${MERGED_RUNNERS}" | jq -cr \
        --arg backend "${backend}" \
        '[.[] | select(.backend == $backend)]')"
    OUTPUT_FIXTURES="$(echo "${OUTPUT_FIXTURES}" "[[\"${backend}\",${KWARGS},${EXPECTED}]]" | jq -cs 'add')"
done

# Review the fixtures.
echo "[INFO] Merged Fixtures:"
jq -r '.' <<<"${OUTPUT_FIXTURES}" | tee "${OUTPUT_FIXTURES_FILE}" || true
