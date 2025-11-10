# Package logic:
# 1. runtime target:
#    - Install tools.
#    - Upgrade GCC if needed.
#    - Install C buildkit.
#    - Upgrade Python if needed.
#    - Install Python buildkit.
#    - Install Platform toolkit.
# 2.1. vllm-build target.
#    - Install Torch.
#    - Install dependencies.
#    - Build Triton if allowed.
#    - Build FashAttention if allowed.
#    - Build AITER if allowed.
# 2.2. vllm target.
#    - Install Torch.
#    - Install vLLM from source.
#    - Install Triton if existed.
#    - Install FlashAttention if existed.
#    - Install AITER if existed.
#    - Install dependencies.
#    - Postprocess, review installation.
# 3.1. sglang-build target, reuse vllm target.
#    - Build AITER if needed.
# 3.2. sglang target.
#    - Install SGLang/Kernel from source.
#    - Install SGLang Router.
#    - Install dependencies.
#    - Postprocess, review installation.

# Argument usage:
# - PYTHON_VERSION: Version of Python to use.
# - CMAKE_MAX_JOBS: Maximum number of jobs to use for CMake,
#   if not specified, it will be set automatically based on the number of CPU cores.
# - ROCM_VERSION: Version of AMD ROCM runtime environment to use.
# - ROCM_ARCHS: Arch variant list supports for this runtime environment,
#   by default, it relies on the Torch wheel,
#   for example, https://github.com/pytorch/pytorch/blob/134179474539648ba7dee1317959529fbd0e7f89/.ci/docker/libtorch/build.sh#L42.
# - VLLM_BASE_IMAGE: Base image for vLLM.
# - VLLM_VERSION: Version of vLLM to use.
# - VLLM_TORCH_VERSION: Version of Torch for vLLM to use.
# - VLLM_TORCH_ROCM_VERSION: Version of ROCM to use for Torch,
#   which is used to build the components that depend on Torch.
#   If not specified, it will be set as ROCM_VERSION.
# - VLLM_BUILD_BASE_IMAGE: Base image for vLLM build,
#   which is used to build wheels.
# - VLLM_FLASHATTENTION_VERSION: Version of FlashAttention to use,
#   which is used to build the FlashAttention wheel.
# - VLLM_AITER_REPOSITORY: Repository URL of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_AITER_VERSION: Version of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_LMCACHE_VERSION: Version of lmcache to use.
# - SGLANG_BASE_IMAGE: Base image for SGLang.
# - SGLANG_VERSION: Version of SGLang to use.
# - SGLANG_AITER_VERSION: Version of AITER to use,
#   which is used to build the AITER wheel.
# - SGLANG_MOONCAKE_VERSION: Version of MoonCake to use.
ARG PYTHON_VERSION=3.12
ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.0.2
ARG ROCM_ARCHS
ARG VLLM_BASE_IMAGE=gpustack/runner:rocm${ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.11.0
ARG VLLM_TORCH_VERSION=2.8.0
ARG VLLM_TORCH_ROCM_VERSION=${ROCM_VERSION}
ARG VLLM_BUILD_BASE_IMAGE=gpustack/runner:rocm${VLLM_TORCH_ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_FLASHATTENTION_VERSION=2.8.3
ARG VLLM_AITER_VERSION=0.1.6.post2
ARG VLLM_LMCACHE_VERSION=0.3.9post1
ARG SGLANG_BASE_IMAGE=vllm
ARG SGLANG_VERSION=0.5.5
ARG SGLANG_MOONCAKE_VERSION=0.3.7.post2

# Stage Bake Runtime
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm{ROCM_VERSION%.*}-python${PYTHON_VERSION}-linux-amd64 --target=runtime pack/dtk
#

FROM rocm/dev-ubuntu-22.04:${ROCM_VERSION}-complete AS runtime
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
        ibverbs-utils ibverbs-providers libibverbs-dev \
        openmpi-bin openmpi-common libopenmpi-dev

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

ARG ROCM_VERSION
ARG ROCM_ARCHS

ENV ROCM_HOME="/opt/rocm" \
    ROCM_VERSION=${ROCM_VERSION} \
    ROCM_ARCHS=${ROCM_ARCHS}

## Install Platform toolkit

RUN <<EOF
    # Toolkit

    uv pip install --system amdsmi==${ROCM_VERSION}

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-linux-amd64 --target=vllm-build pack/rocm
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
ARG VLLM_TORCH_ROCM_VERSION

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION}

RUN <<EOF
    # Torch

    # Install
    IFS="." read -r PYTHON_MAJOR PYTHON_MINOR <<< "${PYTHON_VERSION}"
    WHEEL_SUFFIX="cp${PYTHON_MAJOR}${PYTHON_MINOR}-linux_$(uname -m).whl"
    TRITON_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "triton" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCH_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCHVISION_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torchvision" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCHAUDIO_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    if [[ -z "${TORCH_URL}" || -z "${TORCHVISION_URL}" || -z "${TORCHAUDIO_URL}" ]]; then
        echo "Failed to get ROCM PyTorch wheels for version ${VLLM_TORCH_VERSION} from radeon source."
        exit 1
    fi
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TRITON_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCH_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCHVISION_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCHAUDIO_URL}"
    uv pip install \
        numpy scipy
    exit 0

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    cat <<EOT >/tmp/requirements.txt
requests
pyyaml
einops
pandas
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build FlashAttention
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-flashattention-linux-amd64 --target=vllm-build-flashattention pack/rocm
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
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r FA_MAJOR FA_MINOR FA_PATCH <<< "${VLLM_FLASHATTENTION_VERSION}"

    # Support ARM64 only
    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping FlashAttention building for ${TARGETARCH}..."
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
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    FA_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${FA_ROCM_ARCHS}" ]]; then
        if (( $(echo "${FA_MAJOR}.${FA_MINOR} <= 2.7" | bc -l) )); then
            # See https://github.com/Dao-AILab/flash-attention/blob/c555642172e281cae6da8a6cff4dfd9ff678ae85/setup.py#L126-L133.
            FA_ROCM_ARCHS="gfx90a;gfx940;gfx941;gfx942"
        else
            # See https://github.com/Dao-AILab/flash-attention/blob/6f8f0406eea522735d590c2d7b46139167b95b6e/setup.py#L133-L140.
            FA_ROCM_ARCHS="gfx90a;gfx950;gfx942"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export GPU_ARCHS="${FA_ROCM_ARCHS}"
    export BUILD_TARGET="rocm"
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

