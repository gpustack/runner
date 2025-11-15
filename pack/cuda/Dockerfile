# Package logic:
# 1. runtime target:
#    - Install tools.
#    - Upgrade GCC if needed.
#    - Install C buildkit.
#    - Upgrade Python if needed.
#    - Install Python buildkit.
# 2. voxbox target.
#    - Install Torch.
#    - Install VoxBox.
#    - Postprocess, review installation.
# 3.1. vllm-build target.
#    - Install Torch.
#    - Install dependencies.
#    - Build GDRCopy.
#    - Build FlashInfer.
#    - Build FlashAttention if allowed.
#    - Build DeepGEMM.
#    - Build vLLM.
#    - Build LMCache.
# 3.2. vllm-prepare target.
#    - Install GDRCopy.
#    - Install NVIDIA HPC-X.
#    - Install AWS EFA.
#    - Install NVIDIA NVSHMEM.
#    - Install Torch.
#    - Build PPLX kernels.
#    - Build DeepEP.
# 3.3. vllm target.
#    - Install FlashInfer.
#    - Install FlashAttention if exists.
#    - Install PPLX kernels.
#    - Install DeepEP.
#    - Install DeepGEMM.
#    - Install vLLM.
#    - Install LMCache.
#    - Install dependencies.
#    - Postprocess, review installation.
# 4.1. sglang target, reuse vllm target.
#    - Install SGLang from source.
#    - Install SGLang Router from source.
#    - Install dependencies.
#    - Postprocess, review installation.

