#!/usr/bin/env bash

set -eo pipefail

INPUT_POST_OPERATION=${INPUT_POST_OPERATION:-""}
INPUT_BACKEND="${INPUT_BACKEND:-"all"}"
INPUT_TARGET=${INPUT_TARGET:-"services"}
INPUT_FOR_RELEASE=${INPUT_FOR_RELEASE:-"false"}
INPUT_RUNNER_PROFILE=${INPUT_RUNNER_PROFILE:-"normal"}
INPUT_WORKSPACE="${INPUT_WORKSPACE:-"$(dirname "${BASH_SOURCE[0]}")"}"
INPUT_TEMPDIR="${INPUT_TEMPDIR:-"/tmp"}"

if [[ -n "${INPUT_POST_OPERATION}" ]]; then
    INPUT_WORKSPACE="${INPUT_WORKSPACE}/.post_operation/${INPUT_POST_OPERATION}"
fi
echo "[INFO] Using workspace: ${INPUT_WORKSPACE}"
echo "[INFO] Using tempdir: ${INPUT_TEMPDIR}"
echo "[INFO] Expanding matrix for backend: ${INPUT_BACKEND}, target: ${INPUT_TARGET}, for_release: ${INPUT_FOR_RELEASE}, runner_profile: ${INPUT_RUNNER_PROFILE}"

# Filter the rules based on the backend input.
RULES="$(yq '.[]' \
    --output-format json \
    --indent 0 \
    "${INPUT_WORKSPACE}/matrix.yaml")"
if [[ "${INPUT_BACKEND}" != "all" ]]; then
    RULES="$(echo "${RULES}" | jq -cr \
        --arg backend "${INPUT_BACKEND}" \
        '.[] | select(.backend == $backend)' | jq -cs .)"
fi

# Iterate all backends to gain the ARGs from the given Dockerfile.
BACKENDS="$(echo "${RULES}" | jq -r '.[] | .backend' | sort -u | jq -R . | jq -cs .)"
for BACKEND in $(echo "${BACKENDS}" | jq -cr '.[]'); do
    # Get the Dockerfile path for the backend.
    DOCKERFILE="${INPUT_WORKSPACE}/${BACKEND}/Dockerfile"
    if [[ ! -f "${DOCKERFILE}" ]]; then
        echo "[ERROR]: Dockerfile not found: ${DOCKERFILE}"
        exit 1
    fi

    # Merge the extension args into rules.
    if [[ -n "${INPUT_ARGS}" ]]; then
        INPUT_ARGS="$(echo "${INPUT_ARGS}" | jq -R 'split(" ")' | jq -cr 'map(select(. != null and . != "null" and . != ""))')"
        RULES="$(echo "${RULES}" | jq -cr \
            --arg backend "${BACKEND}" \
            --argjson args "${INPUT_ARGS}" \
            'map(if .backend == $backend then .args = .args + $args else . end)')"
    fi

    # Merge the Dockerfile ARGs into rules.
    FULL_ARGS="$(grep -E '^ARG\s+(\w+)=.*' "${DOCKERFILE}" | sed 's/^ARG[[:space:]]+*//;s/[[:space:]]+$//;s/="/=/;s/"$//' | jq -R . | jq -cs .)"
    if [[ "${FULL_ARGS}" == "[\"\"]" ]]; then
        continue
    fi
    RULES="$(echo "${RULES}" | jq -cr \
        --arg backend "${BACKEND}" \
        --argjson full_args "${FULL_ARGS}" \
        'map(if .backend == $backend then {full_args: $full_args} + . else . end)')"
done

