#!/usr/bin/env bash

set -eo pipefail

INPUT_NAMESPACE="${INPUT_NAMESPACE:-"gpustack"}"
INPUT_REPOSITORY="${INPUT_REPOSITORY:-"runner"}"
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"
INPUT_DEPENDENCIES_DIR="${INPUT_DEPENDENCIES_DIR:-""}"
INPUT_POST_OPERATION="${INPUT_POST_OPERATION:-""}"
INPUT_CATALOG_REFRESH="${INPUT_CATALOG_REFRESH:-"false"}"

if [[ "${INPUT_CATALOG_REFRESH}" == "true" ]]; then
    # Prune and discard only refresh existing rows. Reject build inputs so this
    # mode cannot bypass validation of changed images.
    for INPUT_NAME in INPUT_CONTEXT INPUT_BUILD_JOBS INPUT_DEPENDENCIES_DIR \
        INPUT_DEPENDENCIES_FILE INPUT_MANIFESTS_FILE INPUT_POST_OPERATION INPUT_ALLOW_UNKNOWN; do
        if [[ -n "${!INPUT_NAME}" ]]; then
            echo "[ERROR] Catalog refresh cannot use ${INPUT_NAME}." >&2
            exit 1
        fi
    done
else
    : "${INPUT_CONTEXT:?Frozen Pack context is required}"
    : "${INPUT_DEPENDENCIES_DIR:?Package outputs and receipts are required}"
    : "${INPUT_MANIFESTS_FILE:?Published manifest identities are required}"
    INPUT_DEPENDENCIES_FILE="${INPUT_DEPENDENCIES_FILE:-"$(dirname "${BASH_SOURCE[0]}")/dependencies.json"}"
fi

#
# Merge new runners with existing runners.
#

OUTPUT_DIR="${INPUT_WORKSPACE}/../gpustack_runner"
mkdir -p "${OUTPUT_DIR}"

OUTPUT_FILE="${OUTPUT_DIR}/runner.py.json"

WORK_DIR="$(mktemp -d "${INPUT_TEMPDIR}/runner-merge.XXXXXX")"
CATALOG_CANDIDATE=""
FIXTURES_CANDIDATE=""
trap 'rm -rf "${WORK_DIR}"; rm -f "${CATALOG_CANDIDATE}" "${FIXTURES_CANDIDATE}"' EXIT
if [[ "${INPUT_CATALOG_REFRESH}" != "true" ]]; then
    # Validate the full frozen matrix, Package outputs, receipts and current registry
    # descriptors before rendering either output. Missing data never means reuse.
    printf '%s\n' "${INPUT_CONTEXT}" >"${WORK_DIR}/context.json"
    INPUT_BUILD_JOBS="$(jq -ce '.matrix.build_jobs' "${WORK_DIR}/context.json")"
    EXPECTED_REPOSITORY="$(jq -er '.matrix.repository' "${WORK_DIR}/context.json")"
    if [[ "${EXPECTED_REPOSITORY}" != "${INPUT_NAMESPACE}/${INPUT_REPOSITORY}" ]]; then
        echo "[ERROR] Catalog repository differs from the frozen Pack context." >&2
        exit 1
    fi
    COLLECTION_OPTIONS=()
    if [[ "${INPUT_ALLOW_UNKNOWN:-false}" == "true" ]]; then
        COLLECTION_OPTIONS+=(--allow-unknown)
    fi
    python3 "$(dirname "${BASH_SOURCE[0]}")/collect_dependencies.py" catalog \
        --context "${WORK_DIR}/context.json" \
        --mapping "${INPUT_DEPENDENCIES_FILE}" \
        --artifacts "${INPUT_DEPENDENCIES_DIR}" \
        --manifests "${INPUT_MANIFESTS_FILE}" \
        "${COLLECTION_OPTIONS[@]}" \
        --output "${WORK_DIR}/dependencies.json"
    PROBED_DEPENDENCIES="$(cat "${WORK_DIR}/dependencies.json")"

    # Review the probed dependencies.
    echo "[INFO] Probed Dependencies:"
    jq -r '.' <<<"${PROBED_DEPENDENCIES}"
fi

# Load existing runners if exists.
ORIGINAL_RUNNERS="[]"
if [[ -f "${OUTPUT_FILE}" ]]; then
    ORIGINAL_RUNNERS="$(jq -cr '.' "${OUTPUT_FILE}")"
fi

if [[ "${INPUT_CATALOG_REFRESH}" == "true" ]]; then
    MERGED_RUNNERS="${ORIGINAL_RUNNERS}"