# Argument usage:
# - PYTHON_VERSION: Version of Python to use.
# - CMAKE_MAX_JOBS: Maximum number of jobs to use for CMake,
#   if not specified, it will be set automatically based on the number of CPU cores.
# - CUDA_VERSION: Version of NVIDIA CUDA runtime environment to use.
# - CUDA_ARCHS: Arch variant list supports for this runtime environment,
#   by default, it relies on the Torch wheel,
#   for example, https://github.com/pytorch/pytorch/blob/d35b27dde516b6fb623a60566d4a05a3961ff10f/.ci/manywheel/build_cuda.sh#L56-L76.
# - NVIDIA_GDRCOPY_VERSION: Version of NVIDIA GPUDirect RDMA Copy to use.
# - NVIDIA_HPCX_VERSION: Version of NVIDIA HPC-X to use.
# - AWS_EFA_VERSION: Version of AWS EFA to use.
# - VOXBOX_BASE_IMAGE: Base image for VoxBox.
# - VOXBOX_VERSION: Version of VoxBox to use.
# - VOXBOX_TORCH_VERSION: Version of Torch for VoxBox to use.
# - VOXBOX_TORCH_CUDA_VERSION: Version of CUDA to use for Torch,
#   which is used to build the components that depend on Torch for VoxBox,
#   if not specified, it will be set as CUDA_VERSION.
# - VLLM_BASE_IMAGE: Base image for vLLM.
# - VLLM_VERSION: Version of vLLM to use.
# - VLLM_TORCH_VERSION: Version of Torch for vLLM to use.
# - VLLM_TORCH_CUDA_VERSION: Version of CUDA to use for Torch,
#   which is used to build the components that depend on Torch.
#   If not specified, it will be set as CUDA_VERSION.
# - VLLM_BUILD_BASE_IMAGE: Base image for vLLM build,
#   which is used to build wheels.
# - VLLM_NVIDIA_GDRCOPY_VERSION: Version of NVIDIA GPUDirect RDMA Copy to use,
#   which is used to build the GDRCopy deb.
# - VLLM_NVIDIA_HPCX_VERSION: Version of NVIDIA HPC-X to use.
# - VLLM_NVIDIA_NVSHMEM_VERSION: Version of NVIDIA NVSHMEM to use.
# - VLLM_AWS_EFA_VERSION: Version of AWS EFA to use.
# - VLLM_PPLX_KERNEL_COMMIT: Commit hash of PPLX kernel to use,
#   which is used to build the pplx kernels wheel.
# - VLLM_DEEPEP_VERSION: Version of DeepEP to use,
#   which is used to build the DeepEP wheel.
# - VLLM_DEEPGEMM_VERSION: Version of DeepGEMM to use,
#   which is used to build the DeepGEMM wheel.
# - VLLM_FLASHINFER_VERSION: Version of FlashInfer to use,
#   which is used to build the FlashInfer wheel.
# - VLLM_LMCACHE_VERSION: Version of lmcache to use.
# - SGLANG_BASE_IMAGE: Base image for SGLang.
# - SGLANG_BUILD_BASE_IMAGE: Base image for SGLang build,
#   which is used to build the SGLang from source.
# - SGLANG_VERSION: Version of SGLang to use.
# - SGLANG_KERNEL_VERSION: Version of SGLang Kernel to use.
ARG PYTHON_VERSION=3.12
ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.9.1
ARG CUDA_ARCHS
ARG VOXBOX_BASE_IMAGE=gpustack/runner:cuda${CUDA_VERSION}-python${PYTHON_VERSION}
ARG VOXBOX_VERSION=0.0.20
ARG VOXBOX_TORCH_VERSION=2.7.1
ARG VOXBOX_TORCH_CUDA_VERSION=${CUDA_VERSION}
ARG VLLM_BASE_IMAGE=gpustack/runner:cuda${CUDA_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.11.1rc7
ARG VLLM_TORCH_VERSION=2.9.0
ARG VLLM_TORCH_CUDA_VERSION=${CUDA_VERSION}
ARG VLLM_BUILD_BASE_IMAGE=gpustack/runner:cuda${VLLM_TORCH_CUDA_VERSION}-python${PYTHON_VERSION}
ARG VLLM_NVIDIA_GDRCOPY_VERSION=2.5.1
ARG VLLM_NVIDIA_HPCX_VERSION=2.24.1_cuda12
ARG VLLM_NVIDIA_NVSHMEM_VERSION=3.4.5
ARG VLLM_AWS_EFA_VERSION=1.44.0
ARG VLLM_PPLX_KERNEL_COMMIT=c336faf
ARG VLLM_DEEPEP_VERSION=1.2.1
ARG VLLM_DEEPGEMM_VERSION=2.1.1.post3
ARG VLLM_FLASHINFER_VERSION=0.5.2
ARG VLLM_FLASHATTENTION_VERSION=2.8.2
ARG VLLM_LMCACHE_VERSION=0.3.9post2
ARG SGLANG_BASE_IMAGE=vllm
ARG SGLANG_BUILD_BASE_IMAGE=${SGLANG_BASE_IMAGE}
ARG SGLANG_VERSION=0.5.5.post3
ARG SGLANG_KERNEL_VERSION=0.3.17.post1

#
# Stage Bake Runtime
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-python${PYTHON_VERSION}-linux-amd64 --target=runtime pack/cuda
#

FROM nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04 AS runtime
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install Tools

ENV DEBIAN_FRONTEND=noninteractive \
    LANG='en_US.UTF-8' \
    LANGUAGE='en_US:en' \
    LC_ALL='en_US.UTF-8'

RUN <<EOF
    # Tools

    # Refresh
    apt-get update -y && apt-get install -y --no-install-recommends \
        software-properties-common apt-transport-https \
        ca-certificates gnupg2 lsb-release gnupg-agent \
      && apt-get update -y \
      && add-apt-repository -y ppa:ubuntu-toolchain-r/test \
      && apt-get update -y

    # Install
    apt-get install -y --no-install-recommends \
        ca-certificates build-essential binutils bash openssl \
        curl wget aria2 \
        git git-lfs \
        unzip xz-utils \
        tzdata locales \
        iproute2 iputils-ping ifstat net-tools dnsutils pciutils ipmitool \
        rdma-core rdmacm-utils infiniband-diags \
        procps sysstat htop \
        tini vim jq bc tree

    # Update locale
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

    # Update timezone
    rm -f /etc/localtime \
        && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
        && echo "Asia/Shanghai" > /etc/timezone \
        && dpkg-reconfigure --frontend noninteractive tzdata

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Upgrade GCC if needed

RUN <<EOF
    # GCC

    # Upgrade GCC if the Ubuntu version is lower than 21.04.
    source /etc/os-release
    if (( $(echo "${VERSION_ID} >= 21.04" | bc -l) )); then
        echo "Skipping GCC upgrade for ${VERSION_ID}..."
        exit 0
    fi

    # Install
    apt-get install -y --no-install-recommends \
        gcc-11 g++-11 gfortran-11 gfortran

    # Update alternatives
    if [[ -f /etc/alternatives/gcov-dump ]]; then update-alternatives --remove-all gcov-dump; fi; update-alternatives --install /usr/bin/gcov-dump gcov-dump /usr/bin/gcov-dump-11 10
    if [[ -f /etc/alternatives/lto-dump ]]; then update-alternatives --remove-all lto-dump; fi; update-alternatives --install /usr/bin/lto-dump lto-dump /usr/bin/lto-dump-11 10
    if [[ -f /etc/alternatives/gcov ]]; then update-alternatives --remove-all gcov; fi; update-alternatives --install /usr/bin/gcov gcov /usr/bin/gcov-11 10
    if [[ -f /etc/alternatives/gcc ]]; then update-alternatives --remove-all gcc; fi; update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 10
    if [[ -f /etc/alternatives/gcc-nm ]]; then update-alternatives --remove-all gcc-nm; fi; update-alternatives --install /usr/bin/gcc-nm gcc-nm /usr/bin/gcc-nm-11 10
    if [[ -f /etc/alternatives/cpp ]]; then update-alternatives --remove-all cpp; fi; update-alternatives --install /usr/bin/cpp cpp /usr/bin/cpp-11 10
    if [[ -f /etc/alternatives/g++ ]]; then update-alternatives --remove-all g++; fi; update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-11 10
    if [[ -f /etc/alternatives/gcc-ar ]]; then update-alternatives --remove-all gcc-ar; fi; update-alternatives --install /usr/bin/gcc-ar gcc-ar /usr/bin/gcc-ar-11 10
    if [[ -f /etc/alternatives/gcov-tool ]]; then update-alternatives --remove-all gcov-tool; fi; update-alternatives --install /usr/bin/gcov-tool gcov-tool /usr/bin/gcov-tool-11 10
    if [[ -f /etc/alternatives/gcc-ranlib ]]; then update-alternatives --remove-all gcc-ranlib; fi; update-alternatives --install /usr/bin/gcc-ranlib gcc-ranlib /usr/bin/gcc-ranlib-11 10
    if [[ -f /etc/alternatives/gfortran ]]; then update-alternatives --remove-all gfortran; fi; update-alternatives --install /usr/bin/gfortran gfortran /usr/bin/gfortran-11 10

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install C buildkit

RUN <<EOF
    # C buildkit

    # Install
    apt-get install -y --no-install-recommends \
        make ninja-build pkg-config ccache
    curl --retry 3 --retry-connrefused -fL "https://github.com/Kitware/CMake/releases/download/v3.31.7/cmake-3.31.7-linux-$(uname -m).tar.gz" | tar -zx -C /usr --strip-components 1

    # Install dependencies
    apt-get install -y --no-install-recommends \
        perl-openssl-defaults perl yasm \
        zlib1g zlib1g-dev libbz2-dev libffi-dev libgdbm-dev libgdbm-compat-dev \
        openssl libssl-dev libsqlite3-dev lcov libomp-dev \
        libblas-dev liblapack-dev libopenblas-dev libblas3 liblapack3 libhdf5-dev \
        libxml2 libxslt1-dev libgl1-mesa-glx libgmpxx4ldbl \
        libncurses5-dev libreadline6-dev libsqlite3-dev \
        liblzma-dev lzma lzma-dev tk-dev uuid-dev libmpdec-dev \
        ffmpeg libjpeg-dev libpng-dev libtiff-dev libwebp-dev \
        libnuma1 libnuma-dev libjemalloc-dev \
        libgrpc-dev libgrpc++-dev libprotobuf-dev protobuf-compiler protobuf-compiler-grpc \
        libnl-route-3-200 libnl-3-200 libnl-3-dev  libnl-route-3-dev \
        libibverbs1 libibverbs-dev \
        librdmacm1 librdmacm-dev \
        libibumad3 libibumad-dev \
        libtool \
        ibverbs-utils ibverbs-providers libibverbs-dev

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Upgrade Python if needed

ARG PYTHON_VERSION

ENV PYTHON_VERSION=${PYTHON_VERSION}

RUN <<EOF
    # Python

    if (( $(echo "$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2) == ${PYTHON_VERSION}" | bc -l) )); then
        echo "Skipping Python upgrade for ${PYTHON_VERSION}..."
        if [[ -z "$(ldconfig -v 2>/dev/null | grep libpython${PYTHON_VERSION})" ]]; then
            PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
            echo "${PYTHON_LIB_PREFIX}/lib" >> /etc/ld.so.conf.d/python3.conf
            echo "${PYTHON_LIB_PREFIX}/lib64" >> /etc/ld.so.conf.d/python3.conf
            ldconfig -v
        fi
        exit 0
    fi

    # Add deadsnakes PPA for Python versions
    for i in 1 2 3; do
        add-apt-repository -y ppa:deadsnakes/ppa && break || { echo "Attempt $i failed, retrying in 5s..."; sleep 5; }
    done
    apt-get update -y

    # Install
    apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-dev \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-lib2to3 \
        python${PYTHON_VERSION}-gdbm \
        python${PYTHON_VERSION}-tk
    if (( $(echo "${PYTHON_VERSION} <= 3.11" | bc -l) )); then
        apt-get install -y --no-install-recommends \
            python${PYTHON_VERSION}-distutils
    fi

    # Update alternatives
    if [[ -f /etc/alternatives/python3 ]]; then update-alternatives --remove-all python3; fi; update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1
    if [[ -f /etc/alternatives/python ]]; then update-alternatives --remove-all python; fi; update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1
    curl -sS "https://bootstrap.pypa.io/get-pip.py" | python${PYTHON_VERSION}
    if [[ -f /etc/alternatives/2to3 ]]; then update-alternatives --remove-all 2to3; fi; update-alternatives --install /usr/bin/2to3 2to3 /usr/bin/2to3${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/pydoc3 ]]; then update-alternatives --remove-all pydoc3; fi; update-alternatives --install /usr/bin/pydoc3 pydoc3 /usr/bin/pydoc${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/idle3 ]]; then update-alternatives --remove-all idle3; fi; update-alternatives --install /usr/bin/idle3 idle3 /usr/bin/idle${PYTHON_VERSION} 1 || true
    if [[ -f /etc/alternatives/python3-config ]]; then update-alternatives --remove-all python3-config; fi; update-alternatives --install /usr/bin/python3-config python3-config /usr/bin/python${PYTHON_VERSION}-config 1 || true

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install Python buildkit

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIPX_HOME=/root/.local/share/pipx \
    PIPX_LOCAL_VENVS=/root/.local/share/pipx/venvs \
    UV_NO_CACHE=1 \
    UV_HTTP_TIMEOUT=500 \
    UV_INDEX_STRATEGY="unsafe-best-match"

