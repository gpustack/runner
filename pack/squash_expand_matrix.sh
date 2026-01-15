#!/usr/bin/env bash

set -eo pipefail

INPUT_IMAGE=${INPUT_IMAGE:-""}
INPUT_IMAGE_ARCH="${INPUT_IMAGE_ARCH:-"amd64"}"
INPUT_RUNNER_PROFILE="${INPUT_RUNNER_PROFILE:-"normal"}"

if [[ -z "${INPUT_IMAGE}" ]]; then
    echo "[ERROR] Missing required inputs: INPUT_IMAGE."
    exit 1
fi

echo "[INFO] Image: ${INPUT_IMAGE}"

# Determine the list of architectures in the source image manifest list.
ARCHS=$(docker manifest inspect "${INPUT_IMAGE}" | jq -r '.manifests[].platform.architecture' 2>/dev/null || echo "${INPUT_IMAGE_ARCH}")

# Iterate over each architecture to generate the matrix.
MANIFEST_JOBS="{}"
SQUASH_JOBS="[]"
for ARCH in ${ARCHS}; do
    PLATFORM_IMAGE="${INPUT_IMAGE}-linux-${ARCH}"
    PLATFORM="linux/${ARCH}"
    RUNNER="ubuntu-22.04"
    if [[ "${PLATFORM}" == "linux/arm64" ]]; then
        RUNNER="ubuntu-22.04-arm"
    fi
    if [[ "${INPUT_RUNNER_PROFILE}" != "normal" ]]; then
        RUNNER="${RUNNER}-${INPUT_RUNNER_PROFILE}"
    fi
    # Generate.
    MANIFEST_JOBS="$(echo "${MANIFEST_JOBS}" | jq -cr \
        --arg image "${INPUT_IMAGE}" \
        --arg platform_image "${PLATFORM_IMAGE}" \
        '.[$image] += [$platform_image]')"
    SQUASH_JOBS="$(echo "${SQUASH_JOBS}" | jq -cr \
        --arg src_image "${INPUT_IMAGE}" \
        --arg dst_image "${PLATFORM_IMAGE}" \
        --arg platform "${PLATFORM}" \
        --arg runner "${RUNNER}" \
        '[{
            src_image: $src_image,
            dst_image: $dst_image,
            platform: $platform,
            runner: $runner,
         }] + .')"
done

# Export variables.
export MANIFEST_JOBS
export SQUASH_JOBS

# Review the generated matrix.
echo "[INFO]: Generated Matrix:"
echo "squash_jobs="
# Example
# [
#  {
#     "src_image": "gpustack/runner:cuda12.8-vllm0.11.2",
#     "platform": "linux/arm64",
#     "runner": "ubuntu-22.04-arm",
#     "dst_image": "gpustack/runner:cuda12.8-vllm0.11.2-linux-arm64"
#   },
#   {
#     "src_image": "gpustack/runner:cuda12.8-vllm0.11.2",
#     "platform": "linux/amd64",
#     "runner": "ubuntu-22.04",
#     "dst_image": "gpustack/runner:cuda12.8-vllm0.11.2-linux-amd64"
#   }
# ]
echo "${SQUASH_JOBS}" | jq -r '.'
echo "manifest_jobs="
# Example
# {
#   "gpustack/runner:cuda12.8-vllm0.11: [
#       "gpustack/runner:cuda12.8-vllm0.11.2-linux-arm64",
#       "gpustack/runner:cuda12.8-vllm0.11.2-linux-amd64"
#   ]
# }
echo "${MANIFEST_JOBS}" | jq -r '.'


# Export the squash_jobs/manifest_jobs to GH outputs.
echo "squash_jobs=${SQUASH_JOBS}" >> "$GITHUB_OUTPUT" || true
echo "manifest_jobs=${MANIFEST_JOBS}" >> "$GITHUB_OUTPUT" || true
