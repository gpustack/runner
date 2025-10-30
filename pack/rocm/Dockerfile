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
#    - Install Dependencies.
# 2.2. vllm-build-triton target.
# 2.3. vllm-build-flashattention target.
# 2.4. vllm-build-aiter target.
# 2.5. vllm target.
#    - Install Torch.
#    - Install vLLM from source.
#    - Install Triton if existed.
#    - Install FlashAttention if existed.
#    - Install AITER if existed.
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
# - VLLM_TRITON_REPOSITORY: Repository URL of Triton to use,
#   which is used to build the Triton wheel.
# - VLLM_TRITON_VERSION: Version of Triton to use,
#   which is used to build the Triton wheel.
# - VLLM_FLASHATTENTION_REPOSITORY: Repository URL of FlashAttention to use,
#   which is used to build the FlashAttention wheel.
# - VLLM_FLASHATTENTION_VERSION: Version of FlashAttention to use,
#   which is used to build the FlashAttention wheel.
# - VLLM_AITER_REPOSITORY: Repository URL of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_AITER_VERSION: Version of AITER to use,
#   which is used to build the AITER wheel.
# - VLLM_LMCACHE_VERSION: Version of lmcache to use.
ARG PYTHON_VERSION=3.12
ARG CMAKE_MAX_JOBS
ARG ROCM_VERSION=7.0.2
ARG ROCM_ARCHS
ARG VLLM_BASE_IMAGE=gpustack/runner:rocm${ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.11.0
ARG VLLM_TORCH_SOURCE=radeon
ARG VLLM_TORCH_VERSION=2.8.0
ARG VLLM_TORCH_ROCM_VERSION=${ROCM_VERSION}
ARG VLLM_BUILD_BASE_IMAGE=gpustack/runner:rocm${VLLM_TORCH_ROCM_VERSION}-python${PYTHON_VERSION}
ARG VLLM_TRITON_REPOSITORY=https://github.com/triton-lang/triton.git
ARG VLLM_TRITON_VERSION=3.5.0
ARG VLLM_FLASHATTENTION_REPOSITORY=https://github.com/Dao-AILab/flash-attention.git
ARG VLLM_FLASHATTENTION_VERSION=2.8.3
ARG VLLM_AITER_REPOSITORY=https://github.com/ROCm/aiter.git
ARG VLLM_AITER_VERSION=0.1.5.post4
ARG VLLM_LMCACHE_VERSION=0.3.8

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

ARG VLLM_TRITON_VERSION
ARG VLLM_TORCH_SOURCE
ARG VLLM_TORCH_VERSION
ARG VLLM_TORCH_ROCM_VERSION

ENV VLLM_TRITON_VERSION=${VLLM_TRITON_VERSION} \
    VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION}

RUN <<EOF
    # Torch

    # Install from radeon source.
    if [[ "${VLLM_TORCH_SOURCE}" == "radeon" ]]; then
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
    fi

    # Install from pytorch source.
    cat <<EOT >/tmp/requirements.txt
triton=${VLLM_TRITON_VERSION}
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --index-url https://download.pytorch.org/whl/rocm${ROCM_MAJOR}.${ROCM_MINOR} \
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
ARG VLLM_TRITON_REPOSITORY
ARG VLLM_TRITON_VERSION

ENV VLLM_TRITON_REPOSITORY=${VLLM_TRITON_REPOSITORY} \
    VLLM_TRITON_VERSION=${VLLM_TRITON_VERSION}

RUN <<EOF
    # Triton

    IFS="." read -r TORCH_MAJOR TORCH_MINOR TORCH_PATCH <<< "${VLLM_TORCH_VERSION}"
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    IFS="." read -r TT_MAJOR TT_MINOR TT_PATCH <<< "${VLLM_TRITON_VERSION}"

    # Support ARM64 only
    if [[ "${TARGETARCH}" != "amd64" ]]; then
        echo "Skipping Triton building for ${TARGETARCH}..."
        exit 0
    fi

    # Dependencies
    cat <<EOT >/tmp/requirements.txt