RUN <<EOF
    # Buildkit

    cat <<EOT >/tmp/requirements.txt
build
cmake<4
ninja<1.11
setuptools<80
setuptools-scm
packaging<25
wheel==0.45.1
pybind11<3
Cython
psutil
pipx
uv
EOT
    pip install -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Declare Environment

ARG CUDA_VERSION
ARG CUDA_ARCHS

ENV CUDA_HOME="/usr/local/cuda" \
    CUDA_VERSION=${CUDA_VERSION} \
    CUDA_ARCHS=${CUDA_ARCHS}

# Stage VoxBox
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-voxbox-linux-amd64 --target=voxbox pack/cuda
#

FROM ${VOXBOX_BASE_IMAGE} AS voxbox
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Torch

ARG VOXBOX_TORCH_VERSION
ARG VOXBOX_TORCH_CUDA_VERSION

ENV VOXBOX_TORCH_VERSION=${VOXBOX_TORCH_VERSION} \
    VOXBOX_TORCH_CUDA_VERSION=${VOXBOX_TORCH_CUDA_VERSION}

RUN <<EOF
    # Torch

    # Install
    cat <<EOT >/tmp/requirements.txt
torch==${VOXBOX_TORCH_VERSION}
torchvision
torchaudio
EOT
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VOXBOX_TORCH_CUDA_VERSION}"
    uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
        -r /tmp/requirements.txt
    uv pip install \
        numpy scipy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install VoxBox

