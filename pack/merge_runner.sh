#!/usr/bin/env bash

set -eo pipefail

INPUT_NAMESPACE="${INPUT_NAMESPACE:-"gpustack"}"
INPUT_REPOSITORY="${INPUT_REPOSITORY:-"runner"}"
INPUT_BUILD_JOBS="${INPUT_BUILD_JOBS:-"[]"}"
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"
INPUT_DEPENDENCIES_DIR="${INPUT_DEPENDENCIES_DIR:-""}"
INPUT_DEPENDENCIES_FILE="${INPUT_DEPENDENCIES_FILE:-"$(dirname "${BASH_SOURCE[0]}")/dependencies.json"}"
INPUT_POST_OPERATION="${INPUT_POST_OPERATION:-""}"

#
# Merge new runners with existing runners.
#

OUTPUT_DIR="${INPUT_WORKSPACE}/../gpustack_runner"
mkdir -p "${OUTPUT_DIR}"

OUTPUT_FILE="${OUTPUT_DIR}/runner.py.json"

# Index the probe results, keyed by platform tag: each build job uploads its
# versions as an artifact named "dependencies-<platform_tag>", and a platform tag
# is unique per (platform, tag) within a run, so it addresses exactly one record.
PROBED_DEPENDENCIES="{}"
if [[ -n "${INPUT_DEPENDENCIES_DIR}" ]]; then
    for DEPENDENCIES_FILE in "${INPUT_DEPENDENCIES_DIR}"/dependencies-*/dependencies.json; do
        [[ -f "${DEPENDENCIES_FILE}" ]] || continue
        PLATFORM_TAG="$(basename "$(dirname "${DEPENDENCIES_FILE}")")"
        PROBED_DEPENDENCIES="$(echo "${PROBED_DEPENDENCIES}" | jq -cr \
            --arg platform_tag "${PLATFORM_TAG#dependencies-}" \
            --slurpfile probed "${DEPENDENCIES_FILE}" \
            '.[$platform_tag] = $probed[0]')"
    done
fi

# Fold the probe results onto the dependency names of `pack/dependencies.json`.
#
# A probe reports raw distribution names, and one dependency may ship under
# several of them (``lmcache-ascend`` on CANN, ``lmcache`` elsewhere). The first
# name of the list that is installed wins, so `runner.py.json` records one
# version per dependency and the query side needs no second lookup. A dependency
# no image installed is simply absent, like any other uninstalled package.
# `-S` keeps the folded map sorted whatever order the names file is in, so the
# `runner.py.json` diff stays readable.
PROBED_DEPENDENCIES="$(echo "${PROBED_DEPENDENCIES}" | jq -cSr \
    --slurpfile dependencies "${INPUT_DEPENDENCIES_FILE}" \
    '$dependencies[0] as $names
     | map_values(
         . as $probed
         | reduce ($names | to_entries[]) as $entry ({};
             ($entry.value | map(select($probed[.] != null)) | first) as $hit
             | if $hit == null then . else . + {($entry.key): $probed[$hit]} end
           )
       )')"

# Review the probed dependencies.
echo "[INFO] Probed Dependencies:"
jq -r '.' <<<"${PROBED_DEPENDENCIES}"

# Load existing runners if exists.
ORIGINAL_RUNNERS="[]"
if [[ -f "${OUTPUT_FILE}" ]]; then
    ORIGINAL_RUNNERS="$(jq -cr '.' "${OUTPUT_FILE}")"
fi

if [[ -n "${INPUT_POST_OPERATION}" ]]; then
    # Post operation mode: update in place, never add.
    #
    # An operation mutates an already released tag, so the only field it may
    # change is the `dependencies` of the entries already describing those tags.
    # Its matrix is pruned to just those tags -- building entries from it, the way
    # the normal path does, would invent entries for tags that were never released
    # and rewrite the other fields from a non-authoritative source. Nothing is
    # reconstructed here, so nothing can be lost, and the normal path's carry-over
    # step needs no counterpart.

    # Relate each probe result back to the entry it belongs to.
    PROBED_ENTRIES="$(echo "${INPUT_BUILD_JOBS}" | jq -cr \
        --arg namespace "${INPUT_NAMESPACE}" \
        --arg repository "${INPUT_REPOSITORY}" \
        --argjson dependencies "${PROBED_DEPENDENCIES}" \
        '[.[]
          | select($dependencies[.platform_tag] != null)
          | {
              platform_tag: .platform_tag,
              platform: .platform,
              docker_image: ($namespace + "/" + $repository + ":" + .tag),
              dependencies: $dependencies[.platform_tag],
            }]')"

    # Fail on anything that does not address exactly one existing entry. Only the
    # jobs that actually probed are checked: one without a probe result has no
    # data to write, so it can neither create an entry nor corrupt one.
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
         | map(($index[[.platform, .docker_image] | tostring] | .dependencies) as $d
               | if $d then . + {dependencies: $d} else . end)')"

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

    # Carry over the dependencies of the entries this build did not probe.
    # Otherwise rebuilding an unprobed image would replace an entry that carries
    # dependencies with one that does not, and an absent `dependencies` means
    # "never probed" -- erasing it is a lie only a rebuild can undo.
    NEW_RUNNERS="$(echo "${NEW_RUNNERS}" | jq -cr \
        --argjson original "${ORIGINAL_RUNNERS}" \
        '($original | INDEX([.platform, .docker_image] | tostring)) as $index
         | map(if has("dependencies") then .
               else . + (($index[[.platform, .docker_image] | tostring] | .dependencies) as $d
                         | if $d then {dependencies: $d} else {} end)
               end)')"

    # Merge new runners with original runners, and distinct by docker_image.
    MERGED_RUNNERS="$(echo "${NEW_RUNNERS}" "${ORIGINAL_RUNNERS}" | jq -cs 'add | unique_by([.platform, .docker_image])')"

    # Normalize the merged runners by sorting them.
    MERGED_RUNNERS="$(echo "${MERGED_RUNNERS}" | jq -cr 'sort_by([.backend, (.backend_variant | explode | map(-.)), (.backend_version | explode | map(-.)), .service, (.service_version | split(".") | map(tonumber?) | map(-.))])')"
fi

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
