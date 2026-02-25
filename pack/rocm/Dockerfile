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
#    - Build FashAttention.
#    - Build AITER.
#    - Build vLLM.
#    - Build LMCache.
#    - Build MoonCake.
# 2.2. vllm target.
#    - Install Torch.
#    - Install Triton if existed.
#    - Install FlashAttention.
#    - Install AITER.
#    - Install vLLM.
#    - Install LMCache.
#    - Install MoonCake.
#    - Install dependencies.
#    - Postprocess, review installation.
# 3.1. sglang-build target.
#    - Install Torch.
#    - Build SGLang.
#    - Build SGLang Router.
# 3.2. sglang target.
#    - Install Torch.
#    - Install SGLang.
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
# - VLLM_TORCH_SOURCE: Source of Torch to use for vLLM,
#   which is used to build the components that depend on Torch.
# - VLLM_BUILD_BASE_IMAGE: Base image for vLLM build,
#   which is used to build wheels.
# - VLLM_TRITON_COMMIT: Commit of Triton to use for vLLM.
# - VLLM_FLASHATTENTION_VERSION: Version of FlashAttention to use,
#   which is used to build the FlashAttention wheel.
# - VLLM_AITER_REPOSITORY: Repository URL of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_AITER_VERSION: Version of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_LMCACHE_VERSION: Version of LMCache to use.
# - VLLM_MOONCAKE_VERSION: Version of MoonCake to use.
# - VLLM_OMNI_COMMIT: Commit of Omni to use,
#   which is used to build the Omni wheel.
# - SGLANG_BASE_IMAGE: Base image for SGLang.
# - SGLANG_VERSION: Version of SGLang to use.
# - SGLANG_BUILD_BASE_IMAGE: Base image for SGLang build,
#   which is used to build the SGLang from source.
# - SGLANG_ROUTER_COMMIT: Commit of SGLang Router to use,
#   which is used to build the SGLang Router wheel.
ARG PYTHON_VERSION=3.12
ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.0.2
ARG ROCM_ARCHS
ARG VLLM_BASE_IMAGE=gpustack/runner:rocm${ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.16.0
ARG VLLM_TORCH_VERSION=2.9.1
ARG VLLM_TORCH_ROCM_VERSION=${ROCM_VERSION}
ARG VLLM_TORCH_SOURCE=pytorch
ARG VLLM_BUILD_BASE_IMAGE=gpustack/runner:rocm${VLLM_TORCH_ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_TRITON_COMMIT=57c693b6
ARG VLLM_MORI_COMMIT=20920706
ARG VLLM_FLASHATTENTION_VERSION=2.8.3
ARG VLLM_AITER_VERSION=0.1.10.post3
ARG VLLM_LMCACHE_VERSION=0.3.14
ARG VLLM_MOONCAKE_VERSION=0.3.9
ARG VLLM_OMNI_COMMIT=d6a3551a
ARG SGLANG_BASE_IMAGE=vllm
ARG SGLANG_VERSION=0.5.9
ARG SGLANG_BUILD_BASE_IMAGE=vllm-build
ARG SGLANG_ROUTER_COMMIT=c1f2241a

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
setuptools>=77.0.3,<80.0.0
setuptools-scm
packaging<25
wheel==0.45.1
pybind11<3
Cython
psutil
pipx<=1.8.0
uv<=0.9.11
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

    export UV_SYSTEM_PYTHON=1
    export UV_PRERELEASE=allow
    uv pip install --no-build-isolation \
        /opt/rocm/share/amd_smi
    uv pip tree

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
ARG VLLM_TORCH_SOURCE

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION} \
    VLLM_TORCH_SOURCE=${VLLM_TORCH_SOURCE}

RUN <<EOF
    # Torch

    # Install
    if [[ "${VLLM_TORCH_SOURCE}" == "radeon" ]]; then
        IFS="." read -r PYTHON_MAJOR PYTHON_MINOR <<< "${PYTHON_VERSION}"
        IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
        WHEEL_PREFIX="https://repo.radeon.com/rocm/manylinux/rocm-rel-${VLLM_TORCH_ROCM_VERSION}/"
        WHEEL_SUFFIX="cp${PYTHON_MAJOR}${PYTHON_MINOR}-linux_$(uname -m).whl"
        TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "triton-" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TRITON_URL}" ]]; then
            TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "triton-" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCH_TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "pytorch_triton_rocm-" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCH_TRITON_URL}" ]]; then
            TORCH_TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "pytorch_triton_rocm-" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCH_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCH_URL}" ]]; then
            TORCH_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCHVISION_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchvision" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCHVISION_URL}" ]]; then
            TORCHVISION_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchvision" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${TORCH_MAJOR}.${TORCH_MINOR}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${TORCH_MAJOR}.${TORCH_MINOR}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCH_URL}" || -z "${TORCHVISION_URL}" || -z "${TORCHAUDIO_URL}" ]]; then
            echo "Failed to get ROCM PyTorch wheels for version ${VLLM_TORCH_VERSION} from radeon source."
            exit 1
        fi
        if [[ -n "${TRITON_URL}" ]]; then
            uv pip install "${WHEEL_PREFIX}/${TRITON_URL}"
        fi
        if [[ -n "${TORCH_TRITON_URL}" ]]; then
            uv pip install "${WHEEL_PREFIX}/${TORCH_TRITON_URL}"
        fi
        uv pip install "${WHEEL_PREFIX}/${TORCH_URL}"
        uv pip install "${WHEEL_PREFIX}/${TORCHVISION_URL}"
        uv pip install "${WHEEL_PREFIX}/${TORCHAUDIO_URL}"
    else
        cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
        IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
        uv pip install --index-url https://download.pytorch.org/whl/rocm${ROCM_MAJOR}.${ROCM_MINOR} \
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

    # Install
    cat <<EOT >/tmp/requirements.txt