ARG VOXBOX_VERSION

ENV VOXBOX_VERSION=${VOXBOX_VERSION}

RUN <<EOF
    # VoxBox

    unset UV_PRERELEASE

    # Install
    cat <<EOT >/tmp/requirements.txt
transformers==4.51.3
numba==0.61.2
llvmlite==0.44.0  # Compatible with Python 3.11
httpx<1.0
vox-box==${VOXBOX_VERSION}
EOT
    uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Review
    uv pip tree \
        --package vox-box \
        --package torch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage vLLM Build
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-linux-amd64 --target=vllm-build pack/cuda
#

FROM ${VLLM_BUILD_BASE_IMAGE} AS vllm-build
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Torch

ARG VLLM_TORCH_VERSION
ARG VLLM_TORCH_CUDA_VERSION

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_CUDA_VERSION=${VLLM_TORCH_CUDA_VERSION}

RUN <<EOF
    # Torch

    # Install
    cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"
    uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
        -r /tmp/requirements.txt
    uv pip install \
        numpy scipy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    cat <<EOT >/tmp/requirements.txt
requests
pyyaml
einops
cuda-python==${CUDA_MAJOR}.${CUDA_MINOR}
pynvml==${CUDA_MAJOR}
nvidia-nvshmem-cu${CUDA_MAJOR}
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build GDRCopy
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-gdrcopy-linux-amd64 --target=vllm-build-gdrcopy pack/cuda
#

FROM vllm-build AS vllm-build-gdrcopy
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build GDRCopy

ARG CMAKE_MAX_JOBS
ARG VLLM_NVIDIA_GDRCOPY_VERSION

ENV VLLM_NVIDIA_GDRCOPY_VERSION=${VLLM_NVIDIA_GDRCOPY_VERSION}

RUN <<EOF
    # GDRCopy

    # Install Dependencies
    apt-get install -y --no-install-recommends \
        build-essential \
        devscripts \
        debhelper \
        fakeroot \
        pkg-config \
        dkms

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_NVIDIA_GDRCOPY_VERSION} --single-branch \
        https://github.com/NVIDIA/gdrcopy gdrcopy

    # Build
    pushd /tmp/gdrcopy/packages && \
        CUDA=/usr/local/cuda ./build-deb-packages.sh && \
        tree -hs /tmp/gdrcopy/packages && \
        mv /tmp/gdrcopy/packages /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

# Stage vLLM Build FlashInfer
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-flashinfer-linux-amd64 --target=vllm-build-flashinfer pack/cuda
#

FROM vllm-build AS vllm-build-flashinfer
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build FlashInfer

ARG CMAKE_MAX_JOBS
ARG VLLM_FLASHINFER_VERSION

ENV VLLM_FLASHINFER_VERSION=${VLLM_FLASHINFER_VERSION}