# Iterate all items of rules to generate the matrix.
MANIFEST_JOBS="{}"
BUILD_JOBS="[]"
for RULE in $(echo "${RULES}" | jq -cr '.[]'); do
    # Prepare environment variables for sourcing.
    echo "${RULE}" | jq -cr '.full_args + .args' | jq -r '. | map("export " + .) | .[]' >"${INPUT_TEMPDIR}/envs_shared"

    # Extract backend.
    BACKEND="$(echo "${RULE}" | jq -cr '.backend')"
    BACKEND_UPPER="$(echo "${BACKEND}" | tr '[:lower:]' '[:upper:]')"
    BACKEND_VARIANT=""
    {
        echo "export ORIGINAL_BACKEND_VERSION=\${${BACKEND_UPPER}_VERSION}"
        cat <<EOT
IFS="." read -r BV_MAJOR BV_MINOR BV_PATCH BV_POST <<<"\${ORIGINAL_BACKEND_VERSION}"
export BACKEND_VERSION="\${BV_MAJOR}.\${BV_MINOR}"
EOT
        if [[ "${BACKEND}" == "cann" ]]; then
            echo "export BACKEND_VARIANT=\${${BACKEND_UPPER}_ARCHS}"
        fi
    } >>"${INPUT_TEMPDIR}/envs_shared"
    # Extract args.
    ARGS="$(echo "${RULE}" | jq -cr '.args')"

    # Prepare tag prefix/suffix.
    TAG_PREFIX="${BACKEND}\${BACKEND_VERSION}-"
    if [[ "${INPUT_TARGET}" == "runtime" ]]; then
        TAG_PREFIX="${BACKEND}\${${BACKEND_UPPER}_VERSION}-"
    fi
    if [[ "${BACKEND}" == "cann" ]]; then
        TAG_PREFIX="${TAG_PREFIX}\${${BACKEND_UPPER}_ARCHS}-"
    fi
    TAG_SUFFIX="-dev"
    if [[ "${INPUT_FOR_RELEASE}" == "true" ]] || [[ "${INPUT_TARGET}" == "runtime" ]]; then
        TAG_SUFFIX=""
    fi

    # For runtime packing.
    if [[ "${INPUT_TARGET}" == "runtime" ]]; then
        # Prepare environment variables for sourcing.
        cp -f "${INPUT_TEMPDIR}/envs_shared" "${INPUT_TEMPDIR}/envs_dedicated"
        echo "export TAG=${TAG_PREFIX}python\${PYTHON_VERSION}" >>"${INPUT_TEMPDIR}/envs_dedicated"
        # Value from environment variable.
        source "${INPUT_TEMPDIR}/envs_dedicated" &&
            rm -f "${INPUT_TEMPDIR}/envs_dedicated"
        TAG="$(echo "${TAG}" | tr '[:upper:]' '[:lower:]')"
        if [[ -n "${INPUT_TAG}" ]] && [[ "${INPUT_TAG}" != "${TAG}"* ]]; then
            echo "[INFO] Skipping build tag ${TAG}${TAG_SUFFIX} for backend ${BACKEND} runtime..."
            continue
        fi
        # Generate.
        MANIFEST_JOBS="$(echo "${MANIFEST_JOBS}" | jq -cr \
            --arg tag "${TAG}${TAG_SUFFIX}" \
            '{($tag): []} + .')"
        # Iterate all platforms of the item.
        PLATFORMS=($(echo "${RULE}" | jq -cr '(.platforms[])?'))
        if [[ "${#PLATFORMS[@]}" -eq 0 ]]; then
            PLATFORMS=("linux/amd64" "linux/arm64")
        fi
        for PLATFORM in "${PLATFORMS[@]}"; do
            IFS="/" read -r OS ARCH VARIANT <<<"${PLATFORM}"
            PLATFORM_TAG="${TAG}-${OS}-${ARCH}"
            if [[ -n "${INPUT_TAG}" ]] && [[ "${PLATFORM_TAG}" != "${INPUT_TAG}"* ]]; then
                echo "[INFO] Skipping build tag ${PLATFORM_TAG} for backend ${BACKEND} runtime..."
                continue
            fi
            RUNNER="ubuntu-22.04"
            if [[ "${PLATFORM}" == "linux/arm64" ]]; then
                RUNNER="ubuntu-22.04-arm"
            fi
            if [[ "${INPUT_RUNNER_PROFILE}" != "normal" ]]; then
                RUNNER="${RUNNER}-${INPUT_RUNNER_PROFILE}"
            fi
            # Generate.
            MANIFEST_JOBS="$(echo "${MANIFEST_JOBS}" | jq -cr \
                --arg tag "${TAG}${TAG_SUFFIX}" \
                --arg platform_tag "${PLATFORM_TAG}" \
                '.[$tag] += [$platform_tag]')"
            BUILD_JOBS="$(echo "${BUILD_JOBS}" | jq -cr \
                --arg backend "${BACKEND}" \
                --arg backend_version "${BACKEND_VERSION}" \
                --arg backend_variant "${BACKEND_VARIANT}" \
                --arg platform "${PLATFORM}" \
                --arg platform_tag "${PLATFORM_TAG}" \
                --arg tag "${TAG}${TAG_SUFFIX}" \
                --argjson args "${ARGS}" \
                --arg runner "${RUNNER}" \
                --argjson platform_tag_cache "[\"${PLATFORM_TAG}\"]" \
                --arg original_backend_version "${ORIGINAL_BACKEND_VERSION}" \
                '[{
                    backend: $backend,
                    backend_version: $backend_version,
                    backend_variant: $backend_variant,
                    service: "runtime",
                    service_version: "",
                    platform: $platform,
                    platform_tag: $platform_tag,
                    tag: $tag,
                    args: $args,
                    runner: $runner,
                    platform_tag_cache: $platform_tag_cache,
                    original_backend_version: $original_backend_version,
                    deprecated: false,
                  }] + .')"
        done

        continue
    fi

    # For service packing.

    # Iterate all services of the item.
    SERVICES=($(echo "${RULE}" | jq -cr '(.services[])?'))
    if [[ "${#SERVICES[@]}" -eq 0 ]]; then
        echo "[WARN] No services defined for backend '${BACKEND}', skipping..."
        continue
    fi
    for SERVICE in "${SERVICES[@]}"; do
        SERVICE_UPPER="$(echo "${SERVICE}" | tr '[:lower:]' '[:upper:]')"
        if [[ "${INPUT_TARGET}" != "services" && "${INPUT_TARGET}" != "${SERVICE}" ]]; then
            echo "[INFO] Skipping build service '${SERVICE}' for backend '${BACKEND}' as input target '${INPUT_TARGET}'..."
            continue
        fi
        # Prepare environment variables for sourcing.
        cp -f "${INPUT_TEMPDIR}/envs_shared" "${INPUT_TEMPDIR}/envs_dedicated"
        {
            echo "export SERVICE_VERSION=\${${SERVICE_UPPER}_VERSION}"
            cat <<EOT
IFS="." read -r SV_MAJOR SV_MINOR SV_PATCH SV_POST_RELEASE <<<"\${SERVICE_VERSION}"
if [[ -z "\${SV_PATCH}" ]]; then
    SV_PATCH=0
fi
export SERVICE_VERSION_MAJOR="\${SV_MAJOR}"
export SERVICE_VERSION_MINOR="\${SV_MINOR}"
export SERVICE_VERSION_PATCH="\${SV_PATCH}"
export SERVICE_VERSION_POST_RELEASE="\${SV_POST_RELEASE}"
EOT
            echo "export TAG=${TAG_PREFIX}${SERVICE}\${SERVICE_VERSION}"
            echo "export TAG_X=${TAG_PREFIX}${SERVICE}\${SERVICE_VERSION_MAJOR}"
            echo "export TAG_XY=${TAG_PREFIX}${SERVICE}\${SERVICE_VERSION_MAJOR}.\${SERVICE_VERSION_MINOR}"
        } >>"${INPUT_TEMPDIR}/envs_dedicated"
        # Value from environment variable.
        source "${INPUT_TEMPDIR}/envs_dedicated" &&
            rm -f "${INPUT_TEMPDIR}/envs_dedicated"
        TAG="$(echo "${TAG}" | tr '[:upper:]' '[:lower:]')"
        if [[ -n "${INPUT_TAG}" ]] && [[ "${INPUT_TAG}" != "${TAG}"* ]]; then
            echo "[INFO] Skipping build tag '${TAG}${TAG_SUFFIX}' for backend '${BACKEND}' service '${SERVICE}' as input tag '${INPUT_TAG}'..."
            continue
        fi
        TAG_X="$(echo "${TAG_X}" | tr '[:upper:]' '[:lower:]')"
        TAG_XY="$(echo "${TAG_XY}" | tr '[:upper:]' '[:lower:]')"
        # Generate.
        MANIFEST_JOBS="$(echo "${MANIFEST_JOBS}" | jq -cr \
            --arg tag "${TAG}${TAG_SUFFIX}" \
            '{($tag): []} + .')"
        # Iterate all platforms of the item.
        PLATFORMS=($(echo "${RULE}" | jq -cr '(.platforms[])?'))
        if [[ "${#PLATFORMS[@]}" -eq 0 ]]; then
            PLATFORMS=("linux/amd64" "linux/arm64")
        fi
        for PLATFORM in "${PLATFORMS[@]}"; do
            IFS="/" read -r OS ARCH VARIANT <<<"${PLATFORM}"
            PLATFORM_TAG="${TAG}-${OS}-${ARCH}"
            if [[ -n "${INPUT_TAG}" ]] && [[ "${PLATFORM_TAG}" != "${INPUT_TAG}"* ]]; then
                echo "[INFO] Skipping build tag '${PLATFORM_TAG}' for backend '${BACKEND}' service '${SERVICE}' as input tag '${INPUT_TAG}'..."
                continue
            fi
            PLATFORM_TAG_X="${TAG_X}-${OS}-${ARCH}"
            PLATFORM_TAG_XY="${TAG_XY}-${OS}-${ARCH}"
            RUNNER="ubuntu-22.04"
            if [[ "${PLATFORM}" == "linux/arm64" ]]; then
                RUNNER="ubuntu-22.04-arm"
            fi
            if [[ "${INPUT_RUNNER_PROFILE}" != "normal" ]]; then
                RUNNER="${RUNNER}-${INPUT_RUNNER_PROFILE}"
            fi
            # Generate.
            MANIFEST_JOBS="$(echo "${MANIFEST_JOBS}" | jq -cr \
                --arg tag "${TAG}${TAG_SUFFIX}" \
                --arg platform_tag "${PLATFORM_TAG}" \
                '.[$tag] += [$platform_tag]')"
            BUILD_JOBS="$(echo "${BUILD_JOBS}" | jq -cr \
                --arg backend "${BACKEND}" \
                --arg backend_version "${BACKEND_VERSION}" \
                --arg backend_variant "${BACKEND_VARIANT}" \
                --arg service "${SERVICE}" \
                --arg service_version "${SERVICE_VERSION}" \
                --arg platform "${PLATFORM}" \
                --arg platform_tag "${PLATFORM_TAG}" \
                --arg tag "${TAG}${TAG_SUFFIX}" \
                --argjson args "${ARGS}" \
                --arg runner "${RUNNER}" \
                --argjson platform_tag_cache "[\"${PLATFORM_TAG}\",\"${PLATFORM_TAG_XY}\",\"${PLATFORM_TAG_X}\"]" \
                --arg original_backend_version "${ORIGINAL_BACKEND_VERSION}" \
                '[{
                    backend: $backend,
                    backend_version: $backend_version,
                    backend_variant: $backend_variant,
                    service: $service,
                    service_version: $service_version,
                    platform: $platform,
                    platform_tag: $platform_tag,
                    tag: $tag,
                    args: $args,
                    runner: $runner,
                    platform_tag_cache: $platform_tag_cache,
                    original_backend_version: $original_backend_version,
                    deprecated: false,
                  }] + .')"
        done
    done