setuptools>=77.0.3,<80.0.0
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

# Stage vLLM Build Triton
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-triton-linux-amd64 --target=vllm-build-triton pack/rocm
#

FROM vllm-build AS vllm-build-triton
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build Triton

ARG CMAKE_MAX_JOBS
ARG VLLM_TRITON_COMMIT

ENV VLLM_TRITON_COMMIT=${VLLM_TRITON_COMMIT}

RUN <<EOF
    # Triton

    if pip show triton >/dev/null 2>&1; then
        echo "Skipping Triton building as installed..."
        exit 0
    fi

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r TT_MAJOR TT_MINOR TT_PATCH <<< "${VLLM_TRITON_VERSION}"

    # Dependencies
    cat <<EOT >/tmp/requirements.txt
ninja>=1.11.1
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/ROCm/triton.git triton \
        && pushd /tmp/triton \
        && git checkout ${VLLM_TRITON_COMMIT} \
        && git submodule update --init --recursive

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    TT_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${TT_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            TT_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
        else
            TT_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${TT_ROCM_ARCHS}"
    echo "Building Triton with the following environment variables:"
    env

    pushd /tmp/triton \
      && python -v -m build --no-isolation --wheel \
      && tree -hs /tmp/triton/dist \
      && mv /tmp/triton/dist /workspace
    if [[ -d /tmp/triton/python/triton_kernels ]]; then
        pushd /tmp/triton/python/triton_kernels \
          && python -v -m build --no-isolation --wheel \
          && tree -hs /tmp/triton/python/triton_kernels/dist \
          && mv /tmp/triton/python/triton_kernels/dist/*.whl /workspace
    fi

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

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # AITER

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r AT_MAJOR AT_MINOR AT_PATCH <<< "${VLLM_AITER_VERSION}"

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
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            AT_ROCM_ARCHS="gfx942"
        else
            AT_ROCM_ARCHS="gfx942;gfx950"
        fi
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

# Stage vLLM Build MORI
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-epkernels-mori-linux-amd64 --target=vllm-build-epkernels-mori pack/rocm
#

FROM vllm-build AS vllm-build-epkernels-mori
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build MORI

ARG CMAKE_MAX_JOBS
ARG VLLM_MORI_COMMIT

ENV VLLM_MORI_COMMIT=${VLLM_MORI_COMMIT}

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # MORI

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    # Dependencies
    apt-get install -y --no-install-recommends \
        libpci-dev

    # Prepare
    TORCH_LIB_PREFIX=$(pip show torch | grep Location: | cut -d' ' -f 2)
    echo "${TORCH_LIB_PREFIX}/torch/lib" >> /etc/ld.so.conf.d/python3.conf

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/ROCm/mori.git mori \
        && pushd /tmp/mori \
        && git checkout ${VLLM_MORI_COMMIT} \
        && git submodule update --init --recursive

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    MR_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${MR_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            MR_ROCM_ARCHS="gfx942"
        else
            MR_ROCM_ARCHS="gfx942;gfx950"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${MR_ROCM_ARCHS}"
    export GPU_ARCH="${MR_ROCM_ARCHS}"
    export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/local/lib:${TORCH_LIB_PREFIX}/torch/lib:${LD_LIBRARY_PATH}"
    echo "Building MORI with the following environment variables:"
    env
    pushd /tmp/mori \
      && python setup.py bdist_wheel --dist-dir=dist \
      && tree -hs /tmp/mori/dist \
      && mv /tmp/mori/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-vllm-linux-amd64 --target=vllm-build-vllm pack/rocm
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

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw \
    --mount=type=bind,from=vllm-build-aiter,source=/,target=/aiter,rw <<EOF
    # vLLM

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r VL_MAJOR VL_MINOR VL_PATCH <<< "${VLLM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    VL_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${VL_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
            if (( $(echo "${VL_MAJOR}.${VL_MINOR} >= 0.13" | bc -l) )); then
                # TODO(thxCode): Temporarily remove gfx1030 for vLLM ROCm build due to build error in ROCm 6.4.4.
                # #15 134.9 /tmp/vllm/build/temp.linux-x86_64-cpython-312/csrc/sampler.hip:564:63: error: local memory (66032) exceeds limit (65536) in 'void vllm::topKPerRowDecode<1024, true, false, true>(float const*, int const*, int*, int, int, int, int, float*, int, int const*)'
                # ##15 134.9   564 | static __global__ __launch_bounds__(kNumThreadsPerBlock) void topKPerRowDecode(
                # ##15 134.9       |                                                               ^
                # ##15 134.9 16 warnings and 1 error generated when compiling for gfx1030.
                VL_ROCM_ARCHS="gfx908;gfx90a;gfx942"
            fi
        else
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export PYTORCH_ROCM_ARCH="${VL_ROCM_ARCHS}"
    export VLLM_TARGET_DEVICE="rocm"
    echo "Building vLLM with the following environment variables:"
    env

    # Build
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm
    pushd /tmp/vllm \
        && sed -i "s/\"torch ==.*\"/\"torch\"/g" /tmp/vllm/pyproject.toml \
        && sed -i "s/\"torch==.*\"/\"torch\"/g" /tmp/vllm/requirements/rocm-build.txt \
        && sed -i "s/\"torchvision==.*\"/\"torchvision\"/g" /tmp/vllm/requirements/rocm-build.txt \
        && sed -i "s/\"torchaudio==.*\"/\"torchaudio\"/g" /tmp/vllm/requirements/rocm-build.txt \
        && if [[ "${VLLM_TORCH_SOURCE}" == "radeon" ]]; then sed -i "s/\"triton==.*\"/\"triton\"/g" /tmp/vllm/requirements/rocm-build.txt; fi \
        && uv pip install grpcio-tools==1.78.0 \
        && VLLM_TARGET_DEVICE="rocm" python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/vllm/dist \
        && mv /tmp/vllm/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage vLLM Build Omni
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm{ROCM_VERSION%.*}-vllm-build-omni-linux-amd64 --target=vllm-build-omni pack/rocm
#

FROM vllm-build AS vllm-build-omni
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build Omni

ARG CMAKE_MAX_JOBS
ARG VLLM_OMNI_COMMIT

ENV VLLM_OMNI_COMMIT=${VLLM_OMNI_COMMIT}

RUN --mount=type=bind,from=vllm-build-vllm,source=/,target=/vllm,rw <<EOF
    # Omni

    if [[ -z "${VLLM_OMNI_COMMIT}" ]]; then
        echo "Skipping vLLM Omni build for ${TARGETARCH}..."
        exit 0
    fi

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r VL_MAJOR VL_MINOR VL_PATCH <<< "${VLLM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 4" | bc -l) )); then
        CMAKE_MAX_JOBS="4"
    fi
    VL_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${VL_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
            if (( $(echo "${VL_MAJOR}.${VL_MINOR} == 0.13" | bc -l) )); then
                # TODO(thxCode): Temporarily remove gfx1030 for vLLM ROCm build due to build error in ROCm 6.4.4.
                # #15 134.9 /tmp/vllm/build/temp.linux-x86_64-cpython-312/csrc/sampler.hip:564:63: error: local memory (66032) exceeds limit (65536) in 'void vllm::topKPerRowDecode<1024, true, false, true>(float const*, int const*, int*, int, int, int, int, float*, int, int const*)'
                # ##15 134.9   564 | static __global__ __launch_bounds__(kNumThreadsPerBlock) void topKPerRowDecode(
                # ##15 134.9       |                                                               ^
                # ##15 134.9 16 warnings and 1 error generated when compiling for gfx1030.
                VL_ROCM_ARCHS="gfx908;gfx90a;gfx942"
            fi
        else
            VL_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export COMPILE_CUSTOM_KERNELS=1
    export PYTORCH_ROCM_ARCH="${VL_ROCM_ARCHS}"
    echo "Building vLLM Omni with the following environment variables:"
    env

    # Build
    git -C /tmp clone --recursive --shallow-submodules \
        https://github.com/vllm-project/vllm-omni vllm_omni \
        && pushd /tmp/vllm_omni \
        && git checkout ${VLLM_OMNI_COMMIT} \
        && git submodule update --init --recursive
    pushd /tmp/vllm_omni \
        && sed -i "/\"fa3-fwd.*\"/d" /tmp/vllm_omni/pyproject.toml \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/vllm_omni/dist \
        && mv /tmp/vllm_omni/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage vLLM Build LMCache
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-lmcache-linux-amd64 --target=vllm-build-lmcache pack/rocm
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
    # Ref https://github.com/LMCache/LMCache/blob/5afe9688b3519074b9915e7b3acf871328250150/docs/source/getting_started/installation.rst?plain=1#L184-L237.

    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"

    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    LC_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${LC_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            LC_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
        else
            LC_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${LC_ROCM_ARCHS}"
    export TORCH_DONT_CHECK_COMPILER_ABI=1
    export CXX=hipcc
    export BUILD_WITH_HIP=1
    echo "Building LMCache with the following environment variables:"
    env

    # Build
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    pushd /tmp/lmcache \
        && sed -i "s/\"torch==.*\"/\"torch\"/g" /tmp/lmcache/pyproject.toml \
        && cat /tmp/lmcache/pyproject.toml \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/lmcache/dist \
        && mv /tmp/lmcache/dist /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage vLLM Build MoonCake
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-vllm-build-mooncake-linux-amd64 --target=vllm-build-mooncake pack/rocm
#

FROM vllm-build AS vllm-build-mooncake
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build MoonCake

ARG CMAKE_MAX_JOBS
ARG VLLM_MOONCAKE_VERSION

ENV VLLM_MOONCAKE_VERSION=${VLLM_MOONCAKE_VERSION} \
    PATH="/usr/local/go/bin:${PATH}"

RUN --mount=type=bind,from=vllm-build-vllm,source=/,target=/vllm,rw <<EOF
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
        --depth 1 --branch v${VLLM_MOONCAKE_VERSION} --single-branch \
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
    UV_PRERELEASE=allow \
    UV_SKIP_WHEEL_FILENAME_CHECK=1

## Install Torch

ARG VLLM_TORCH_VERSION
ARG VLLM_TORCH_ROCM_VERSION
ARG VLLM_TORCH_SOURCE

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION} \
    VLLM_TORCH_SOURCE=${VLLM_TORCH_SOURCE}

RUN <<EOF
    # Torch

    # Install
    if [[ "${VLLM_TORCH_SOURCE}" == "radeon" ]]; then
        IFS="." read -r PYTHON_MAJOR PYTHON_MINOR <<< "${PYTHON_VERSION}"
        IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
        WHEEL_PREFIX="https://repo.radeon.com/rocm/manylinux/rocm-rel-${VLLM_TORCH_ROCM_VERSION}/"
        WHEEL_SUFFIX="cp${PYTHON_MAJOR}${PYTHON_MINOR}-linux_$(uname -m).whl"
        TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "triton-" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TRITON_URL}" ]]; then
            TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "triton-" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCH_TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "pytorch_triton_rocm-" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCH_TRITON_URL}" ]]; then
            TORCH_TRITON_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "pytorch_triton_rocm-" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCH_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCH_URL}" ]]; then
            TORCH_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torch-${VLLM_TORCH_VERSION}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCHVISION_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchvision" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCHVISION_URL}" ]]; then
            TORCHVISION_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchvision" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${VLLM_TORCH_VERSION}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${TORCH_MAJOR}.${TORCH_MINOR}" | grep -v lw | grep -v dev | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCHAUDIO_URL}" ]]; then
            TORCHAUDIO_URL="$(curl -sf "${WHEEL_PREFIX}" | grep "torchaudio-${TORCH_MAJOR}.${TORCH_MINOR}" | grep -v lw | grep "${WHEEL_SUFFIX}" | tail -n 1 | sed -n 's/.*href="\([^"]*\)".*/\1/p' || echo "")"
        fi
        if [[ -z "${TORCH_URL}" || -z "${TORCHVISION_URL}" || -z "${TORCHAUDIO_URL}" ]]; then
            echo "Failed to get ROCM PyTorch wheels for version ${VLLM_TORCH_VERSION} from radeon source."
            exit 1
        fi
        if [[ -n "${TRITON_URL}" ]]; then
            uv pip install "${WHEEL_PREFIX}/${TRITON_URL}"
        fi
        if [[ -n "${TORCH_TRITON_URL}" ]]; then
            uv pip install "${WHEEL_PREFIX}/${TORCH_TRITON_URL}"
        fi
        uv pip install "${WHEEL_PREFIX}/${TORCH_URL}"
        uv pip install "${WHEEL_PREFIX}/${TORCHVISION_URL}"
        uv pip install "${WHEEL_PREFIX}/${TORCHAUDIO_URL}"
    else
        cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
        IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
        uv pip install --index-url https://download.pytorch.org/whl/rocm${ROCM_MAJOR}.${ROCM_MINOR} \
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

    # Install
    cat <<EOT >/tmp/requirements.txt
setuptools>=77.0.3,<80.0.0
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

## Install Omni

RUN --mount=type=bind,from=vllm-build-omni,source=/,target=/omni,rw <<EOF
    # Omni

    if [[ ! -d /omni/workspace ]]; then
        echo "Skipping vLLM Omni installation for ${TARGETARCH}..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation \
        /omni/workspace/*.whl

    # Dependencies
    uv pip uninstall onnxruntime || true
    cat <<EOT >/tmp/requirements.txt
onnxruntime-rocm
sox
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install EP Kenerls: MORI

RUN --mount=type=bind,from=vllm-build-epkernels-mori,source=/,target=/mori,rw <<EOF
    # MORI

    # Install
    uv pip install --no-build-isolation \
        /mori/workspace/*.whl

    # Dependencies
    apt-get install -y --no-install-recommends \
        libpci-dev

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install Triton

RUN --mount=type=bind,from=vllm-build-triton,source=/,target=/triton,rw <<EOF
    # Triton

    if pip show triton >/dev/null 2>&1; then
        echo "Skipping Triton building as installed..."
        exit 0
    fi

    # Install
    uv pip install --no-build-isolation --no-deps \
        /triton/workspace/*.whl

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install FlashAttention

RUN --mount=type=bind,from=vllm-build-flashattention,source=/,target=/flashattention,rw <<EOF
    # FlashAttention

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

    # Install
    uv pip install --no-build-isolation \
        /aiter/workspace/*.whl

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

## Install MoonCake

RUN --mount=type=bind,from=vllm-build-mooncake,source=/,target=/mooncake,rw <<EOF
    # MoonCake

    # Install
    uv pip install --no-build-isolation \
        /mooncake/workspace/*.whl

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
    cat <<EOT >/tmp/requirements.txt
# dockerfile extras
accelerate
hf_transfer
modelscope
aiofile==3.9.0
aiofiles==25.1.0
awscrt==0.28.2
cufile-python==0.2.0
nvtx==0.2.13
sortedcontainers==2.4.0

# audio extras
librosa
soundfile
mistral_common[audio]

# petit extras
petit-kernel
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
        --package vllm-omni \
        --package flash-attn \
        --package triton \
        --package aiter \
        --package torch \
        --package lmcache \
        --package mooncake-transfer-engine
EOF

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    tree -hs /workspace/patches
    pushd $(pip show vllm | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/vllm/*.patch
    if pip show vllm_omni > /dev/null 2>&1; then \
        pushd $(pip show vllm_omni | grep Location: | cut -d" " -f 2) \
            && patch -p1 < /workspace/patches/vllm_omni/*.patch; \
    fi
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_ROCR_VISIBLE_DEVICES=1 \
    RAY_EXPERIMENTAL_NOSET_HIP_VISIBLE_DEVICES=1 \
    TOKENIZERS_PARALLELISM=false \
    SAFETENSORS_FAST_GPU=1 \
    HIP_FORCE_DEV_KERNARG=1 \
    HSA_NO_SCRATCH_RECLAIM=1 \
    VLLM_ROCM_USE_AITER=1 \
    VLLM_FP8_PADDING=1 \
    VLLM_FP8_ACT_PADDING=1 \
    VLLM_FP8_WEIGHT_PADDING=1 \
    VLLM_FP8_REDUCE_CONV=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage SGLang Build
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm{ROCM_VERSION%.*}-sglang-build-linux-amd64 --target=sglang-build pack/rocm
#

FROM ${SGLANG_BUILD_BASE_IMAGE} AS sglang-build
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    cat <<EOT >/tmp/requirements.txt
setuptools>=77.0.3,<80.0.0
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

# Stage SGLang Build SGLang
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-sglang-build-sglang-linux-amd64 --target=sglang-build-sglang pack/rocm
#

FROM sglang-build AS sglang-build-sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build SGLang

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
    SG_ROCM_ARCHS="${ROCM_ARCHS}"
    if [[ -z "${SG_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            SG_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx1030;gfx1100"
        else
            SG_ROCM_ARCHS="gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1200;gfx1201;gfx1150;gfx1151"
        fi
    fi
    SK_ROCM_ARCHS="gfx950"
    if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
        SK_ROCM_ARCHS="gfx942"
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${SG_ROCM_ARCHS}"
    export AMDGPU_TARGET="${SK_ROCM_ARCHS}"
    echo "Building SGLang with the following environment variables:"
    env

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang

    # Build SGLang
    # Copy config files to support MI300X in virtualized environments (MI300X_VF).
    # Symlinks will not be created in image build.
    # See https://github.com/sgl-project/sglang/blob/09938e1f82334a98c124ae3352d893480963775f/docker/rocm.Dockerfile#L197C2-L200.
    find /tmp/sglang/python/sglang/srt/layers/quantization/configs/ \
         /tmp/sglang/python/sglang/srt/layers/moe/fused_moe_triton/configs/ \
         -type f -name '*MI300X*' | xargs -I {} sh -c 'vf_config=$(echo "$1" | sed "s/MI300X/MI300X_VF/"); cp "$1" "$vf_config"' -- {}
    pushd /tmp/sglang/python \
        && uv pip install grpcio-tools==1.75.1 \
        && cp /tmp/sglang/README.md /tmp/sglang/LICENSE . \
        && if [[ -f pyproject_other.toml ]]; then mv pyproject_other.toml pyproject.toml; fi \
        && sed -i "s/\"torch==.*\"/\"torch\"/g" /tmp/sglang/python/pyproject.toml \
        && sed -i "s/\"torchaudio==.*\"/\"torchaudio\"/g" /tmp/sglang/python/pyproject.toml \
        && cat /tmp/sglang/python/pyproject.toml \
        && python -v -m build --no-isolation --wheel \
        && tree -hs /tmp/sglang/python/dist \
        && mv /tmp/sglang/python/dist /workspace

    # Build SGLang Kernel
    pushd /tmp/sglang/sgl-kernel \
        && if [[ -f pyproject_rocm.toml ]]; then mv pyproject_rocm.toml pyproject.toml; fi \
        && python setup_rocm.py bdist_wheel --dist-dir=dist \
        && tree -hs /tmp/sglang/sgl-kernel/dist \
        && mv /tmp/sglang/sgl-kernel/dist/*.whl /workspace

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && ccache --clear --clean
EOF

# Stage SGLang Build SGLang Router
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-sglang-build-sglangrouter-linux-amd64 --target=sglang-build-sglangrouter pack/rocm
#

FROM sglang-build AS sglang-build-sglangrouter
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Build SGLang Router

ARG CMAKE_MAX_JOBS
ARG SGLANG_ROUTER_COMMIT

ENV SGLANG_ROUTER_COMMIT=${SGLANG_ROUTER_COMMIT}

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
        https://github.com/sgl-project/sglang.git sglang \
        && pushd /tmp/sglang \
        && git checkout ${SGLANG_ROUTER_COMMIT} \
        && git submodule update --init --recursive

    # Build
    pushd /tmp/sglang/sgl-model-gateway/bindings/python \
        && ulimit -n 65536 && maturin build --release --features vendored-openssl --out dist \
        && tree -hs /tmp/sglang/sgl-model-gateway/bindings/python/dist \
        && mv /tmp/sglang/sgl-model-gateway/bindings/python/dist /workspace

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
#   docker build --progress=plain --platform=linux/amd64 --file=pack/rocm/Dockerfile --tag=gpustack/runner:rocm${ROCM_VERSION%.*}-sglang-linux-amd64 --target=sglang pack/rocm
#

FROM ${SGLANG_BASE_IMAGE} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow \
    UV_SKIP_WHEEL_FILENAME_CHECK=1

## Install SGLang

ARG CMAKE_MAX_JOBS
ARG SGLANG_VERSION
ARG SGLANG_ROUTER_COMMIT

ENV SGLANG_VERSION=${SGLANG_VERSION} \
    SGLANG_ROUTER_COMMIT=${SGLANG_ROUTER_COMMIT}

RUN --mount=type=bind,from=sglang-build-sglang,source=/,target=/sglang,rw \
    --mount=type=bind,from=sglang-build-sglangrouter,source=/,target=/sglangrouter,rw <<EOF
    # SGLang

    # Install
    uv pip install \
        "$(ls /sglang/workspace/sglang-*.whl)[srt_hip]"
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        # Install SGLang Diffusion Extension
        uv pip install \
            "$(ls /sglang/workspace/sglang-*.whl)[diffusion_hip]"
    fi
    uv pip install \
        "$(ls /sglang/workspace/sgl_kernel-*.whl)"
    uv pip install --force-reinstall \
        /sglangrouter/workspace/*.whl

    # Uninstall
    ## Remove Run:AI Model Streamer to avoid peak memory usage in model loading.
    uv pip uninstall \
        runai-model-streamer || true

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Fast-Hadamard-Transform

RUN <<EOF
    # Fast-Hadamard-Transform

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
        --package flash-attn \
        --package triton \
        --package vllm \
        --package torch \
        --package deep-ep \
        --package ipython \
        --package mooncake-transfer-engine
EOF

## Patch

RUN --mount=type=bind,target=/workspace,rw <<EOF
    # Patch

    tree -hs /workspace/patches
    pushd $(pip show sglang | grep Location: | cut -d" " -f 2) \
        && patch -p1 < /workspace/patches/sglang/*.patch
EOF

## Entrypoint

ENV SGLANG_DISABLE_CUDNN_CHECK=1 \
    SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 \
    SGLANG_INT4_WEIGHT=0 \
    SGLANG_MOE_PADDING=1 \
    SGLANG_SET_CPU_AFFINITY=1 \
    SGLANG_ROCM_DISABLE_LINEARQUANT=0 \
    SGLANG_ROCM_FUSED_DECODE_MLA=1 \
    SGLANG_USE_AITER=1 \
    SGLANG_USE_ROCM700A=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