RUN <<EOF
    # FlashInfer

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    PREBUILD_URL="https://github.com/flashinfer-ai/flashinfer/releases/download/v${VLLM_FLASHINFER_VERSION}/flashinfer_jit_cache-${VLLM_FLASHINFER_VERSION}+cu128-cp39-abi3-manylinux_2_28_$(uname -m).whl"
    if curl --retry 3 --retry-connrefused -fsSIL "${PREBUILD_URL}" >/dev/null 2>&1; then
        echo "Downloading prebuilt FlashInfer wheel from ${PREBUILD_URL}..."
        curl --retry 3 --retry-connrefused -fL "${PREBUILD_URL}" -o "/tmp/flashinfer_jit_cache-${VLLM_FLASHINFER_VERSION}+cu128-cp39-abi3-manylinux_2_28_$(uname -m).whl"
        curl --retry 3 --retry-connrefused -fL "https://github.com/flashinfer-ai/flashinfer/releases/download/v${VLLM_FLASHINFER_VERSION}/flashinfer_python-${VLLM_FLASHINFER_VERSION}-py3-none-any.whl" -o "/tmp/flashinfer_python-${VLLM_FLASHINFER_VERSION}-py3-none-any.whl"
        mkdir -p /workspace \
            && mv /tmp/*.whl /workspace \
            && tree -hs /workspace
        exit 0
    fi

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_FLASHINFER_VERSION} --single-branch \
        https://github.com/flashinfer-ai/flashinfer.git flashinfer

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    FI_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${FI_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            FI_CUDA_ARCHS="7.5 8.0 8.9 9.0a 10.0a 12.0a"
        else
            FI_CUDA_ARCHS="7.5 8.0 8.9 9.0a 10.0a 10.3a 12.0a"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${FI_CUDA_ARCHS}"
    export FLASHINFER_CUDA_ARCH_LIST="${FI_CUDA_ARCHS}"
    export FLASHINFER_LOCAL_VERSION="cu${CUDA_MAJOR}${CUDA_MINOR}torch${TORCH_MAJOR}.${TORCH_MINOR}"
    export NVCC_THREADS=1
    export LD_PRELOAD="${CUDA_HOME}/lib64/libcudart.so:${LD_PRELOAD}"  # Ensure CUDA runtime is preloaded
    echo "Building FlashInfer with the following environment variables:"
    env
    pushd /tmp/flashinfer \
      && echo "${VLLM_FLASHINFER_VERSION}" > version.txt \
      && python -v -m flashinfer.aot \
      && python -v -m build --no-isolation --wheel \
      && tree -hs /tmp/flashinfer/dist \
      && mv /tmp/flashinfer/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build DeepGEMM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-deepgemm-linux-amd64 --target=vllm-build-deepgemm pack/cuda
#

FROM vllm-build AS vllm-build-deepgemm
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

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_DEEPGEMM_VERSION} --single-branch \
        https://github.com/deepseek-ai/DeepGEMM deep_gemm

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    DP_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${DP_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            DP_CUDA_ARCHS="9.0a+PTX"
        else
            DP_CUDA_ARCHS="9.0a 10.0a+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${DP_CUDA_ARCHS}"
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

# Stage vLLM Build FlashAttention
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-flashattention-linux-amd64 --target=vllm-build-flashattention pack/cuda
#

FROM vllm-build AS vllm-build-flashattention
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build FlashAttention

ARG CMAKE_MAX_JOBS
ARG VLLM_FLASHATTENTION_VERSION

ENV VLLM_FLASHATTENTION_VERSION=${VLLM_FLASHATTENTION_VERSION}

RUN <<EOF
    # FlashAttention

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Support ARM64 only
    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping FlashAttention building for ${TARGETARCH}..."
        exit 0
    fi

    PREBUILD_URL="https://github.com/Dao-AILab/flash-attention/releases/download/v${VLLM_FLASHATTENTION_VERSION}/flash_attn-${VLLM_FLASHATTENTION_VERSION}+cu${CUDA_MAJOR}torch${TORCH_MAJOR}.${TORCH_MINOR}cxx11abiFALSE-cp310-cp310-linux_$(uname -m).whl"
    if curl --retry 3 --retry-connrefused -fsSIL "${PREBUILD_URL}" >/dev/null 2>&1; then
        echo "Downloading prebuilt FlashAttention wheel from ${PREBUILD_URL}..."
        curl --retry 3 --retry-connrefused -fL "${PREBUILD_URL}" -o "/tmp/flash_attn-${VLLM_FLASHATTENTION_VERSION}+cu${CUDA_MAJOR}torch${TORCH_MAJOR}.${TORCH_MINOR}cxx11abiFALSE-cp310-cp310-linux_$(uname -m).whl"
        mkdir -p /workspace \
            && mv /tmp/*.whl /workspace \
            && tree -hs /workspace
        exit 0
    fi

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_FLASHATTENTION_VERSION} --single-branch \
        https://github.com/Dao-AILab/flash-attention.git flashattention

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 2" | bc -l) )); then
        CMAKE_MAX_JOBS="2"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export BUILD_TARGET="cuda"
    export NVCC_THREADS=2
    echo "Building FlashAttention with the following environment variables:"
    env
    pushd /tmp/flashattention \
      && python -v -m build --no-isolation --wheel \
      && tree -hs /tmp/flashattention/dist \
      && mv /tmp/flashattention/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-vllm-linux-amd64 --target=vllm-build-vllm pack/cuda
#

FROM vllm-build AS vllm-build-vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build vLLM

ARG CMAKE_MAX_JOBS
ARG VLLM_VERSION

ENV VLLM_VERSION=${VLLM_VERSION}

RUN --mount=type=bind,from=vllm-build-flashinfer,source=/,target=/flashinfer,rw \
    --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # vLLM

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    VL_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${VL_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            VL_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0+PTX 12.0+PTX"
        else
            VL_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0 10.3 12.0 12.1+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${VL_CUDA_ARCHS}"
    export COMPILE_CUSTOM_KERNELS=1
    export NVCC_THREADS=1

    # Install
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm
    pushd /tmp/vllm \
        && VLLM_TARGET_DEVICE="cuda" python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/vllm/dist \
        && mv /tmp/vllm/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage vLLM Build LMCache
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-build-lmcache-linux-amd64 --target=vllm-build-lmcache pack/cuda
#

FROM vllm-build AS vllm-build-lmcache
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build LMCache

ARG CMAKE_MAX_JOBS
ARG VLLM_LMCACHE_VERSION

ENV VLLM_LMCACHE_VERSION=${VLLM_LMCACHE_VERSION}

RUN --mount=type=bind,from=vllm-build-vllm,source=/,target=/vllm,rw <<EOF
    # LMCache
    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L67-L129.

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install LMCache
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    LC_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${LC_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0+PTX 12.0+PTX"
        else
            LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0 10.3 12.0 12.1+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${LC_CUDA_ARCHS}"
    export NVCC_THREADS=1
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    sed -i "s/\"torch==2\.8\.0\"/\"torch\"/g" /tmp/lmcache/pyproject.toml
    sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    pushd /tmp/lmcache \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/lmcache/dist \
        && mv /tmp/lmcache/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage vLLM Prepare
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-prepare-linux-amd64 --target=vllm-prepare pack/cuda
#

FROM ${VLLM_BASE_IMAGE} AS vllm-prepare
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install GDRCopy,
## See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html#nccl-start-base-gdrcopy.

RUN --mount=type=bind,from=vllm-build-gdrcopy,source=/,target=/gdrcopy,rw <<EOF
    # GDRCopy

    # Install
    dpkg -i /gdrcopy/workspace/libgdrapi_*.deb && \
        ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install NVIDIA HPC-X,
## See https://catalog.ngc.nvidia.com/orgs/nvidia/containers/cuda-dl-base/layers?version=24.12-cuda12.6-devel-ubuntu24.04.

ARG VLLM_NVIDIA_HPCX_VERSION

ENV VLLM_NVIDIA_HPCX_VERSION=${VLLM_NVIDIA_HPCX_VERSION}

RUN <<EOF
    # NVIDIA HPC-X

    # Prepare
    rm -f $(dpkg-query -L libibverbs-dev librdmacm-dev libibumad-dev | grep "\(\.so\|\.a\)$") || true
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${CUDA_VERSION}"
    source /etc/os-release

    # Get Download Version
    # If VLLM_NVIDIA_HPCX_VERSION=2.24.1_cuda13, VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=2.24.1
    # If VLLM_NVIDIA_HPCX_VERSION=2.22.1rc4, VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=2.22.1
    # If VLLM_NVIDIA_HPCX_VERSION=2.21.3, VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=2.21.3
    if [[ "${VLLM_NVIDIA_HPCX_VERSION}" == *"_cuda"* ]]; then
        VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=$(echo "${VLLM_NVIDIA_HPCX_VERSION}" | sed 's/_cuda.*//')
    elif [[ "${VLLM_NVIDIA_HPCX_VERSION}" == *"rc"* ]]; then
        VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=$(echo "${VLLM_NVIDIA_HPCX_VERSION}" | sed 's/rc.*//')
    else
        VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD=${VLLM_NVIDIA_HPCX_VERSION}
    fi

    # Download
    mkdir -p /opt/hpcx
    curl --retry 3 --retry-connrefused -fL "https://content.mellanox.com/hpc/hpc-x/v${VLLM_NVIDIA_HPCX_VERSION}/hpcx-v${VLLM_NVIDIA_HPCX_VERSION_DOWNLOAD}-gcc-inbox-${ID}${VERSION_ID}-cuda${CUDA_MAJOR}-$(uname -m).tbz" | tar -jxv -C /opt/hpcx --strip-components 1

    # Install
    ln -sf /opt/hpcx/ompi /usr/local/mpi
    ln -sf /opt/hpcx/ucx /usr/local/ucx
    sed -i 's/^\(hwloc_base_binding_policy\) = core$/\1 = none/' /opt/hpcx/ompi/etc/openmpi-mca-params.conf
    sed -i 's/^\(btl = self\)$/#\1/' /opt/hpcx/ompi/etc/openmpi-mca-params.conf
    cat <<EOT > /etc/ld.so.conf.d/hpcx.conf