ninja>=1.11.1
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_TRITON_VERSION} --single-branch \
        ${VLLM_TRITON_REPOSITORY} triton

    # Build
    CMAKE_MAX_JOBS="${CMAKE_MAX_JOBS}"
    if [[ -z "${CMAKE_MAX_JOBS}" ]]; then
        CMAKE_MAX_JOBS="$(( $(nproc) / 2 ))"
    fi
    if (( $(echo "${CMAKE_MAX_JOBS} > 8" | bc -l) )); then
        CMAKE_MAX_JOBS="8"
    fi
    TT_ROCM_ARCHS="$(echo ${ROCM_ARCHS} | sed -e 's/;gfx1[0-9]\{3\}//g')"
    if [[ -z "${TT_ROCM_ARCHS}" ]]; then
        if (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} <= 6.2" | bc -l) )); then
            TT_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx941;gfx942;gfx1030;gfx1100;gfx1101"
        elif (( $(echo "${ROCM_MAJOR}.${ROCM_MINOR} < 7.0" | bc -l) )); then
            TT_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        else
            TT_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
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
          && cp /tmp/triton/python/triton_kernels/dist/*.whl /workspace
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
ARG VLLM_FLASHATTENTION_REPOSITORY
ARG VLLM_FLASHATTENTION_VERSION

ENV VLLM_FLASHATTENTION_REPOSITORY=${VLLM_FLASHATTENTION_REPOSITORY} \
    VLLM_FLASHATTENTION_VERSION=${VLLM_FLASHATTENTION_VERSION}

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
        ${VLLM_FLASHATTENTION_REPOSITORY} flashattention

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
ARG VLLM_AITER_REPOSITORY
ARG VLLM_AITER_VERSION

ENV VLLM_AITER_REPOSITORY=${VLLM_AITER_REPOSITORY} \
    VLLM_AITER_VERSION=${VLLM_AITER_VERSION}

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

    # Install Dependencies
    uv pip install --reinstall \
        pybind11>=3.0.1

    # Prepare
    TORCH_LIB_PREFIX=$(pip show torch | grep Location: | cut -d' ' -f 2)
    echo "${TORCH_LIB_PREFIX}/torch/lib" >> /etc/ld.so.conf.d/python3.conf

    # Download
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_AITER_VERSION} --single-branch \
        ${VLLM_AITER_REPOSITORY} aiter

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
    export LD_LIBRARY_PATH="${TORCH_LIB_PREFIX}/torch/lib:${LD_LIBRARY_PATH}"
    export BUILD_TARGET="rocm"
    export PREBUILD_KERNELS=1
    echo "Building AITER with the following environment variables:"
    env
    pushd /tmp/aiter \
      && python -v -m build --verbose --no-isolation --wheel \
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

ARG VLLM_TRITON_VERSION
ARG VLLM_TORCH_SOURCE
ARG VLLM_TORCH_VERSION
ARG VLLM_TORCH_ROCM_VERSION

ENV VLLM_TRITON_VERSION=${VLLM_TRITON_VERSION} \
    VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    VLLM_TORCH_ROCM_VERSION=${VLLM_TORCH_ROCM_VERSION}

RUN <<EOF
    # Torch

    # Install from radeon source.
    if [[ "${VLLM_TORCH_SOURCE}" == "radeon" ]]; then
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
    fi

    # Install from pytorch source.
    cat <<EOT >/tmp/requirements.txt
triton=${VLLM_TRITON_VERSION}
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    IFS="." read -r ROCM_MAJOR ROCM_MINOR ROCM_PATCH <<< "${VLLM_TORCH_ROCM_VERSION}"
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --index-url https://download.pytorch.org/whl/rocm${ROCM_MAJOR}.${ROCM_MINOR} \
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
            VL_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
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
        && rm -rf /tmp/*
EOF

## Instal Triton

RUN --mount=type=bind,from=vllm-build-triton,source=/,target=/triton,rw <<EOF
    # Triton

    if [[ ! -d /triton/workspace ]]; then
        echo "Skipping Triton installation for ${TARGETARCH}..."
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
            LC_ROCM_ARCHS="gfx900;gfx906;gfx908;gfx90a;gfx942;gfx950;gfx1030;gfx1100;gfx1101;gfx1102;gfx1200;gfx1201"
        fi
    fi
    export MAX_JOBS="${CMAKE_MAX_JOBS}"
    export PYTORCH_ROCM_ARCH="${LC_ROCM_ARCHS}"
    export TORCH_DONT_CHECK_COMPILER_ABI=1
    export CXX=hipcc
    export BUILD_WITH_HIP=1

    # Install LMCache
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_LMCACHE_VERSION} --single-branch \
        https://github.com/LMCache/LMCache.git lmcache
    if [[ "${TARGETARCH}" == "arm64" ]]; then
        sed -i "s/^infinistore$/infinistore; platform_machine == 'x86_64'/" /tmp/lmcache/requirements/common.txt
    fi
    uv pip install --no-build-isolation --verbose \
        /tmp/lmcache

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
