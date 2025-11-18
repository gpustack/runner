#!/usr/bin/env bash

set -eo pipefail

INPUT_BACKEND="${INPUT_BACKEND:-""}"
INPUT_BACKEND_VERSION="${INPUT_BACKEND_VERSION:-""}"
INPUT_BACKEND_VARIANT="${INPUT_BACKEND_VARIANT:-""}"
INPUT_SERVICE=${INPUT_SERVICE:-""}
INPUT_SERVICE_VERSION="${INPUT_SERVICE_VERSION:-""}"
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"

#
# Prune unused runner.
#

INPUT_DIR="${INPUT_WORKSPACE}/../gpustack_runner"

# Validate and default inputs.
if [[ -z "${INPUT_BACKEND}" && -z "${INPUT_SERVICE}" ]]; then
    echo "[ERROR] No backend or service specified. Please provide a backend or service to discard unrecommended runners."
    exit 1
fi

if [[ -z "${INPUT_BACKEND}" ]]; then
    INPUT_BACKEND_VERSION=""
fi
if [[ -z "${INPUT_BACKEND_VARIANT}" ]]; then
    INPUT_BACKEND_VARIANT=""
fi
if [[ -z "${INPUT_SERVICE}" ]]; then
    INPUT_SERVICE_VERSION=""
fi

INPUT_FILE="${INPUT_DIR}/runner.py.json"
if [[ ! -f "${INPUT_FILE}" ]]; then
    echo "[ERROR] No runner file found at ${INPUT_FILE}. Nothing to discard."
    exit 1
fi

# Discard runners based on the inputs.
# - If backend is specified, but not backend_version, mark runners with the backend with `"deprecated": true`.
# - If backend and backend_version are specified, mark runners with the backend and backend_version with `"deprecated": true`.
# - If service is specified, but not service_version, mark runners with the service with `"deprecated": true`.
# - If service and service_version are specified, mark runners with the service and service_version with `"deprecated": true`.
# - If both backend and service are specified, mark runners that match all criteria with `"deprecated": true`.
DISCARDED_RUNNERS="$(jq -cr \
    --arg backend "${INPUT_BACKEND}" \
    --arg backend_version "${INPUT_BACKEND_VERSION}" \
    --arg backend_variant "${INPUT_BACKEND_VARIANT}" \
    --arg service "${INPUT_SERVICE}" \
    --arg service_version "${INPUT_SERVICE_VERSION}" \
    'map(if
        ($backend != "" and $service != "" and (.backend == $backend and ($backend_variant == "" or .backend_variant == $backend_variant) and ($backend_version == "" or .backend_version == $backend_version)) and (.service == $service and ($service_version == "" or .service_version == $service_version))) or
        ($backend != "" and $service == "" and (.backend == $backend and ($backend_variant == "" or .backend_variant == $backend_variant) and ($backend_version == "" or .backend_version == $backend_version))) or
        ($backend == "" and $service != "" and (.service == $service and ($service_version == "" or .service_version == $service_version))) then
        . + { deprecated: true }
        else
        .
        end
    )' "${INPUT_FILE}")"

# Review the discarded runners.
echo "[INFO] Discarded Runners:"
jq -r '.' <<<"${DISCARDED_RUNNERS}" | tee "${INPUT_FILE}" || true

"${INPUT_WORKSPACE}"/merge_runner.sh