/opt/hpcx/clusterkit/lib
/opt/hpcx/hcoll/lib
/opt/hpcx/nccl_rdma_sharp_plugin/lib
/opt/hpcx/ncclnet_plugin/lib
/opt/hpcx/ompi/lib
/opt/hpcx/sharp/lib
/opt/hpcx/ucc/lib
/opt/hpcx/ucx/lib
EOT

    # Fix DeepEP IBGDA symlink
    ln -sf /usr/lib/$(uname -m)-linux-gnu/libmlx5.so.1 /usr/lib/$(uname -m)-linux-gnu/libmlx5.so || true

    # Review
    ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF
ENV PATH="/usr/local/mpi/bin:/usr/local/ucx/bin:${PATH}" \
    OPAL_PREFIX=/opt/hpcx/ompi \
    OMPI_MCA_coll_hcoll_enable=0

## Install AWS EFA,
## See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html#nccl-start-base-enable.

ARG VLLM_AWS_EFA_VERSION

ENV VLLM_AWS_EFA_VERSION=${VLLM_AWS_EFA_VERSION}

RUN <<EOF
    # AWS EFA

    # Download
    curl --retry 3 --retry-connrefused -fL "https://efa-installer.amazonaws.com/aws-efa-installer-${VLLM_AWS_EFA_VERSION}.tar.gz" | tar -zxv -C /tmp

    # Install
    pushd /tmp/aws-efa-installer && \
        ./efa_installer.sh -y --skip-kmod

    # Prepare
    rm /opt/amazon/efa/lib/libfabric.a || true

    # Review
    ldconfig -v

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF
ENV PATH="${PATH}:/opt/amazon/efa/bin"

## Install NVIDIA NVSHMEM

ARG CMAKE_MAX_JOBS
ARG VLLM_NVIDIA_NVSHMEM_VERSION

ENV VLLM_NVIDIA_NVSHMEM_VERSION=${VLLM_NVIDIA_NVSHMEM_VERSION} \
    VLLM_NVIDIA_NVSHMEM_DIR="/usr/local/nvshmem"