# Stage vLLM Build AITER
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-aiter-linux-amd64 --target=vllm-build-aiter pack/rocm
#

FROM vllm-build AS vllm-build-aiter
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build AITER

ARG CMAKE_MAX_JOBS
ARG VLLM_AITER_VERSION

ENV VLLM_AITER_VERSION=${VLLM_AITER_VERSION}

RUN <<EOF
    # AITER

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r AT_MAJOR AT_MINOR AT_PATCH <<< "${VLLM_AITER_VERSION}"

    # Support ARM64 only
    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping AITER building for ${TARGETARCH}..."
        exit 0
    fi

    # Prepare
    TORCH_LIB_PREFIX=$(pip show torch | grep Location: | cut -d' ' -f 2)
    echo "${TORCH_LIB_PREFIX}/torch/lib" >> /etc/ld.so.conf.d/python3.conf

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_AITER_VERSION} --single-branch \
        https://github.com/ROCm/aiter.git aiter

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    AT_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${AT_ROCM_ARCHS}" ]]; then
        AT_ROCM_ARCHS="gfx942;gfx950"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export GPU_ARCHS="${AT_ROCM_ARCHS}"
    export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/local/lib:${TORCH_LIB_PREFIX}/torch/lib:${LD_LIBRARY_PATH}"
    export BUILD_TARGET="rocm"
    export PREBUILD_KERNELS=1
    echo "Building AITER with the following environment variables:"
    env
    pushd /tmp/aiter \
      && python setup.py bdist_wheel --dist-dir=dist \
      && tree -hs /tmp/aiter/dist \
      && mv /tmp/aiter/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-linux-amd64 --target=vllm pack/rocm
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
ARG VLLM_TORCH_ROCM_VERSION

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION}

