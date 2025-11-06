ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.4
ARG VLLM_VERSION=0.10.0
ARG VLLM_NVIDIA_NVSHMEM_VERSION=3.4.5
ARG VLLM_PPLX_KERNEL_COMMIT=c336faf
ARG VLLM_DEEPEP_VERSION=1.2.1
ARG VLLM_DEEPGEMM_VERSION=2.1.1.post3

# Stage vLLM Build DeepGEMM
#

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm-build-deepgemm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build DeepGEMM

ARG CMAKE_MAX_JOBS
ARG VLLM_DEEPGEMM_VERSION

ENV VLLM_DEEPGEMM_VERSION=${VLLM_DEEPGEMM_VERSION}

RUN <<EOF
    # DeepGEMM

    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping DeepGEMM building for ${TARGETARCH}..."
        exit 0
    fi

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
        echo "Skipping DeepGEMM building for CUDA ${CUDA_MAJOR}.${CUDA_MINOR}..."
        exit 0
    fi

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_DEEPGEMM_VERSION} --single-branch \
        https://github.com/deepseek-ai/DeepGEMM deep_gemm

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    DG_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${DG_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            DG_CUDA_ARCHS="9.0a+PTX"
        else
            DG_CUDA_ARCHS="9.0a 10.0a+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${DG_CUDA_ARCHS}"
    export NVCC_THREADS=1
    echo "Building DeepGEMM with the following environment variables:"
    env
    pushd /tmp/deep_gemm \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/deep_gemm/dist \
        && mv /tmp/deep_gemm/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Prepare
#

FROM gpustack/runner:cuda${CUDA_VERSION}-vllm${VLLM_VERSION} AS vllm-prepare
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Polish NVIDIA HPC-X

RUN <<EOF
    # NVIDIA HPC-X

    # Fix DeepEP IBGDA symlink
    ln -sf /usr/lib/$(uname -m)-linux-gnu/libmlx5.so.1 /usr/lib/$(uname -m)-linux-gnu/libmlx5.so || true

    # Review
    ldconfig -v
EOF

## Install NVIDIA NVSHMEM

ARG CMAKE_MAX_JOBS
ARG VLLM_NVIDIA_NVSHMEM_VERSION

ENV VLLM_NVIDIA_NVSHMEM_VERSION=${VLLM_NVIDIA_NVSHMEM_VERSION} \
    VLLM_NVIDIA_NVSHMEM_DIR="/usr/local/nvshmem"

RUN <<EOF
    # NVIDIA NVSHMEM

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${CUDA_VERSION}"

    # Download
    if (( $(echo "${CUDA_MAJOR} > 12" | bc -l) )); then
        curl --retry 3 --retry-connrefused -fL "https://github.com/NVIDIA/nvshmem/releases/download/v${VLLM_NVIDIA_NVSHMEM_VERSION}-0/nvshmem_src_cuda-all-all-${VLLM_NVIDIA_NVSHMEM_VERSION}.tar.gz" | tar -zxv -C /tmp
    else
        curl --retry 3 --retry-connrefused -fL "https://developer.download.nvidia.com/compute/redist/nvshmem/${VLLM_NVIDIA_NVSHMEM_VERSION}/source/nvshmem_src_cuda12-all-all-${VLLM_NVIDIA_NVSHMEM_VERSION}.tar.gz" | tar -zxv -C /tmp
    fi

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    NS_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${NS_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
            NS_CUDA_ARCHS="7.5 8.0 8.9"
        elif (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
            NS_CUDA_ARCHS="7.5 8.0 8.9 9.0"
        else
            NS_CUDA_ARCHS="7.5 8.0 8.9 9.0 10.0 10.3 12.0"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export CUDA_ARCH="${NS_CUDA_ARCHS}"
    # Disable all features except IBGDA
    export NVSHMEM_IBGDA_SUPPORT=1
    export NVSHMEM_SHMEM_SUPPORT=0
    export NVSHMEM_UCX_SUPPORT=0
    export NVSHMEM_USE_NCCL=0
    export NVSHMEM_PMIX_SUPPORT=0
    export NVSHMEM_TIMEOUT_DEVICE_POLLING=0
    export NVSHMEM_USE_GDRCOPY=1
    export NVSHMEM_IBRC_SUPPORT=0
    export NVSHMEM_BUILD_TESTS=0
    export NVSHMEM_BUILD_EXAMPLES=0
    export NVSHMEM_MPI_SUPPORT=0
    export NVSHMEM_BUILD_HYDRA_LAUNCHER=0
    export NVSHMEM_BUILD_TXZ_PACKAGE=0
    export NVSHMEM_TIMEOUT_DEVICE_POLLING=0
    export NVCC_THREADS=1
    echo "Building NVSHMEM with the following environment variables:"
    env
    # FIX: Hide Python3.10 to avoid issues with Python version mismatch.
    PYTHON3_10_BIN=$(which python3.10 || true)
    if [[ -n "${PYTHON3_10_BIN}" ]]; then
        mv "${PYTHON3_10_BIN}" /tmp/python3.10
    fi
    pushd /tmp/nvshmem_src \
        && cmake -G Ninja -S . -B build -DCMAKE_INSTALL_PREFIX=${VLLM_NVIDIA_NVSHMEM_DIR} \
        && cmake --build build --target install -j${MAX_JOBS}
    if [[ -n "${PYTHON3_10_BIN}" ]]; then
        mv /tmp/python3.10 "${PYTHON3_10_BIN}"
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Prepare PPLX Kernels
#

FROM vllm-prepare AS vllm-prepare-pplx-kernels
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build PPLX Kernel

ARG CMAKE_MAX_JOBS
ARG VLLM_PPLX_KERNEL_COMMIT

ENV VLLM_PPLX_KERNEL_COMMIT=${VLLM_PPLX_KERNEL_COMMIT}

RUN <<EOF
    # PPLX Kernels

    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping PPLX Kernels building for ${TARGETARCH}..."
        exit 0
    fi

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/ppl-ai/pplx-kernels pplx-kernels \
        && pushd /tmp/pplx-kernels \
        && git checkout ${VLLM_PPLX_KERNEL_COMMIT}

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    PP_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${PP_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
            PP_CUDA_ARCHS="9.0a+PTX"
        else
            PP_CUDA_ARCHS="9.0a 10.0a 12.0a+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${PP_CUDA_ARCHS}"
    export NVSHMEM_DIR="${VLLM_NVIDIA_NVSHMEM_DIR}"
    echo "Building PPLX Kernels with the following environment variables:"
    env
    pushd /tmp/pplx-kernels \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/pplx-kernels/dist \
        && mv /tmp/pplx-kernels/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Prepare DeepEP
#

FROM vllm-prepare AS vllm-prepare-deepep
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build DeepEP

ARG CMAKE_MAX_JOBS
ARG VLLM_DEEPEP_VERSION

ENV VLLM_DEEPEP_VERSION=${VLLM_DEEPEP_VERSION}

RUN <<EOF
    # DeepEP

    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping DeepEP building for ${TARGETARCH}..."
        exit 0
    fi

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
        echo "Skipping DeepEP building for CUDA ${CUDA_MAJOR}.${CUDA_MINOR}..."
        exit 0
    fi

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_DEEPEP_VERSION} --single-branch \
        https://github.com/deepseek-ai/DeepEP deep_ep

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    DP_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${DP_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
            DP_CUDA_ARCHS="9.0a+PTX"
        else
            DP_CUDA_ARCHS="9.0a 10.0a 12.0a+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${DP_CUDA_ARCHS}"
    export NVSHMEM_DIR="${VLLM_NVIDIA_NVSHMEM_DIR}"
    echo "Building DeepEP with the following environment variables:"
    env
    pushd /tmp/deep_ep \
        && sed -i 's/#define NUM_CPU_TIMEOUT_SECS 100/#define NUM_CPU_TIMEOUT_SECS 1000/' csrc/kernels/configs.cuh \
        && if (( $(echo "${CUDA_MAJOR} > 12" | bc -l) )); then \
            sed -i "/^    include_dirs = \['csrc\/'\]/a\    include_dirs.append('${CUDA_HOME}/include/cccl')" setup.py; \
        fi \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/deep_ep/dist \
        && mv /tmp/deep_ep/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM
#

FROM vllm-prepare AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install DeepGEMM

RUN --mount=type=bind,from=vllm-build-deepgemm,source=/,target=/deepgemm,rw <<EOF
    # DeepGEMM

    if [[ ! -d /deepgemm/workspace ]]; then
        echo "Skipping DeepGEMM installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /deepgemm/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install PPLX Kernels

RUN --mount=type=bind,from=vllm-prepare-pplx-kernels,source=/,target=/pplx-kernels,rw <<EOF
    # PPLX Kernels

    if [[ ! -d /pplx-kernels/workspace ]]; then
        echo "Skipping PPLX Kernels installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /pplx-kernels/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install DeepEP

RUN --mount=type=bind,from=vllm-prepare-deepep,source=/,target=/deepep,rw <<EOF
    # DeepEP

    if [[ ! -d /deepep/workspace ]]; then
        echo "Skipping DeepEP installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /deepep/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Postprocess

RUN <<EOF
    # Postprocess

    # Review
    uv pip tree \
        --package vllm \
        --package flashinfer-python \
        --package torch \
        --package pplx-kernels \
        --package deep-gemm \
        --package deep-ep \
        --package lmcache
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
