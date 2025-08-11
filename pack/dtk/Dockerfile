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
# 3. vllm target:
#    - Postprocess, review installation.

# Argument usage:
# - PYTHON_VERSION: Version of Python to use.
# - CMAKE_MAX_JOBS: (PLACEHOLDER) Maximum number of jobs to use for CMake, default is empty,
#   which means it will use the number of available CPU cores.
# - DTK_VERSION: Version of Hygon DTK runtime environment to use.
# - DTK_ARCHS: (PLACEHOLDER) Arch variant list supports for this runtime environment.
# - VOXBOX_BASE_IMAGE: Base image for VoxBox.
# - VOXBOX_VERSION: Version of VoxBox to use.
# - VOXBOX_TORCH_VERSION: Version of Torch for VoxBox to use.
# - VLLM_BASE_IMAGE: Base image for vLLM.
# - VLLM_VERSION: Version of vLLM to use.
# - VLLM_TORCH_VERSION: (PLACEHOLDER) Version of Torch for vLLM to use.
ARG PYTHON_VERSION=3.10
ARG CMAKE_MAX_JOBS
ARG DTK_VERSION=25.04.1
ARG DTK_ARCHS
ARG VOXBOX_BASE_IMAGE=gpustack/runner:dtk${DTK_VERSION}-python${PYTHON_VERSION}
ARG VOXBOX_VERSION=0.0.19
ARG VOXBOX_TORCH_VERSION=2.7.1
ARG VLLM_BASE_IMAGE=gpustack/runner:dtk${DTK_VERSION}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.8.5
ARG VLLM_TORCH_VERSION=2.4.1

# Stage Bake Runtime
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/dtk/Dockerfile --tag=gpustack/runner:dtk${DTK_VERSION%.*}-python${PYTHON_VERSION}-linux-amd64 --target=runtime pack/dtk
#

FROM gpustack/runner:dtk${DTK_VERSION}-python${PYTHON_VERSION}-vanilla AS runtime
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

## Install tools

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
    if (( $(echo "${VERSION_ID} > 21.04" | bc -l) )); then
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
pybind11
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

ARG DTK_VERSION
ARG DTK_ARCHS

ENV DTK_HOME="/opt/dtk" \
    DTK_VERSION=${DTK_VERSION} \
    DTK_ARCHS=${DTK_ARCHS}

# Stage Install VoxBox
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/dtk/Dockerfile --tag=gpustack/runner:dtk{DTK_VERSION%.*}-voxbox${VOXBOX_VERSION}-linux-amd64 --target=voxbox pack/dtk
#

FROM ${VOXBOX_BASE_IMAGE} AS voxbox
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ARG VOXBOX_VERSION
ARG VOXBOX_TORCH_VERSION

ENV VOXBOX_VERSION=${VOXBOX_VERSION} \
    VOXBOX_TORCH_VERSION=${VOXBOX_TORCH_VERSION} \
    UV_SYSTEM_PYTHON=1

## Install Torch

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${VOXBOX_TORCH_VERSION}
torchvision
torchaudio
EOT
    uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
        -r /tmp/requirements.txt
    uv pip install \
        numpy spicy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install VoxBox

RUN <<EOF
    # VoxBox

    # Install
    cat <<EOT >/tmp/requirements.txt
transformers==4.51.3
numba==0.61.2
llvmlite==0.44.0  # Compatible with Python 3.11
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

    # Link if needed
    if [[ ! -d ${DTK_HOME} ]] && [[ -d /opt/dtk-${DTK_VERSION} ]]; then
        ln -vsf /opt/dtk-${DTK_VERSION} ${DTK_HOME}
    fi
    if [[ ! -d /opt/hyhal ]] && [[ -d /opt/dtk-${DTK_VERSION}/.hyhal ]]; then
        ln -vsf /opt/dtk-${DTK_VERSION}/.hyhal /opt/hyhal
    fi

    # Review
    uv pip tree \
        --package vox-box \
        --package torch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage Install vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/amd64 --file=pack/dtk/Dockerfile --tag=gpustack/runner:dtk${DTK_VERSION%.*}-vllm${VLLM_VERSION}-linux-amd64 --target=vllm pack/dtk
#

FROM ${VLLM_BASE_IMAGE} AS vllm
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ARG VLLM_VERSION
ARG VLLM_TORCH_VERSION

ENV VLLM_VERSION=${VLLM_VERSION} \
    VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION} \
    UV_SYSTEM_PYTHON=1

## Install Torch
##
## Nothing to do, as the Torch has installed in global.

## Install vLLM
##
## Nothing to do, as the vLLM has installed in global.

## Postprocess

RUN <<EOF
    # Postprocess

    # Link if needed
    if [[ ! -d ${DTK_HOME} ]] && [[ -d /opt/dtk-${DTK_VERSION} ]]; then
        ln -vsf /opt/dtk-${DTK_VERSION} ${DTK_HOME}
    fi
    if [[ ! -d /opt/hyhal ]] && [[ -d /opt/dtk-${DTK_VERSION}/.hyhal ]]; then
        ln -vsf /opt/dtk-${DTK_VERSION}/.hyhal /opt/hyhal
    fi

    # Review
    uv pip tree \
        --package vllm \
        --package torch
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