elif [[ -n "${INPUT_POST_OPERATION}" ]]; then
    # Post operation mode: update in place, never add.
    #
    # An operation mutates an already released tag, so the only field it may
    # change is the `dependencies` of the entries already describing those tags.
    # Its matrix is pruned to just those tags -- building entries from it, the way
    # the normal path does, would invent entries for tags that were never released
    # and rewrite the other fields from a non-authoritative source. Nothing is
    # reconstructed here, so unrelated row fields stay unchanged.

    # Relate each probe result back to the entry it belongs to.
    PROBED_ENTRIES="$(echo "${INPUT_BUILD_JOBS}" | jq -cr \
        --arg namespace "${INPUT_NAMESPACE}" \
        --arg repository "${INPUT_REPOSITORY}" \
        --argjson dependencies "${PROBED_DEPENDENCIES}" \
        '[.[]
          | {
              platform_tag: .platform_tag,
              platform: .platform,
              docker_image: ($namespace + "/" + $repository + ":" + .tag),
              dependencies: $dependencies[.platform_tag],
            }]')"

    # Every changed image must address exactly one existing entry, including
    # explicit unknown results. Unknown removes stale metadata for that image.
    UNLOCATABLE="$(jq -cn \
        --argjson probed "${PROBED_ENTRIES}" \
        --argjson original "${ORIGINAL_RUNNERS}" \
        '[$probed[]
          | . as $p
          | . + {matched: ([$original[]
                            | select(.platform == $p.platform and .docker_image == $p.docker_image)] | length)}
          | select(.matched != 1)]')"
    if [[ "$(echo "${UNLOCATABLE}" | jq -r 'length')" -ne 0 ]]; then
        echo "[ERROR] Post operation '${INPUT_POST_OPERATION}': $(echo "${UNLOCATABLE}" | jq -r 'length') probed image(s) do not address exactly one existing entry of '${OUTPUT_FILE}'." >&2
        echo "${UNLOCATABLE}" | jq -r '.[] | "[ERROR]   platform_tag=\"\(.platform_tag)\" platform=\"\(.platform)\" docker_image=\"\(.docker_image)\" matched=\(.matched)"' >&2
        echo "[ERROR] A post operation may only address already released tags. Check the tags of the operation's matrix.yaml, and make sure the workflow ran with for_release=true: otherwise the tags carry the '-dev' suffix and can never address a released entry." >&2
        exit 1
    fi

    # Update the addressed entries, and only their `dependencies`.
    MERGED_RUNNERS="$(jq -cn \
        --argjson probed "${PROBED_ENTRIES}" \
        --argjson original "${ORIGINAL_RUNNERS}" \
        '($probed | INDEX([.platform, .docker_image] | tostring)) as $index
         | $original
         | map(($index[[.platform, .docker_image] | tostring]) as $p
               | if $p == null then .
                 elif $p.dependencies == null then del(.dependencies)
                 else . + {dependencies: $p.dependencies} end)')"

    echo "[INFO] Updated Runners: $(echo "${PROBED_ENTRIES}" | jq -r 'length') of $(echo "${ORIGINAL_RUNNERS}" | jq -r 'length')"
else
    # Construct new runners from the input build jobs.
    NEW_RUNNERS="$(echo "${INPUT_BUILD_JOBS}" | jq -cr \
        --arg namespace "${INPUT_NAMESPACE}" \
        --arg repository "${INPUT_REPOSITORY}" \
        --argjson dependencies "${PROBED_DEPENDENCIES}" \
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
        } + (if $dependencies[.platform_tag] then {dependencies: $dependencies[.platform_tag]} else {} end)' | jq -cs .)"

    # Replace selected identities; preserve every untouched historical row.
    MERGED_RUNNERS="$(jq -cn \
        --argjson new "${NEW_RUNNERS}" \
        --argjson original "${ORIGINAL_RUNNERS}" \
        '($new | INDEX([.platform, .docker_image] | tostring)) as $index
         | $new + [$original[] | select($index[[.platform, .docker_image] | tostring] == null)]')"
fi

if [[ -z "${INPUT_POST_OPERATION}" ]]; then
    # Normalize the merged runners by sorting them.
    MERGED_RUNNERS="$(echo "${MERGED_RUNNERS}" | jq -cr 'sort_by([.backend, (.backend_variant | explode | map(-.)), (.backend_version | explode | map(-.)), .service, (.service_version | split(".") | map(tonumber?) | map(-.))])')"
fi

# Review the merged runners.
echo "[INFO] Merged Runners:"
jq -r '.' <<<"${MERGED_RUNNERS}"

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
jq -r '.' <<<"${OUTPUT_FIXTURES}"

# Render both complete files before either replacement. Each rename is atomic
# because its candidate lives in the destination directory.
CATALOG_CANDIDATE="$(mktemp "${OUTPUT_DIR}/.runner.XXXXXX")"
FIXTURES_CANDIDATE="$(mktemp "${OUTPUT_FIXTURES_DIR}/.runners.XXXXXX")"
jq '.' <<<"${MERGED_RUNNERS}" >"${CATALOG_CANDIDATE}"
jq '.' <<<"${OUTPUT_FIXTURES}" >"${FIXTURES_CANDIDATE}"
chmod 644 "${CATALOG_CANDIDATE}" "${FIXTURES_CANDIDATE}"
mv -f "${FIXTURES_CANDIDATE}" "${OUTPUT_FIXTURES_FILE}"
mv -f "${CATALOG_CANDIDATE}" "${OUTPUT_FILE}"
