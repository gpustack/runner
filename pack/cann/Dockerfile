# Package logic:
# 1. runtime target:
#    - Install tools.
#    - Upgrade GCC if needed.
#    - Install C buildkit.
#    - Upgrade Python if needed.
#    - Install Python buildkit.
#    - Install CANN buildkit if needed.
# 2. mindie target.
#    - Install Torch.
#    - Install MindIE.
#    - Install dependencies.
#    - Postprocess, review installation.
# 3. vllm target.
#    - Install Torch.
#    - Install vLLM from source.
#    - Install vLLM-Ascend from source.
#    - Install dependencies.
#    - Postprocess, review installation.
# 4. sglang target.
#    - Install Torch.
#    - Install SGLang from source.
#    - Install SGLang Router from source.
#    - Install dependencies.
#    - Postprocess, review installation.

# Argument usage:
# - PYTHON_VERSION: Version of Python to use.
# - CMAKE_MAX_JOBS: Maximum number of jobs to use for CMake,
#   if not specified, it will be set automatically based on the number of CPU cores.
# - CANN_VERSION: Version of Ascend CANN runtime environment to use.
# - CANN_ARCHS: Arch variant list supports for this runtime environment,
#   it only support one architecture at present, eg. 310p, 910b and a3.
# - MINDIE_BASE_IMAGE: Base image for MindIE.
# - MINDIE_VERSION: Version of MindIE to use.
# - MINDIE_TORCH_VERSION: Version of Torch for MindIE to use.
# - VLLM_BASE_IMAGE: Base image for vLLM.
# - VLLM_VERSION: Version of vLLM to use.
# - VLLM_ASCEND_VERSION: Version of vLLM Ascend to use,
#   if not specified, it will fetch from the vLLM Ascend PyPi RSS.
# - VLLM_TORCH_VERSION: Version of Torch for vLLM to use.
# - SGLANG_BASE_IMAGE: Base image for SGLang.
# - SGLANG_VERSION: Version of SGLang to use.
# - SGLANG_TORCH_VERSION: Version of Torch for SGLang to use.
# - SGLANG_KERNEL_VERSION: Version of SGLang Kernel to use.
ARG PYTHON_VERSION=3.11
ARG CMAKE_MAX_JOBS
ARG CANN_VERSION=8.3.rc1
ARG CANN_ARCHS=910b
ARG MINDIE_BASE_IMAGE=gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-python${PYTHON_VERSION}
ARG MINDIE_VERSION=2.1.rc2
ARG MINDIE_TORCH_VERSION=2.1.0
ARG VLLM_BASE_IMAGE=gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-python${PYTHON_VERSION}
ARG VLLM_VERSION=0.11.0
ARG VLLM_ASCEND_VERSION=0.11.0rc1
ARG VLLM_TORCH_VERSION=2.7.1
ARG SGLANG_BASE_IMAGE=gpustack/runner:cann${CANN_VERSION}-${CANN_ARCHS}-python${PYTHON_VERSION}
ARG SGLANG_VERSION=0.5.2
ARG SGLANG_TORCH_VERSION=2.6.0
ARG SGLANG_KERNEL_VERSION=20251106

#
# Stage Bake Runtime
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-${CANN_ARCHS}-python${PYTHON_VERSION}-linux-amd64 --target=runtime pack/cann
#

FROM quay.io/ascend/cann:${CANN_VERSION}-${CANN_ARCHS}-ubuntu22.04-py${PYTHON_VERSION} AS runtime
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

## Install CANN buildkit if needed

ARG CANN_VERSION
ARG CANN_ARCHS

ENV CANN_HOME="/usr/local/Ascend" \
    CANN_VERSION=${CANN_VERSION} \
    CANN_ARCHS=${CANN_ARCHS}

RUN <<EOF
    # CANN Toolkit

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]]; then
        echo "Skipping CANN Toolkit upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Install dependencies
    cat <<EOT >/tmp/requirements.txt
attrs==24.3.0
numpy==1.26.4
decorator==5.2.1
sympy==1.14.0
cffi==1.17.1
PyYAML==6.0.2
pathlib2==2.3.7.post1
protobuf==6.31.0
scipy==1.15.3
requests==2.32.3
absl-py==2.2.2
EOT
    pip install -r /tmp/requirements.txt

    # Install toolkit
    TOOLKIT_FILE="Ascend-cann-toolkit_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    TOOLKIT_PATH="/tmp/${TOOLKIT_FILE}"
    TOOLKIT_URL="${URL_PREFIX}/${TOOLKIT_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${TOOLKIT_PATH}" "${TOOLKIT_URL}"
    chmod a+x "${TOOLKIT_PATH}"
    printf "Y\n" | "${TOOLKIT_PATH}" --install --install-for-all --install-path="${CANN_HOME}"

    # Cleanup
   rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend \
        && rm -rf /var/log/ascend_seclog
