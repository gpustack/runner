ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3
ARG CANN_ARCHS=910b
ARG SGLANG_VERSION=0.12.0
ARG SGLANG_KERNEL_VERSION=20251206

FROM gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-sglang${SGLANG_VERSION} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Reinstall SGLang Kernel

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION
ARG SGLANG_KERNEL_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_KERNEL_VERSION=${SGLANG_KERNEL_VERSION}

RUN <<EOF
    # SGLang

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${CANN_HOME}/ascend-toolkit/latest/$(uname -i)-linux/devlib"
    export LD_LIBRARY_PATH="${CANN_HOME}/ascend-toolkit/latest/runtime/lib64/stub:${LD_LIBRARY_PATH}"
    source ${CANN_HOME}/ascend-toolkit/set_env.sh
    echo "Building SGLang with the following environment variables:"
    env

    # Install Dependencies
    cat <<EOT >/tmp/requirements.txt
attrs==25.4.0
decorator==5.2.1
psutil==7.1.3
pyyaml==6.0.3
triton-ascend==3.2.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Build and Install SGLang Kernel
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch ${SGLANG_KERNEL_VERSION} --single-branch \
        https://github.com/sgl-project/sgl-kernel-npu.git sgl-kernel-npu
    unset ASCEND_HOME_PATH
    pushd /tmp/sgl-kernel-npu \
        && ./build.sh \
        && tree -hs /tmp/sgl-kernel-npu/output \
        && uv pip install /tmp/sgl-kernel-npu/output/deep_ep*.whl /tmp/sgl-kernel-npu/output/sgl_kernel_npu*.whl

    # Postprocess SGLang Kernel (DeepEP)
    cd "$(pip show deep-ep | awk '/^Location:/ {print $2}')" && ln -sf deep_ep/deep_ep_cpp*.so

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