done

# Export variables.
export RULES
export BUILD_JOBS
export MANIFEST_JOBS

# Review the generated matrix.
echo "[INFO]: Generated Matrix:"
echo "build_jobs="
# Example
# [
#  {
#    "backend": "cuda",
#    "backend_version": "12.6",
#    "backend_variant": "",
#    "service": "vllm",
#    "service_version": "0.9.2",
#    "platform": "linux/arm64",
#    "platform_tag": "cuda12.6-vllm0.9.2-linux-arm64",
#    "tag": "cuda12.6-vllm0.9.2",
#    "args": [
#      "CUDA_VERSION=12.6.3"
#    ],
#    "runner": "ubuntu-22.04-arm",
#    "platform_tag_cache": [
#      "cuda12.6-vllm0.9.2-linux-arm64",
#      "cuda12.6-vllm0.9-linux-arm64",
#      "cuda12.6-vllm0-linux-arm64",
#    ],
#    "original_backend_version": "12.6.3",
#    "deprecated": false
#  },
#  {
#    "backend": "cuda",
#    "backend_version": "12.6",
#    "backend_variant": "",
#    "service": "vllm",
#    "service_version": "0.9.2",
#    "platform": "linux/amd64",
#    "platform_tag": "cuda12.6-vllm0.9.2-linux-amd64",
#    "tag": "cuda12.6-vllm0.9.2",
#    "args": [
#      "CUDA_VERSION=12.6.3"
#    ],
#    "runner": "ubuntu-22.04",
#    "platform_tag_cache": [
#      "cuda12.6-vllm0.9.2-linux-amd64",
#      "cuda12.6-vllm0.9-linux-amd64",
#      "cuda12.6-vllm0-linux-amd64",
#    ],
#    "original_backend_version": "12.6.3",
#    "deprecated": false
#  }
# ]
echo "${BUILD_JOBS}" | jq -r '.'
echo "manifest_jobs="
# Example
# {
#  "cuda12.6-vllm0.9.2-dev": [
#    "cuda12.6-vllm0.9.2-linux-amd64",
#    "cuda12.6-vllm0.9.2-linux-arm64"
#  ]
# }
echo "${MANIFEST_JOBS}" | jq -r '.'

# Export the build_jobs/manifest_jobs to GH output.
echo "build_jobs=${BUILD_JOBS}" >>"$GITHUB_OUTPUT" || true
echo "manifest_jobs=${MANIFEST_JOBS}" >>"$GITHUB_OUTPUT" || true