RUN <<EOF
    # Torch

    # Install
    IFS="." read -r PYTHON_MAJOR PYTHON_MINOR <<< "${PYTHON_VERSION}"
    WHEEL_SUFFIX="cp${PYTHON_MAJOR}${PYTHON_MINOR}-linux_$(uname -m).whl"
    TRITON_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "triton" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCH_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCHVISION_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torchvision" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    TORCHAUDIO_URL="$(curl -sf "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')"
    if [[ -z "${TORCH_URL}" || -z "${TORCHVISION_URL}" || -z "${TORCHAUDIO_URL}" ]]; then
        echo "Failed to get ROCM PyTorch wheels for version ${VLLM_TORCH_VERSION} from radeon source."
        exit 1
    fi
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TRITON_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCH_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCHVISION_URL}"
    uv pip install "https://repo.radeon.com/rocm/manylinux/rocm-rel-${ROCM_VERSION}/${TORCHAUDIO_URL}"
    uv pip install \
        numpy scipy
        exit 0

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

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    VL_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${VL_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} <= 6.2" | bc -l) )); then
            VL_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx941;gfx942;gfx1030;gfx1100;gfx1101"
        elif (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            VL_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        else
            VL_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export PYTORCH_ROCM_ARCH="${VL_ROCM_ARCHS}"

    # Install
    EXTRA_INDEX_URL="https://download.pytorch.org/whl/rocm${ROCM_MAJOR}.${ROCM_MINOR}"
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        EXTRA_INDEX_URL="https://download.pytorch.org/whl/cpu/"
    fi
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm-${VLLM_VERSION}
    VLLM_TARGET_DEVICE="rocm" \
        uv pip install --no-build-isolation --verbose --extra-index-url ${EXTRA_INDEX_URL} \
        /tmp/vllm-${VLLM_VERSION}

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

## Install FlashAttention

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # FlashAttention

    if [[ ! -d /flashattention/workspace ]]; then
        echo "Skipping FlashAttention installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation --no-deps \
        /flashattention/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install AITER

RUN --mount=type=bind,from=vllm-build-aiter,source=/,target=/aiter,rw <<EOF
    # AITER

    if [[ ! -d /aiter/workspace ]]; then
        echo "Skipping AITER installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /aiter/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install LMCache

ARG VLLM_LMCACHE_VERSION

ENV VLLM_LMCACHE_VERSION=${VLLM_LMCACHE_VERSION}

RUN <<EOF
    # LMCache

    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L184-L237.

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    LC_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${LC_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} <= 6.2" | bc -l) )); then
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx941;gfx942;gfx1030;gfx1100;gfx1101"
        elif (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        else
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${LC_ROCM_ARCHS}"
    export TORCH_DONT_CHECK_COMPILER_ABI=1
    export CXX=hipcc
    export BUILD_WITH_HIP=1

    cat <<EOT >/tmp/requirements.txt
aiofile==3.9.0
aiofiles==25.1.0
awscrt==0.28.2
cufile-python==0.2.0
nvtx==0.2.13
sortedcontainers==2.4.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Install LMCache
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    fi
    uv pip install --no-build-isolation --no-deps --verbose \
        /tmp/lmcache

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
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

## Postprocess

RUN <<EOF
    # Postprocess

    # Review
    uv pip tree \
        --package vllm \
        --package flash_attn \
        --package triton \
        --package aiter \
        --package torch \
        --package lmcache
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_ROCR_VISIBLE_DEVICES=1 \
    RAY_EXPERIMENTAL_NOSET_HIP_VISIBLE_DEVICES=1 \
    TOKENIZERS_PARALLELISM=false \
    SAFETENSORS_FAST_GPU=1 \
    HIP_FORCE_DEV_KERNARG=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage SGLang Prepare
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm{ROCM_VERSION%.*}-sglang-prepare-linux-amd64 --target=sglang-build pack/rocm
#

FROM ${SGLANG_BASE_IMAGE} AS sglang-prepare
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

# Stage SGLang Prepare MoonCake
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-sglang-prepare-mooncake-linux-amd64 --target=sglang-prepare-mooncake pack/rocm
#

FROM sglang-prepare AS sglang-prepare-mooncake
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Prepare MoonCake

ARG CMAKE_MAX_JOBS
ARG SGLANG_MOONCAKE_VERSION

ENV SGLANG_MOONCAKE_VERSION=${SGLANG_MOONCAKE_VERSION} \
    PATH="/usr/local/go/bin:${PATH}"

RUN <<EOF
    # MoonCake

    # Build MoonCake
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    echo "Building MoonCake with the following environment variables:"
    env
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_MOONCAKE_VERSION} --single-branch \
        https://github.com/kvcache-ai/Mooncake.git mooncake
    pushd /tmp/mooncake \
        && bash dependencies.sh -y \
        && cmake -S . -B build -DBUILD_UNIT_TESTS=OFF -DUSE_HIP=ON -DUSE_HTTP=ON -DUSE_ETCD=ON -DSTORE_USE_ETCD=ON -DCMAKE_BUILD_TYPE=Release \
        && cmake --build build --target install -j${MAX_JOBS} \
        && ./scripts/build_wheel.sh \
        && tree -hs /tmp/mooncake/mooncake-wheel/dist/ \
        && mv /tmp/mooncake/mooncake-wheel/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage SGLang
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-sglang-linux-amd64 --target=sglang pack/rocm
#

FROM sglang-prepare AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install SGLang

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION

ENV SGLANG_VERSION=${SGLANG_VERSION}

RUN <<EOF
    # SGLang

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    SG_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${SG_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} <= 6.2" | bc -l) )); then
            SG_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx941;gfx942;gfx1030;gfx1100;gfx1101"
        elif (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            SG_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        else
            SG_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${SG_ROCM_ARCHS}"
    export AMDGPU_TARGET="gfx950"
    echo "Building SGLang with the following environment variables:"
    env

    # Download SGLang
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang-${SGLANG_VERSION}

    # Install SGLang
    # Copy config files to support MI300X in virtualized environments (MI300X_VF).
    # Symlinks will not be created in image build.
    # See https://github.com/sgl-project/sglang/blob/09938e1f82334a98c124ae3352d893480963775f/docker/rocm.Dockerfile#L197C2-L200.
    find /tmp/sglang-${SGLANG_VERSION}/python/sglang/srt/layers/quantization/configs/ \
         /tmp/sglang-${SGLANG_VERSION}/python/sglang/srt/layers/moe/fused_moe_triton/configs/ \
         -type f -name '*MI300X*' | xargs -I {} sh -c 'vf_config=$(echo "$1" | sed "s/MI300X/MI300X_VF/"); cp "$1" "$vf_config"' -- {}
    pushd /tmp/sglang-${SGLANG_VERSION}/python \
        && if [[ -f pyproject_other.toml ]]; then mv pyproject_other.toml pyproject.toml; fi \
        && uv pip install --verbose --no-deps .[all_hip]

    # Install SGLang Kernel
    pushd /tmp/sglang-${SGLANG_VERSION}/sgl-kernel \
        && if [[ -f pyproject_rocm.toml ]]; then mv pyproject_rocm.toml pyproject.toml; fi \
        && python setup_rocm.py install

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

## Install SGLang Router

RUN <<EOF
    # SGlang Router

    # Install Rust
    curl --retry 3 --retry-connrefused --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    export PATH="/root/.cargo/bin:${PATH}" \
        && rustc --version \
        && cargo --version

    # Install build tools
    uv pip install \
        setuptools-rust maturin

    # Install SGLang Router
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang
    pushd /tmp/sglang/sgl-router \
        && ulimit -n 65536 && maturin build --release --features vendored-openssl --out dist \
        && tree -hs /tmp/sglang/sgl-router/dist \
        && uv pip install --force-reinstall /tmp/sglang/sgl-router/dist/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /root/.cargo \
        && rm -rf /root/.rustup \
        && sed -i '$d' /root/.profile \
        && sed -i '$d' /root/.bashrc \
        && ccache --clear --clean
EOF

## Install MoonCake

RUN --mount=type=bind,from=sglang-prepare-mooncake,source=/,target=/mooncake,rw <<EOF
    # MoonCake

    if [[ ! -d /mooncake/workspace ]]; then
        echo "Skipping MoonCake installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /mooncake/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Fast-Hadamard-Transform

RUN <<EOF
    # Fast-Hadamard-Transform

    uv pip install \
        wheel==0.45.1

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export FAST_HADAMARD_TRANSFORM_SKIP_CUDA_BUILD="TRUE"
    echo "Building Fast-Hadamard-Transform with the following environment variables:"
    env

    # Install Fast-Hadamard-Transform
    git -C /tmp clone --recursive --shallow-submodules \
        --branch rocm --single-branch \
        https://github.com/jeffdaily/fast-hadamard-transform.git fast-hadamard-transform
    pushd /tmp/fast-hadamard-transform \
        && python setup.py install

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
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
        --package triton \
        --package vllm \
        --package torch \
        --package deep-ep
EOF

## Entrypoint

ENV HIP_FORCE_DEV_KERNARG=1 \
    HSA_NO_SCRATCH_RECLAIM=1 \
    SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 \
    SGLANG_INT4_WEIGHT=0 \
    SGLANG_MOE_PADDING=1 \
    SGLANG_ROCM_DISABLE_LINEARQUANT=0 \
    SGLANG_ROCM_FUSED_DECODE_MLA=1 \
    SGLANG_SET_CPU_AFFINITY=1\
    SGLANG_USE_AITER=1 \
    SGLANG_USE_ROCM700A=1 \
    NCCL_MIN_NCHANNELS=112 \
    VLLM_FP8_PADDING=1 \
    VLLM_FP8_ACT_PADDING=1 \
    VLLM_FP8_WEIGHT_PADDING=1 \
    VLLM_FP8_REDUCE_CONV=1 \
    TORCHINDUCTOR_MAX_AUTOTUNE=1 \
    TORCHINDUCTOR_MAX_AUTOTUNE_POINTWISE=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