RUN <<EOF
    # NVIDIA NVSHMEM

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${CUDA_VERSION}"

    # Download
    mkdir -p /tmp/nvshmem
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
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    NS_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${NS_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            NS_CUDA_ARCHS="7.5 8.0 8.9 9.0 10.0 12.0"
        else
            NS_CUDA_ARCHS="7.5 8.0 8.9 9.0 10.0 10.3 12.0 12.1"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export CUDA_ARCH="${NS_CUDA_ARCHS}"
    export NVSHMEM_IBGDA_SUPPORT=1
    export NVSHMEM_USE_GDRCOPY=1
    export NVSHMEM_SHMEM_SUPPORT=0
    export NVSHMEM_UCX_SUPPORT=0
    export NVSHMEM_USE_NCCL=0
    export NVSHMEM_PMIX_SUPPORT=0
    export NVSHMEM_TIMEOUT_DEVICE_POLLING=0
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

## Install Torch

ARG VLLM_TORCH_VERSION
ARG VLLM_TORCH_CUDA_VERSION

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_CUDA_VERSION=${VLLM_TORCH_CUDA_VERSION}

RUN <<EOF
    # Torch

    # Install
    cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"
    uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
        -r /tmp/requirements.txt
    uv pip install \
        numpy scipy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Install
    cat <<EOT >/tmp/requirements.txt
requests
pyyaml
einops
cuda-python==${CUDA_MAJOR}.${CUDA_MINOR}
pynvml==${CUDA_MAJOR}
nvidia-nvshmem-cu${CUDA_MAJOR}
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Prepare PPLX Kernels
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-prepare-pplx-kernels-linux-amd64 --target=vllm-prepare-pplx-kernels pack/cuda
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

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/ppl-ai/pplx-kernels.git pplx-kernels \
        && pushd /tmp/pplx-kernels \
        && git checkout ${VLLM_PPLX_KERNEL_COMMIT}

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    PP_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${PP_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            PP_CUDA_ARCHS="9.0a+PTX"
        else
            PP_CUDA_ARCHS="9.0a 10.0a+PTX"
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
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm-prepare-deepep-linux-amd64 --target=vllm-prepare-deepep pack/cuda
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

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_DEEPEP_VERSION} --single-branch \
        https://github.com/deepseek-ai/DeepEP.git deep_ep

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    DP_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${DP_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            DP_CUDA_ARCHS="9.0a+PTX"
        else
            DP_CUDA_ARCHS="9.0a 10.0a+PTX"
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
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm${VLLM_VERSION}-linux-amd64 --target=vllm pack/cuda
#

FROM vllm-prepare AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install vLLM

ARG CMAKE_MAX_JOBS
ARG VLLM_VERSION

ENV VLLM_VERSION=${VLLM_VERSION}

RUN --mount=type=bind,from=vllm-build-vllm,source=/,target=/vllm,rw <<EOF
    # vLLM

    # Install
    uv pip install \
        /vllm/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install PPLX Kernels

RUN --mount=type=bind,from=vllm-prepare-pplx-kernels,source=/,target=/pplx-kernels,rw <<EOF
    # PPLX Kernels

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

    # Install
    uv pip install --no-build-isolation \
        /deepep/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install DeepGEMM

RUN --mount=type=bind,from=vllm-build-deepgemm,source=/,target=/deepgemm,rw <<EOF
    # DeepGEMM

    # Install
    uv pip install --no-build-isolation \
        /deepgemm/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install FlashAttention

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # FlashAttention

    if [[ ! -d /flashattention/workspace ]]; then
        echo "Skipping FlashAttention installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /flashattention/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install FlashInfer

RUN --mount=type=bind,from=vllm-build-flashinfer,source=/,target=/flashinfer,rw <<EOF
    # FlashInfer

    # Install
    uv pip install --no-build-isolation \
        /flashinfer/workspace/*.whl

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi

    # Download pre-compiled cubins
    FLASHINFER_CUBIN_DOWNLOAD_THREADS="${CMAKE_MAX_JOBS}" \
    FLASHINFER_LOGGING_LEVEL=warning \
        python -m flashinfer --download-cubin

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install LMCache

RUN --mount=type=bind,from=vllm-build-lmcache,source=/,target=/lmcache,rw <<EOF
    # LMCache

    # Install
    uv pip install --no-build-isolation \
        /lmcache/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Enhance Ray

RUN <<EOF
    # Ray

    # Install Ray Client and Default
    RAY_VERSION=$(pip show ray | grep Version: | cut -d' ' -f 2)
    cat <<EOT >/tmp/requirements.txt
ray[client]==${RAY_VERSION}
ray[default]==${RAY_VERSION}
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    BITSANDBYTES_VERSION="0.46.1"
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        BITSANDBYTES_VERSION="0.42.0"
    fi
    cat <<EOT >/tmp/requirements.txt
accelerate
hf_transfer
modelscope
bitsandbytes>=${BITSANDBYTES_VERSION}
timm>=1.0.17
boto3
nixl>=0.6.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Review
    uv pip tree \
        --package vllm \
        --package flashinfer-python \
        --package flash-attn \
        --package torch \
        --package triton \
        --package pplx-kernels \
        --package deep-gemm \
        --package deep-ep \
        --package lmcache
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage SGLang Build SGLang
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-sglang-build-sglang-linux-amd64 --target=sglang-build-sglang pack/cuda
#

FROM ${SGLANG_BUILD_BASE_IMAGE} AS sglang-build-sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build SGLang

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION
ARG SGLANG_KERNEL_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_KERNEL_VERSION=${SGLANG_KERNEL_VERSION}

RUN <<EOF
    # SGLang

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    SG_CUDA_ARCHS="${CUDA_ARCHS}"
    if [[ -z "${SG_CUDA_ARCHS}" ]]; then
        if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.9" | bc -l) )); then
            SG_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0+PTX 12.0+PTX"
        else
            SG_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0 10.0 10.3 12.0 12.1+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${SG_CUDA_ARCHS}"
    export COMPILE_CUSTOM_KERNELS=1
    export NVCC_THREADS=1

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang

    # Install SGLang
    pushd /tmp/sglang/python \
        && cp /tmp/sglang/README.md /tmp/sglang/LICENSE . \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/sglang/python/dist \
        && mv /tmp/sglang/python/dist /workspace

    # Install pre-complied SGLang Kernel

    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} <= 12.9" | bc -l) )); then
        curl --retry 3 --retry-connrefused -fL \
            "https://github.com/sgl-project/whl/releases/download/${SGLANG_KERNEL_VERSION}/sgl_kernel-${SGLANG_KERNEL_VERSION}-cp310-abi3-manylinux2014_$(uname -m).whl" \
            -o "/workspace/sgl_kernel-${SGLANG_KERNEL_VERSION}-cp310-abi3-manylinux2014_$(uname -m).whl"
    else
        curl --retry 3 --retry-connrefused -fL \
            "https://github.com/sgl-project/whl/releases/download/${SGLANG_KERNEL_VERSION}/sgl_kernel-${SGLANG_KERNEL_VERSION}+cu130-cp310-abi3-manylinux2014_$(uname -m).whl" \
            -o "/workspace/sgl_kernel-${SGLANG_KERNEL_VERSION}+cu130-cp310-abi3-manylinux2014_$(uname -m).whl"
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage SGLang Build SGLang Router
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-sglang-build-sglangrouter-linux-amd64 --target=sglang-build-sglangrouter pack/cuda
#

FROM ${SGLANG_BUILD_BASE_IMAGE} AS sglang-build-sglangrouter
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build SGLang Router

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION
ARG SGLANG_KERNEL_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_KERNEL_VERSION=${SGLANG_KERNEL_VERSION}

RUN --mount=type=bind,from=sglang-build-sglang,source=/,target=/sglang,rw <<EOF
    # SGlang Router

    # Install Rust
    curl --retry 3 --retry-connrefused --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    export PATH="/root/.cargo/bin:${PATH}" \
        && rustc --version \
        && cargo --version

    # Install build tools
    uv pip install \
        setuptools-rust maturin

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang

    # Install SGLang Router
    pushd /tmp/sglang/sgl-router \
        && ulimit -n 65536 && maturin build --release --features vendored-openssl --out dist \
        && tree -hs /tmp/sglang/sgl-router/dist \
        && mv /tmp/sglang/sgl-router/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /root/.cargo \
        && rm -rf /root/.rustup \
        && sed -i '$d' /root/.profile \
        && sed -i '$d' /root/.bashrc \
        && ccache --clear --clean
EOF

# Stage SGLang
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-sglang-linux-amd64 --target=sglang pack/cuda
#

FROM ${SGLANG_BASE_IMAGE} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install SGLang

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION
ARG SGLANG_KERNEL_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_KERNEL_VERSION=${SGLANG_KERNEL_VERSION}

RUN --mount=type=bind,from=sglang-build-sglang,source=/,target=/sglang,rw <<EOF
    # SGLang

    # Install
    uv pip install \
        /sglang/workspace/*.whl

    # Install SGLang Diffusion Extension
    if [[ "${TARGETARCH}" == "amd64" ]]; then
            cat <<EOT >/tmp/requirements.txt
diffusers==0.35.2
yunchang==0.6.3.post1
opencv-python==4.10.0.84
imageio==2.36.0
imageio-ffmpeg==0.5.1
PyYAML==6.0.1
moviepy>=2.0.0
cloudpickle
remote-pdb
torchcodec==0.5.0
st_attn ==0.0.7
vsa==0.0.4
EOT
        uv pip install \
            -r /tmp/requirements.txt
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install SGLang Router

RUN --mount=type=bind,from=sglang-build-sglangrouter,source=/,target=/sglangrouter,rw <<EOF
    # SGlang Router

    # Install
    uv pip install --force-reinstall \
        /sglangrouter/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install Dependencies,
    # see https://github.com/sgl-project/sglang/blob/41c10e67fcae6ac50dfe283655bdf545d224cba9/docker/Dockerfile#L181-L209.
    cat <<EOT >/tmp/requirements.txt
nvidia-cutlass-dsl==4.3.0.dev0
datamodel_code_generator
mooncake-transfer-engine==0.3.7.post2
nixl
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Review
    uv pip tree \
        --package sglang \
        --package sglang-router \
        --package sgl-kernel \
        --package flashinfer-python \
        --package flash-attn \
        --package triton \
        --package vllm \
        --package torch \
        --package deep-ep \
        --package diffusers \
        --package opencv-python
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
