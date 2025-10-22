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
#    - Install Dependencies.
# 3.2. vllm-build-flashinfer target.
# 3.3. vllm target.
#    - Install Torch.
#    - Install vLLM.
#    - Install FlashInfer if existed.
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
# - VLLM_FLASHINFER_REPOSITORY: Repository URL of FlashInfer to use,
#   which is used to build the FlashInfer wheel.
# - VLLM_FLASHINFER_VERSION: Version of FlashInfer to use,
#   which is used to build the FlashInfer wheel.
ARG PYTHON_VERSION=3.11
ARG CMAKE_MAX_JOBS
ARG CUDA_VERSION=12.6.3
ARG CUDA_ARCHS
ARG VOXBOX_BASE_IMAGE=gpustack/runner:cuda${CUDA_VERSION}-python${PYTHON_VERSION}
ARG VOXBOX_VERSION=0.0.20
ARG VOXBOX_TORCH_VERSION=2.7.1
ARG VOXBOX_TORCH_CUDA_VERSION=${CUDA_VERSION}
ARG VLLM_BASE_IMAGE=gpustack/runner:cuda${CUDA_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.10.1.1
ARG VLLM_TORCH_VERSION=2.7.1
ARG VLLM_TORCH_CUDA_VERSION=${CUDA_VERSION}
ARG VLLM_BUILD_BASE_IMAGE=gpustack/runner:cuda${VLLM_TORCH_CUDA_VERSION}-python${PYTHON_VERSION}
ARG VLLM_FLASHINFER_REPOSITORY=https://github.com/flashinfer-ai/flashinfer.git
ARG VLLM_FLASHINFER_VERSION=0.2.11

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
        libnuma-dev libjemalloc-dev

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
            EXPORT_PYTHON_LIB="export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}"
            echo "${EXPORT_PYTHON_LIB}" >> /etc/profile
            echo "${EXPORT_PYTHON_LIB}" >> ~/.bashrc
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
        python${PYTHON_VERSION}-distutils \
        python${PYTHON_VERSION}-lib2to3 \
        python${PYTHON_VERSION}-gdbm \
        python${PYTHON_VERSION}-tk \
        libibverbs-dev

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
wheel
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
    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} > 12.7" | bc -l) )) || [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
            -r /tmp/requirements.txt
    else
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    fi
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
    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} > 12.7" | bc -l) )) || [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
            -r /tmp/requirements.txt
    else
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    fi
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
pynvml
cuda-python
einops
nvidia-nvshmem-cu${CUDA_MAJOR}
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
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
ARG VLLM_FLASHINFER_REPOSITORY
ARG VLLM_FLASHINFER_VERSION

ENV VLLM_FLASHINFER_REPOSITORY=${VLLM_FLASHINFER_REPOSITORY} \
    VLLM_FLASHINFER_VERSION=${VLLM_FLASHINFER_VERSION}

RUN <<EOF
    # FlashInfer

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"
    IFS="." read -r FI_MAJOR FI_MINOR FI_PATCH <<< "${VLLM_FLASHINFER_VERSION}"

    # Support ARM64 only for CUDA 12.8 and above
    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} <= 12.7" | bc -l) )) && [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping FlashInfer building for ${TARGETARCH}..."
        exit 0
    fi

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_FLASHINFER_VERSION} --single-branch \
        ${VLLM_FLASHINFER_REPOSITORY} flashinfer

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
        if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
            FI_CUDA_ARCHS="7.5 8.0+PTX 8.9"
        elif (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
            FI_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX"
        else
            FI_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX 10.0+PTX 12.0+PTX"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export TORCH_CUDA_ARCH_LIST="${FI_CUDA_ARCHS}"
    export FLASHINFER_LOCAL_VERSION="cu${CUDA_MAJOR}${CUDA_MINOR}torch${TORCH_MAJOR}.${TORCH_MINOR}"
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

# Stage vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/cuda/Dockerfile --tag=gpustack/runner:cuda${CUDA_VERSION%.*}-vllm${VLLM_VERSION}-linux-amd64 --target=vllm pack/cuda
#

FROM ${VLLM_BASE_IMAGE} AS vllm
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
    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} > 12.7" | bc -l) )) || [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
            -r /tmp/requirements.txt
    else
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    fi
    uv pip install \
        numpy scipy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install vLLM

ARG CMAKE_MAX_JOBS
ARG VLLM_VERSION

ENV VLLM_VERSION=${VLLM_VERSION}

RUN <<EOF
    # vLLM

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export NVCC_THREADS=1

    # Install
    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --verbose --extra-index-url https://download.pytorch.org/whl/cu${CUDA_MAJOR}${CUDA_MINOR} \
            vllm==${VLLM_VERSION}
    else
        uv pip install --verbose --extra-index-url https://download.pytorch.org/whl/cpu/ \
            vllm==${VLLM_VERSION}
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install FlashInfer

RUN --mount=type=bind,from=vllm-build-flashinfer,source=/,target=/flashinfer,rw <<EOF
    # FlashInfer

    if [[ ! -d /flashinfer/workspace ]]; then
        echo "Skipping FlashInfer installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install \
        /flashinfer/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install LMCache

RUN <<EOF
    # LMCache

    VLLM_LMCACHE_VERSION=0.3.3

    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L67-L129.

    IFS="." read -r CUDA_MAJOR CUDA_MINOR CUDA_PATCH <<< "${VLLM_TORCH_CUDA_VERSION}"

    # Support ARM64 only for CUDA 12.8 and above
    if (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} <= 12.7" | bc -l) )) && [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping LMCache building for ${TARGETARCH}..."
        exit 0
    fi

    # Install LMCache
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
        if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
            CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
        fi
        if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
            CMAKE_MAX_JOBS="4"
        fi
        LC_CUDA_ARCHS="${CUDA_ARCHS}"
        if [[ -z "${LC_CUDA_ARCHS}" ]]; then
            if (( $(echo "${CUDA_MAJOR} < 12" | bc -l) )); then
                LC_CUDA_ARCHS="7.5 8.0+PTX 8.9"
            elif (( $(echo "${CUDA_MAJOR}.${CUDA_MINOR} < 12.8" | bc -l) )); then
                LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX"
            else
                LC_CUDA_ARCHS="7.5 8.0+PTX 8.9 9.0+PTX 10.0+PTX 12.0+PTX"
            fi
        fi
        export MAX_JOBS="${CMAKE_MAX_JOBS}"
        export TORCH_CUDA_ARCH_LIST="${LC_CUDA_ARCHS}"

        git -C /tmp clone --recursive --shallow-submodules \
            --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
            https://github.com/LMCache/LMCache.git lmcache
        sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
        pip install -v --no-build-isolation /tmp/lmcache
    else
        uv pip install lmcache==${VLLM_LMCACHE_VERSION}
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Ray Client

RUN <<EOF
    # Ray Client

    # Install Ray Client
    RAY_VERSION=$(pip show ray | grep Version: | cut -d' ' -f 2)
    uv pip install "ray[client]==${RAY_VERSION}"

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
timm==0.9.10
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
        --package flashinfer \
        --package torch \
        --package lmcache
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