EOF

RUN <<EOF
    # CANN Kernels

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]]; then
        echo "Skipping CANN Kernels upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Prepare environment
    source ${CANN_HOME}/ascend-toolkit/set_env.sh

    # Install kernels
    KERNELS_FILE="Ascend-cann-kernels-${CANN_ARCHS}_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    if ! curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fsSIL "${URL_PREFIX}/${KERNELS_FILE}?${URL_SUFFIX}" >/dev/null 2>&1; then
        # Fallback to generic kernels
        KERNELS_FILE="Ascend-cann-kernels-${CANN_ARCHS}_${DOWNLOAD_VERSION}_${OS}.run"
    fi
    KERNELS_PATH="/tmp/${KERNELS_FILE}"
    KERNELS_URL="${URL_PREFIX}/${KERNELS_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${KERNELS_PATH}" "${KERNELS_URL}"
    chmod a+x "${KERNELS_PATH}"
    printf "Y\n" |"${KERNELS_PATH}" --install --install-for-all --install-path="${CANN_HOME}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend \
        && rm -rf /var/log/ascend_seclog
EOF

RUN <<EOF
    # CANN NNAL

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${CANN_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"

    if [[ -d "${CANN_HOME}/ascend-toolkit/${DOWNLOAD_VERSION}" ]] && [[ -d "${CANN_HOME}/nnal" ]]; then
        echo "Skipping CANN NNAL upgrade for ${DOWNLOAD_VERSION}..."
        exit 0
    fi

    # Prepare environment
    source ${CANN_HOME}/ascend-toolkit/set_env.sh

    # Install NNAL
    NNAL_FILE="Ascend-cann-nnal_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    NNAL_PATH="/tmp/${NNAL_FILE}"
    NNAL_URL="${URL_PREFIX}/${NNAL_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${NNAL_PATH}" "${NNAL_URL}"
    chmod a+x "${NNAL_PATH}"
    printf "Y\n" | "${NNAL_PATH}" --install --install-path="${CANN_HOME}"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt \
        && rm -rf /var/log/ascend_seclog \
        && rm -rf /var/log/cann_atb_log
EOF

## Declare Environment

ENV PATH="${CANN_HOME}/driver/tools:${PATH}"

# Stage Install MindIE
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-mindie{MINDIE_VERSION}-linux-arm64 --target=mindie pack/cann
#

FROM ${MINDIE_BASE_IMAGE} AS mindie
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Torch

ARG MINDIE_TORCH_VERSION

ENV MINDIE_TORCH_VERSION=${MINDIE_TORCH_VERSION}

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${MINDIE_TORCH_VERSION}
torchvision
torchaudio
EOT
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    else
        uv pip install \
            -r /tmp/requirements.txt
    fi
    uv pip install \
        torch-npu==${MINDIE_TORCH_VERSION}.*

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install MindIE

ARG MINDIE_VERSION

ENV MINDIE_VERSION=${MINDIE_VERSION}

ADD --chown=root:root mindie-atb-models_${MINDIE_VERSION}_${TARGETOS}-${TARGETARCH}_py${PYTHON_VERSION}_torch${MINDIE_TORCH_VERSION}-abi0.tar.gz ${CANN_HOME}/atb-models/
RUN <<EOF
    # MindIE

    # Install dependencies
    cat <<EOT >/tmp/requirements.txt
absl-py==2.2.2
accelerate==0.34.2
aiohappyeyeballs==2.6.1
aiohttp==3.12.15
aiosignal==1.4.0
attrs==24.3.0
certifi==2024.8.30
cloudpickle==3.0.0
cpm-kernels==1.0.11
decorator==5.2.1
easydict==1.13
einops==0.8.1
et-xmlfile==1.1.0
frozenlist==1.7.0
fuzzywuzzy==0.18.0
gevent==24.2.1
geventhttpclient==2.3.1
greenlet==3.2.1
grpcio==1.71.0
icetk==0.0.4
idna==2.8
jieba==0.42.1
Jinja2==3.1.6
jiter==0.11.0
joblib==1.4.2
json5==0.12.1
jsonlines==4.0.0
jsonschema==4.23.0
latex2mathml==3.77.0
loguru==0.7.2
Markdown==3.7
matplotlib==3.9.2
mdtex2html==1.3.0
ml_dtypes==0.5.0
multidict==6.4.3
nltk==3.9.1
numba==0.61.2
numpy==1.26.4
onnx==1.19.0
openai==1.108.1
opencv-python-headless==4.11.0.86
openpyxl==3.1.5
orjson==3.11.3
pandas==2.2.3
pillow==11.2.1
prettytable==3.11.0
propcache==0.3.1
psutil==7.0.0
pyarrow==19.0.1
pydantic_core==2.23.4
pydantic==2.9.2
python-rapidjson==1.20
requests==2.32.3
rouge-score==0.1.2
rouge==1.0.1
sacrebleu==2.4.3
scipy==1.15.3
text-generation==0.7.0
thefuzz==0.22.1
tiktoken==0.7.0
tornado==6.4.2
tqdm==4.67.1
transformers==4.51.3
safetensors==0.5.3
tritonclient==2.49.0
typing_extensions==4.13.2
tzdata==2024.2
urllib3==2.4.0
yarl==1.20.1
zope.event==5.0
zope.interface==7.0.3
EOT
    uv pip install \
        -r /tmp/requirements.txt

    # Install ATB models
    uv pip install \
        ${CANN_HOME}/atb-models/*.whl

    # Install MindIE
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    DOWNLOAD_VERSION="$(echo ${MINDIE_VERSION%\.beta1} | tr '[:lower:]' '[:upper:]')"
    URL_PREFIX="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/MindIE/MindIE%20${DOWNLOAD_VERSION}"
    URL_SUFFIX="response-content-type=application/octet-stream"
    MINDIE_FILE="Ascend-mindie_${DOWNLOAD_VERSION}_${OS}-${ARCH}.run"
    IFS="." read -r MINDIE_MAJOR MINDIE_MINOR MINDIE_PATCH <<< "${MINDIE_VERSION}"
    if (( $(echo "${MINDIE_MAJOR}.${MINDIE_MINOR} >= 2.1" | bc -l) )); then
        MINDIE_FILE="Ascend-mindie_${DOWNLOAD_VERSION}_${OS}-${ARCH}_abi0.run"
    fi
    MINDIE_PATH="/tmp/${MINDIE_FILE}"
    MINDIE_URL="${URL_PREFIX}/${MINDIE_FILE}?${URL_SUFFIX}"
    curl -H 'Referer: https://www.hiascend.com/' --retry 3 --retry-connrefused -fL -o "${MINDIE_PATH}" "${MINDIE_URL}"
    chmod a+x "${MINDIE_PATH}"
    printf "Y\n" | "${MINDIE_PATH}" --install --install-path="${CANN_HOME}"

    # Fix
    # - Make MindIE service configuration writable.
    chmod +w "${CANN_HOME}/mindie/latest/mindie-service/conf"

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Postprocess

RUN <<EOF
    # Postprocess

    # Hijack executable path
    mv ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon_
    PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
    cat <<EOT >${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon
#!/usr/bin/bash

# Argument
#
MINDIE_LOG_LEVEL=\${MINDIE_LOG_LEVEL:-INFO}
MIES_CERTS_LOG_LEVEL=\${MIES_CERTS_LOG_LEVEL:-INFO}
MINDIE_LLM_LOG_LEVEL=\${MINDIE_LLM_LOG_LEVEL:-WARN}
MINDIE_LLM_PYTHON_LOG_LEVEL=\${MINDIE_LLM_PYTHON_LOG_LEVEL:-WARN}
ASCEND_GLOBAL_LOG_LEVEL=\${ASCEND_GLOBAL_LOG_LEVEL:-3}
ASCEND_SLOG_LEVEL=\${ASCEND_SLOG_LEVEL:-WARN}
MINDIE_RT_LOG_LEVEL=\${MINDIE_RT_LOG_LEVEL:-3}
ATB_LOG_LEVEL=\${ATB_LOG_LEVEL:-ERROR}
ASDOPS_LOG_LEVEL=\${ASDOPS_LOG_LEVEL:-ERROR}
OCK_LOG_LEVEL=\${OCK_LOG_LEVEL:-ERROR}
LOG_LEVEL=\${LOG_LEVEL:-ERROR}
TORCH_AIE_LOG_LEVEL=\${TORCH_AIE_LOG_LEVEL:-3}
PYPI_PACKAGES_INSTALL=\${PYPI_PACKAGES_INSTALL:-}

# Prepare
#
if [[ -n "\${PYPI_PACKAGES_INSTALL}" ]]; then
    echo "Installing extra PyPi packages: \${PYPI_PACKAGES_INSTALL} ..."
    uv pip install \${PYPI_PACKAGES_INSTALL}
fi
export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}
source \${CANN_HOME}/ascend-toolkit/set_env.sh
source \${CANN_HOME}/nnal/atb/set_env.sh
source \${CANN_HOME}/atb-models/set_env.sh
source \${CANN_HOME}/mindie/set_env.sh

# Configure Logging
#
export MINDIE_LOG_LEVEL=\${MINDIE_LOG_LEVEL}
export MINDIE_LOG_TO_STDOUT=1
export MINDIE_LOG_TO_FILE=0
export MIES_CERTS_LOG_LEVEL=\${MIES_CERTS_LOG_LEVEL}
export MIES_CERTS_LOG_TO_STDOUT=1
export MIES_CERTS_LOG_TO_FILE=0
export MINDIE_LLM_LOG_LEVEL=\${MINDIE_LLM_LOG_LEVEL}
export MINDIE_LLM_LOG_TO_STDOUT=1
export MINDIE_LLM_LOG_TO_FILE=0
export MINDIE_LLM_PYTHON_LOG_LEVEL=\${MINDIE_LLM_PYTHON_LOG_LEVEL}
export MINDIE_LLM_PYTHON_LOG_TO_STDOUT=1
export MINDIE_LLM_PYTHON_LOG_TO_FILE=0
export ASCEND_GLOBAL_LOG_LEVEL=\${ASCEND_GLOBAL_LOG_LEVEL}
export ASCEND_GLOBAL_EVENT_ENABLE=0
export ASCEND_SLOG_LEVEL=\${ASCEND_SLOG_LEVEL}
export ASCEND_SLOG_PRINT_TO_STDOUT=1
export ASCEND_SLOG_PRINT_TO_FILE=0
export MINDIE_RT_LOG_LEVEL=\${MINDIE_RT_LOG_LEVEL}
export MINDIE_RT_LOG_PRINT_TO_STDOUT=1
export MINDIE_RT_LOG_PRINT_TO_FILE=0
export ATB_LOG_LEVEL=\${ATB_LOG_LEVEL}
export ATB_LOG_TO_STDOUT=1
export ATB_LOG_TO_FILE=0
export ATB_STREAM_SYNC_EVERY_KERNEL_ENABLE=0
export ATB_LOG_TO_FILE_FLUSH=0
export ASDOPS_LOG_LEVEL=\${ASDOPS_LOG_LEVEL}
export ASDOPS_LOG_TO_STDOUT=1
export ASDOPS_LOG_TO_FILE=0
export OCK_LOG_LEVEL=\${OCK_LOG_LEVEL}
export OCK_LOG_TO_STDOUT=1
export OCK_LOG_TO_FILE=0
export LOG_LEVEL=\${LOG_LEVEL}
export LOG_TO_STDOUT=1
export LOG_TO_FILE=0
export TORCH_AIE_LOG_LEVEL=\${TORCH_AIE_LOG_LEVEL}
export TORCH_AIE_PRINT_TO_STDOUT=1
export TORCH_AIE_PRINT_TO_FILE=0

# Execute
#
echo "Starting MindIE Service Daemon ..."
if [[ \${MINDIE_LOG_LEVEL} == "DEBUG" ]]; then
	echo "With envs:"
	env
fi
cd \$(dirname \${BASH_SOURCE[0]})/..
echo "On:"
pwd
./bin/\$(basename \${BASH_SOURCE[0]})_ "\$@"
EOT
    chmod a+x ${CANN_HOME}/mindie/latest/mindie-service/bin/mindieservice_daemon

    # Review
    uv pip tree
EOF

## Entrypoint

ENV PATH="${CANN_HOME}/mindie/latest/mindie-service/bin:${PATH}"

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage Install vLLM
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-vllm${VLLM_VERSION}-linux-arm64 --target=vllm pack/cann
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

ENV VLLM_TORCH_VERSION=${VLLM_TORCH_VERSION}

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${VLLM_TORCH_VERSION}
torchvision
torchaudio
EOT
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    else
        uv pip install \
            -r /tmp/requirements.txt
    fi
    uv pip install --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
        torch-npu==${VLLM_TORCH_VERSION}.*
    uv pip install \
        numpy spicy

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install vLLM

ARG CMAKE_MAX_JOBS
ARG VLLM_VERSION
ARG VLLM_ASCEND_VERSION

ENV VLLM_VERSION=${VLLM_VERSION} \
    VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION}

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
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/Ascend/ascend-toolkit/latest/$(uname -i)-linux/devlib"

    # Install vLLM
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm-${VLLM_VERSION}
    VLLM_TARGET_DEVICE="empty" \
        uv pip install --verbose --extra-index-url https://download.pytorch.org/whl/cpu/ \
        /tmp/vllm-${VLLM_VERSION}
    # Fix
    # - vLLM Ascend doesn't support triton, uninstall it.
    uv pip uninstall triton || true

    # Install vLLM Ascend
    VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION:-}
    if [[ -z "${VLLM_ASCEND_VERSION}" ]]; then
        # Fetch the latest version from RSS subscription.
        VLLM_ASCEND_VERSION="$(curl -sS https://pypi.org/rss/project/vllm-ascend/releases.xml | grep title | grep "${VLLM_VERSION}" | head -n 1 | awk -F '[<>]' '/<title>/ {print $3}')"
    fi
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${VLLM_ASCEND_VERSION} --single-branch \
        https://github.com/vllm-project/vllm-ascend.git vllm-ascend-${VLLM_ASCEND_VERSION}
    VLLM_TARGET_DEVICE="empty" \
        uv pip install --verbose --extra-index-url https://download.pytorch.org/whl/cpu/ --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
        /tmp/vllm-ascend-${VLLM_ASCEND_VERSION}
    # Fix
    # - Replace SoC version instead of compile.
    if [[ "${CANN_ARCHS}" == "310p" ]]; then
        sed -i "s/^__soc_version__.*/__soc_version__ = 'ASCEND310P3'/" $(pip show vllm-ascend | grep Location: | cut -d':' -f 2)/vllm_ascend/_build_info.py
    fi

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install Dependencies

RUN <<EOF
    # Dependencies

    # Install
    cat <<EOT >/tmp/requirements.txt
accelerate
hf_transfer
modelscope
ray[client]>=2.47.1,<=2.48.0
ray[default]>=2.47.1,<=2.48.0
protobuf>3.20.0
grpcio==1.71.0
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

    # Hijack executable path
    PYTHON_LIB_PREFIX=$(python3 -c "import sys; print(sys.base_prefix);")
    mv ${PYTHON_LIB_PREFIX}/bin/vllm ${PYTHON_LIB_PREFIX}/bin/vllm_
    cat <<EOT >${PYTHON_LIB_PREFIX}/bin/vllm
#!/usr/bin/bash

source \${CANN_HOME}/ascend-toolkit/set_env.sh
source \${CANN_HOME}/nnal/atb/set_env.sh

export LD_LIBRARY_PATH=${PYTHON_LIB_PREFIX}/lib:${PYTHON_LIB_PREFIX}/lib64:\${LD_LIBRARY_PATH}

exec \${BASH_SOURCE[0]}_ "\$@"
EOT
    chmod a+x ${PYTHON_LIB_PREFIX}/bin/vllm

    # Review
    uv pip tree \
        --package vllm \
        --package vllm-ascend \
        --package torch \
        --package torch-npu
EOF

## Entrypoint

ENV RAY_EXPERIMENTAL_NOSET_ASCEND_RT_VISIBLE_DEVICES=1

WORKDIR /
ENTRYPOINT [ "tini", "--" ]

# Stage Install SGLang
#
# Example build command:
#   docker build --progress=plain --platform=linux/arm64 --file=pack/cann/Dockerfile --tag=gpustack/runner:cann${CANN_VERSION%.*}-sglang${SGLANG_VERSION}-linux-arm64 --target=sglang pack/cann
#
FROM ${SGLANG_BASE_IMAGE} AS sglang
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

ENV UV_SYSTEM_PYTHON=1 \
    UV_PRERELEASE=allow

## Install Tools

RUN <<EOF
    # Tools

    # Install
    apt-get update -y && apt-get install -y --no-install-recommends \
        libgrpc-dev \
        libgrpc++-dev \
        libprotobuf-dev \
        protobuf-compiler \
        protobuf-compiler-grpc

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/* \
        && rm -rf /var/cache/apt
EOF

## Install Torch

ARG SGLANG_TORCH_VERSION

ENV SGLANG_TORCH_VERSION=${SGLANG_TORCH_VERSION}

RUN <<EOF
    # Torch

    # Install Torch
    cat <<EOT >/tmp/requirements.txt
torch==${SGLANG_TORCH_VERSION}
torchvision
torchaudio
EOT
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --extra-index-url https://download.pytorch.org/whl/cpu/ \
            -r /tmp/requirements.txt
    else
        uv pip install \
            -r /tmp/requirements.txt
    fi
    uv pip install --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi \
        torch-npu==${SGLANG_TORCH_VERSION}.*
    uv pip install \
        numpy==1.26.4 scipy==1.13.1

    # Cleanup
    rm -rf /var/tmp/* \
        && rm -rf /tmp/*
EOF

## Install SGLang

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

    # Install vLLM
    SGLANG_VLLM_VERSION=0.8.5
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VLLM_VERSION} --single-branch \
        https://github.com/vllm-project/vllm.git vllm-${SGLANG_VLLM_VERSION}
    VLLM_TARGET_DEVICE="empty" \
        uv pip install --verbose --extra-index-url https://download.pytorch.org/whl/cpu/ \
        /tmp/vllm-${SGLANG_VLLM_VERSION}

    # Install Dependencies
    cat <<EOT >/tmp/requirements.txt
attrs==24.2.0
decorator==5.1.1
psutil==6.0.0
pytest==8.3.2
pytest-xdist==3.6.1
pyyaml
EOT
    uv pip install \
        -r /tmp/requirements.txt
    if [[ "${TARGETARCH}" == "amd64" ]]; then
        uv pip install --verbose \
            https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/sglang/triton_ascend-3.2.0.dev20250923-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
    else
        uv pip install --verbose \
            https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/sglang/triton_ascend-3.2.0%2Bgitb0ea0850-cp311-cp311-linux_aarch64.whl
    fi

    # Install SGLang
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch v${SGLANG_VERSION} --single-branch \
        https://github.com/sgl-project/sglang.git sglang-${SGLANG_VERSION}
    pushd /tmp/sglang-${SGLANG_VERSION}/python \
        && if [[ -f pyproject_other.toml ]]; then mv pyproject_other.toml pyproject.toml; fi \
        && uv pip install --verbose .[srt_npu]

    export LD_LIBRARY_PATH="${CANN_HOME}/ascend-toolkit/latest/runtime/lib64/stub:${LD_LIBRARY_PATH}"
    source ${CANN_HOME}/ascend-toolkit/set_env.sh

    # Install SGLang Kernel
    git -C /tmp clone --recursive --shallow-submodules \
        --depth 1 --branch ${SGLANG_KERNEL_VERSION} --single-branch \
        https://github.com/sgl-project/sgl-kernel-npu.git sgl-kernel-npu
    pushd /tmp/sgl-kernel-npu \
        && ./build.sh \
        && tree -hs /tmp/sgl-kernel-npu/output \
        && uv pip install /tmp/sgl-kernel-npu/output/deep_ep*.whl /tmp/sgl-kernel-npu/output/sgl_kernel_npu*.whl

    # Postprocess SGLang Kernel (DeepEP)
    cd "$(pip show deep-ep | awk '/^Location:/ {print $2}')" && ln -s deep_ep/deep_ep_cpp*.so

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

## Install Custom Ops

RUN <<EOF
    # Custom Ops

    if [[ "${TARGETARCH}" == "amd64" ]]; then
        echo "Skipping Custom Ops installation on ${TARGETARCH}..."
        exit 0
    fi

    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    UV_SKIP_WHEEL_FILENAME_CHECK=1 uv pip install --verbose \
        https://sglang-ascend.obs.cn-east-3.myhuaweicloud.com/ops/custom_ops-1.0.${CANN_ARCHS}-cp311-cp311-${OS}_${ARCH}.whl

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
        --package sgl-kernel-npu \
        --package deep-ep \
        --package triton-ascend \
        --package custom-ops \
        --package vllm \
        --package torch \
        --package torch-npu
EOF

## Entrypoint

WORKDIR /
ENTRYPOINT [ "tini", "--" ]
